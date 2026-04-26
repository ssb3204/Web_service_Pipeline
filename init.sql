-- ============================================================
-- 이벤트 로그 파이프라인 - DB 스키마 초기화
-- ============================================================
-- 이 파일은 PostgreSQL 컨테이너가 최초 기동될 때 자동 실행된다
-- (docker-entrypoint-initdb.d 규칙에 따라 /docker-entrypoint-initdb.d/ 에 마운트)
-- ============================================================


-- ------------------------------------------------------------
-- users 테이블
-- 서비스에 가입된 유저 정보를 저장한다
-- ------------------------------------------------------------
CREATE TABLE users (
    user_id     VARCHAR(20) PRIMARY KEY,
    name        VARCHAR(50) NOT NULL,
    created_at  TIMESTAMP   NOT NULL,
    device_type VARCHAR(10) NOT NULL
                CHECK (device_type IN ('mobile', 'desktop'))
);


-- ------------------------------------------------------------
-- events 테이블
-- 유저 행동 이벤트 로그를 저장한다 (append-only, 비정규화)
-- ------------------------------------------------------------
CREATE TABLE events (
    event_id    VARCHAR(20) PRIMARY KEY,
    user_id     VARCHAR(20) REFERENCES users(user_id),
    session_id  VARCHAR(20) NOT NULL,
    event_type  VARCHAR(10) NOT NULL
                CHECK (event_type IN ('view', 'cart', 'purchase')),
    error_check BOOLEAN     NOT NULL DEFAULT FALSE,
    lecture_id  VARCHAR(10),
    timestamp   TIMESTAMP   NOT NULL
);


-- ------------------------------------------------------------
-- 인덱스
-- ------------------------------------------------------------
-- 시간대별 이벤트 추이 분석에서 timestamp 컬럼으로 GROUP BY / 필터링 발생
-- 풀스캔 대신 정렬된 색인으로 빠르게 접근하기 위한 인덱스
CREATE INDEX idx_events_timestamp ON events(timestamp);

-- 유저별 전환 분석에서 user_id 컬럼으로 GROUP BY / 필터링 발생
-- FK는 PostgreSQL에서 자동 인덱싱되지 않으므로 명시적으로 추가
CREATE INDEX idx_events_user_id ON events(user_id);


-- ------------------------------------------------------------
-- agg_event_summary 테이블
-- raw events를 (시 단위 bucket_hour, user_id, event_type)으로 사전 집계한 wide fact 테이블.
-- 분석 쿼리는 모두 이 테이블에서 GROUP BY 조합으로 수행하며,
-- raw events 직접 쿼리와 EXPLAIN ANALYZE 비교 대상이 된다.
-- ------------------------------------------------------------
CREATE TABLE agg_event_summary (
    bucket_hour TIMESTAMP   NOT NULL,
    user_id     VARCHAR(20) NOT NULL REFERENCES users(user_id),
    event_type  VARCHAR(10) NOT NULL
                CHECK (event_type IN ('view', 'cart', 'purchase')),
    event_count INT         NOT NULL CHECK (event_count >= 0),
    error_count INT         NOT NULL
                CHECK (error_count >= 0 AND error_count <= event_count),
    PRIMARY KEY (bucket_hour, user_id, event_type)
);
