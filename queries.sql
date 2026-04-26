-- ============================================================
-- 분석 쿼리 — 라이브클래스 이벤트 로그 파이프라인
-- ============================================================
-- 본 파일은 분석 쿼리 3개를 raw events 직접 / agg_event_summary 두 가지로 작성하고,
-- 동일 결과를 내는지 + EXPLAIN ANALYZE로 실행 비용을 비교한다.
--
-- 분석 스토리:
--   "유저가 강의를 몇 번 조회한 후 구매로 이어지는지 전환 흐름을 파악하고,
--    어느 단계에서 에러가 주로 발생하는지 서비스 안정성을 모니터링한다.
--    동시에 시간대별 트래픽 패턴을 통해 운영 시점을 진단한다."
--
-- agg_event_summary 도입 효과 요약 (50K events / 32K agg rows 기준):
--   Q1: raw 9.84ms / agg 4.99ms  (~2x)   ← raw는 50K Sort 필요
--   Q2: raw 5.95ms / agg 5.26ms  (소폭)  ← 둘 다 HashAggregate
--   Q3: raw 4.47ms / agg 2.74ms  (~1.6x)
--   buffers 사용량은 모든 쿼리에서 일관되게 ~54% 감소 (516 → 238 페이지).
--   50K 스케일에선 ms 단위 차이지만 데이터가 10x~100x 늘면 격차 확대.
-- ============================================================


-- ============================================================
-- Q1. 시간대별 이벤트 추이 (0~23시 분포)
-- ============================================================
-- 분석 목적: 하루 중 어느 시간대에 트래픽이 몰리는지 파악.
-- 운영 측면(서버 스케일링), 마케팅 측면(푸시 발송 시점) 모두에 활용.

-- ---------- raw events 직접 ----------
SELECT
    EXTRACT(HOUR FROM timestamp)::INT AS hour,
    COUNT(*) AS event_count
FROM events
GROUP BY hour
ORDER BY hour;

-- EXPLAIN ANALYZE (raw):
--   Seq Scan on events (50,000 rows)
--     -> Sort (Sort Key: hour, quicksort 1.5MB)  ← 50K 행 정렬 비용 발생
--       -> GroupAggregate
--   Buffers: shared hit=519
--   Execution Time: 9.842 ms

-- ---------- agg_event_summary 활용 ----------
SELECT
    EXTRACT(HOUR FROM bucket_hour)::INT AS hour,
    SUM(event_count) AS event_count
FROM agg_event_summary
GROUP BY hour
ORDER BY hour;

-- EXPLAIN ANALYZE (agg):
--   Seq Scan on agg_event_summary (32,084 rows)
--     -> HashAggregate (Memory: 73kB)            ← 행 수 적어 정렬 없이 해시 집계
--       -> Sort (Sort Key: hour, 24 rows only)
--   Buffers: shared hit=238
--   Execution Time: 4.994 ms

-- 비교: agg가 약 2x 빠름. raw는 50K 행 정렬 후 그룹핑이라 비용이 큼.
--      agg는 (bucket_hour, user_id, event_type)으로 사전 집계되어 있어 행 수 자체가 적음.


-- ============================================================
-- Q2. 이벤트 비율 — 타입별 발생 비율 + 타입별 에러율 (한 쿼리)
-- ============================================================
-- 분석 목적: 트래픽 구성(view 압도적인지) + 단계별 안정성(어느 단계 에러율 높은지)를
--           한 결과 테이블에서 동시에 확인. 시각화 시 한 차트에 매핑 가능.

-- ---------- raw events 직접 ----------
SELECT
    event_type,
    COUNT(*) AS event_total,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total,
    SUM(CASE WHEN error_check THEN 1 ELSE 0 END) AS error_total,
    ROUND(
        SUM(CASE WHEN error_check THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0),
        2
    ) AS error_rate_pct
FROM events
GROUP BY event_type
ORDER BY event_total DESC;

-- EXPLAIN ANALYZE (raw):
--   Seq Scan on events (50,000 rows, width=6)
--     -> HashAggregate (3 groups, 24kB)
--       -> WindowAgg (전체 합계 윈도우)
--   Buffers: shared hit=516
--   Execution Time: 5.952 ms

-- ---------- agg_event_summary 활용 ----------
SELECT
    event_type,
    SUM(event_count) AS event_total,
    ROUND(SUM(event_count) * 100.0 / SUM(SUM(event_count)) OVER (), 2) AS pct_of_total,
    SUM(error_count) AS error_total,
    ROUND(
        SUM(error_count) * 100.0 / NULLIF(SUM(event_count), 0),
        2
    ) AS error_rate_pct
FROM agg_event_summary
GROUP BY event_type
ORDER BY event_total DESC;

-- EXPLAIN ANALYZE (agg):
--   Seq Scan on agg_event_summary (32,084 rows, width=13)
--     -> HashAggregate (3 groups, 24kB)
--       -> WindowAgg
--   Buffers: shared hit=238
--   Execution Time: 5.259 ms

-- 비교: 실행 시간 차이는 작지만 (둘 다 동일한 HashAggregate 패턴),
--      agg는 buffers를 절반 미만으로 사용 (516 → 238). 데이터 증가 시 차이 확대 예상.


-- ============================================================
-- Q3. 조회 대비 구매 전환율
-- ============================================================
-- 분석 목적: 전체 view 중 purchase로 이어진 비율. 서비스 핵심 KPI.
-- 본 데이터에서는 1.09% (목표 ACTION_RATIO 2/96 ≈ 2.08%의 절반 수준 — 벨커브 폴백 영향).

-- ---------- raw events 직접 ----------
SELECT
    SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS view_count,
    SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchase_count,
    ROUND(
        SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) * 100.0
        / NULLIF(SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END), 0),
        2
    ) AS conversion_pct
FROM events;

-- EXPLAIN ANALYZE (raw):
--   Seq Scan on events (50,000 rows, width=5)
--     -> Aggregate (단일 행 결과)
--   Buffers: shared hit=516
--   Execution Time: 4.469 ms

-- ---------- agg_event_summary 활용 ----------
SELECT
    SUM(CASE WHEN event_type = 'view' THEN event_count ELSE 0 END) AS view_count,
    SUM(CASE WHEN event_type = 'purchase' THEN event_count ELSE 0 END) AS purchase_count,
    ROUND(
        SUM(CASE WHEN event_type = 'purchase' THEN event_count ELSE 0 END) * 100.0
        / NULLIF(SUM(CASE WHEN event_type = 'view' THEN event_count ELSE 0 END), 0),
        2
    ) AS conversion_pct
FROM agg_event_summary;

-- EXPLAIN ANALYZE (agg):
--   Seq Scan on agg_event_summary (32,084 rows, width=9)
--     -> Aggregate (단일 행 결과)
--   Buffers: shared hit=238
--   Execution Time: 2.741 ms

-- 비교: agg가 약 1.6x 빠름. 같은 단일 패스 Aggregate지만 입력 행 수 자체가 적어 시간 단축.
