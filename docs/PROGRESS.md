# 진행 상황 로그 (PROGRESS)

본 문서는 날짜별 작업 진행 상황을 기록한다. 최신 항목이 위로 오도록 append 한다.

진행 상황 요약은 `CLAUDE.md`의 "작업 진행 상황" 섹션과 중복되나, 이 파일은 **장기 누적 로그** 성격이고 CLAUDE.md는 **현재 스냅샷** 성격이라는 점에서 분리되어 있다.

---

## 전체 파이프라인 체크리스트

과제 원 프롬프트 기준 5단계. 현 상태 기준.

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 1 | 이벤트 생성기 (`event_generator.py`) | 코드 작성 완료 / DB 연결 검증 대기 | state machine 모델 전환, 50K/60일/Zipf/±20%/30분 세션 |
| 2 | 저장소 (`init.sql` + PostgreSQL) | 부분 (raw 완료, agg 미추가) | `agg_event_summary` 추가 필요 |
| 3 | 분석 쿼리 (`queries.sql`) | 미착수 | 3개로 변경. raw vs agg EXPLAIN ANALYZE 비교 포함 |
| 4 | Docker Compose (전체 기동) | 부분 | DB 서비스만 존재. app 서비스 추가 필요 |
| 5 | 시각화 | 미착수 | 도구 미결정 (Streamlit/Metabase/Grafana 후보) |
| - | README.md | 미착수 | DECISIONS.md에서 발췌해 작성 예정 |
| - | `requirements.txt` | 미착수 | psycopg2-binary 등 |
| - | `scripts/extract_weights.py` | 완료 | 일회성 가중치 추출 유틸리티 |

---

## 2026-04-26 (세션 4)

### 세션 범위
Step 4 마무리 (Dockerfile + app 서비스), `queries.sql` 작성, GitHub 리포 생성·분할 커밋 push, README 작성. 이번 세션으로 시각화(Step 5)를 제외한 모든 항목 완료.

### 수행
- **`requirements.txt` 작성** — `psycopg2-binary==2.9.12`, `tzdata==2026.2`. 처음 핀 고정한 2.9.10이 Python 3.14 wheel을 제공하지 않아 2.9.12로 상향 (#27)
- **venv에 의존성 설치 + import 검증** — `psycopg2.extras.execute_values`, `zoneinfo("Asia/Seoul")` 둘 다 동작 확인
- **`event_generator.py` DB 연결 검증** — `docker compose up -d db` → `python event_generator.py` 실행. 첫 시도 시 `event_id` UUID(36자)가 `VARCHAR(20)`을 초과해 실패 → ID 형식 결정 (#28)
- **ID 형식: 순차 채택** (#28) — UUID 대신 `evt_NNNNN` (5자리), `sess_NNNNN` (5자리). 로그 가독성 우선, 단일 머신이라 분산 충돌 무관
  - VARCHAR(20) 그대로 유지 (타이트닝은 디스크 영향 없고 작업 비용 큼, #29)
  - 통계 검증: view 48,620 (97.24%) / cart 851 (1.70%) / purchase 529 (1.06%) / errors 328 (0.66%) / 29,788 sessions
- **`init.sql`에 `agg_event_summary` 추가** — `(bucket_hour, user_id, event_type)` PK wide fact, `error_count <= event_count` CHECK
  - 라이브 DB에도 동일 DDL 직접 적용 (재기동 없이 동기화)
- **`event_generator.py`에 `aggregate_to_summary` ETL 추가** — `TRUNCATE agg_event_summary` 후 `INSERT INTO ... SELECT ... GROUP BY date_trunc('hour', timestamp), user_id, event_type`. 백필 1회 모드라 idempotent 보장
  - 검증: agg_rows=32,084 / total_events=50,000 / total_errors=328 → raw와 정확히 일치
- **`queries.sql` 작성** — 3개 분석을 raw/agg 양 버전으로 작성, EXPLAIN ANALYZE 결과 주석 첨부
  - Q1 시간대 추이 / Q2 이벤트 비율(타입+에러) / Q3 전환율
  - 측정: Q1 raw 9.84ms vs agg 4.99ms (~2x), Q2 5.95 vs 5.26ms, Q3 4.47 vs 2.74ms (~1.6x). buffers는 일관 ~54% 감소
- **`Dockerfile` 작성** — `python:3.14-slim` 베이스, 의존성 레이어 캐싱, `TZ=Asia/Seoul` 환경변수
- **`docker-compose.yml`에 app 서비스 추가** — `build: .`, `depends_on: db service_healthy`, `restart: no`, `DB_HOST=db`
- **전체 자동 기동 검증** — `down -v` 후 `up --build --abort-on-container-exit --exit-code-from app` 한 번으로 db 기동 → app 빌드·실행 → 50K events + 32K agg INSERT → app exit 0 → db 정상 종료까지 깔끔하게 흘러감
- **GitHub 리포 생성** — `https://github.com/ssb3204/-_-_-` 등록, 7개 기능 단위 분할 커밋 후 push
- **`README.md` 작성** — 실행 방법, 아키텍처, DB 스키마(설계 이유 포함), 이벤트 생성기 설계, 분석 쿼리 결과 요약, raw vs agg 비교, 핵심 결정, 구현하면서 고민한 점, 디렉토리 구조, 제약/한계

### 확정 결정 (DECISIONS.md 추가)
- **#27** psycopg2-binary 2.9.12로 상향 (Python 3.14 wheel 호환)
- **#28** event_id / session_id 형식: 순차 (UUID 비채택, 단일 머신 가독성 우선)
- **#29** VARCHAR 폭은 VARCHAR(20) 유지 (PostgreSQL VARCHAR은 max 제약일 뿐 디스크 영향 없음)
- **#30** Docker Compose app 서비스 구성: 일회성 배치(`restart: no`), `depends_on: service_healthy`, `DB_HOST=db` 네트워크 DNS

### 미완 / 이슈
- **Step 5 시각화 미착수** — 도구 미결정. 후보 (Streamlit / Metabase / Grafana) 별 트레이드오프 평가 필요
- backfill timestamp가 실행 일자에 의존 — README에 명시했으나 평가자가 절대값 비교 시 혼동 가능성

### 다음 세션 시작 시 바로 할 것
1. 시각화 도구 결정 (Streamlit 단순함 vs Metabase 운영성 vs Grafana 시계열 강점)
2. 도구별 docker-compose 통합 또는 별도 실행 방식 결정
3. Q1~Q3 차트 3종 구성

---

## 2026-04-26 (세션 4)

### 세션 범위
Step 4 마무리 (Dockerfile + app 서비스), `queries.sql` 작성, GitHub 리포 생성·분할 커밋 push, README 작성. 이번 세션으로 시각화(Step 5)를 제외한 모든 항목 완료.

### 수행
- **`requirements.txt` 작성** — `psycopg2-binary==2.9.12`, `tzdata==2026.2`. 처음 핀 고정한 2.9.10이 Python 3.14 wheel을 제공하지 않아 2.9.12로 상향 (#27)
- **venv에 의존성 설치 + import 검증** — `psycopg2.extras.execute_values`, `zoneinfo("Asia/Seoul")` 둘 다 동작 확인
- **`event_generator.py` DB 연결 검증** — `docker compose up -d db` → `python event_generator.py` 실행. 첫 시도 시 `event_id` UUID(36자)가 `VARCHAR(20)`을 초과해 실패 → ID 형식 결정 (#28)
- **ID 형식: 순차 채택** (#28) — UUID 대신 `evt_NNNNN` (5자리), `sess_NNNNN` (5자리). 로그 가독성 우선, 단일 머신이라 분산 충돌 무관
  - VARCHAR(20) 그대로 유지 (타이트닝은 디스크 영향 없고 작업 비용 큼, #29)
  - 통계 검증: view 48,620 (97.24%) / cart 851 (1.70%) / purchase 529 (1.06%) / errors 328 (0.66%) / 29,788 sessions
- **`init.sql`에 `agg_event_summary` 추가** — `(bucket_hour, user_id, event_type)` PK wide fact, `error_count <= event_count` CHECK
  - 라이브 DB에도 동일 DDL 직접 적용 (재기동 없이 동기화)
- **`event_generator.py`에 `aggregate_to_summary` ETL 추가** — `TRUNCATE agg_event_summary` 후 `INSERT INTO ... SELECT ... GROUP BY date_trunc('hour', timestamp), user_id, event_type`. 백필 1회 모드라 idempotent 보장
  - 검증: agg_rows=32,084 / total_events=50,000 / total_errors=328 → raw와 정확히 일치
- **`queries.sql` 작성** — 3개 분석을 raw/agg 양 버전으로 작성, EXPLAIN ANALYZE 결과 주석 첨부
  - Q1 시간대 추이 / Q2 이벤트 비율(타입+에러) / Q3 전환율
  - 측정: Q1 raw 9.84ms vs agg 4.99ms (~2x), Q2 5.95 vs 5.26ms, Q3 4.47 vs 2.74ms (~1.6x). buffers는 일관 ~54% 감소
- **`Dockerfile` 작성** — `python:3.14-slim` 베이스, 의존성 레이어 캐싱, `TZ=Asia/Seoul` 환경변수
- **`docker-compose.yml`에 app 서비스 추가** — `build: .`, `depends_on: db service_healthy`, `restart: no`, `DB_HOST=db`
- **전체 자동 기동 검증** — `down -v` 후 `up --build --abort-on-container-exit --exit-code-from app` 한 번으로 db 기동 → app 빌드·실행 → 50K events + 32K agg INSERT → app exit 0 → db 정상 종료까지 깔끔하게 흘러감
- **GitHub 리포 생성** — `https://github.com/ssb3204/-_-_-` 등록, 7개 기능 단위 분할 커밋 후 push
- **`README.md` 작성** — 실행 방법, 아키텍처, DB 스키마(설계 이유 포함), 이벤트 생성기 설계, 분석 쿼리 결과 요약, raw vs agg 비교, 핵심 결정, 구현하면서 고민한 점, 디렉토리 구조, 제약/한계

### 확정 결정 (DECISIONS.md 추가)
- **#27** psycopg2-binary 2.9.12로 상향 (Python 3.14 wheel 호환)
- **#28** event_id / session_id 형식: 순차 (UUID 비채택, 단일 머신 가독성 우선)
- **#29** VARCHAR 폭은 VARCHAR(20) 유지 (PostgreSQL VARCHAR은 max 제약일 뿐 디스크 영향 없음)
- **#30** Docker Compose app 서비스 구성: 일회성 배치(`restart: no`), `depends_on: service_healthy`, `DB_HOST=db` 네트워크 DNS

### 미완 / 이슈
- **Step 5 시각화 미착수** — 도구 미결정. 후보 (Streamlit / Metabase / Grafana) 별 트레이드오프 평가 필요
- backfill timestamp가 실행 일자에 의존 — README에 명시했으나 평가자가 절대값 비교 시 혼동 가능성

### 다음 세션 시작 시 바로 할 것
1. 시각화 도구 결정 (Streamlit 단순함 vs Metabase 운영성 vs Grafana 시계열 강점)
2. 도구별 docker-compose 통합 또는 별도 실행 방식 결정
3. Q1~Q3 차트 3종 구성

---

## 2026-04-25 (세션 3)

### 세션 범위
Kaggle 가중치 재추출, 이벤트 생성기 설계 전면 재검토(state machine 전환), 파라미터 갱신, `event_generator.py` 본체 작성, 집계 테이블 도입 결정.

### 수행
- **venv 생성**: 프로젝트 루트에 `.venv`. pandas 3.0.2 / pyarrow 24.0.0 / tzdata 2026.2 설치
- **`scripts/extract_weights.py` 작성 및 실행** — 2019-Oct.csv 4,244만건에서 10% 샘플(4,244,876건) chunked 추출, random_state=3, UTC→KST 변환, event_type별 정규화
  - 결과: VIEW(408만) / CART(9.2만) / PURCHASE(7.4만) 3개 dict 확보
  - 시간대당 cart/purchase 표본 ~3,000+건 → 안정적 분포
  - 출력: stdout으로 dict 3개 출력 후 event_generator.py에 직접 박음 (별도 파일 분리 안 함)
- **이벤트 생성기 설계 전면 재검토 → state machine 모델로 전환**
  - 세션 단위 퍼널 → 이벤트 1개씩 생성, hour 먼저 샘플 → action 점수 비교 방식
  - (user, lecture) 페어별 상태 추적 (view_count / cart / purchase)
  - view→cart 강의 선택은 누적 조회수 벨커브 가중 (1~2 낮음, 3~5 피크, 6+ 하락)
  - Zipf(s=1) 유저 가중치 도입 → 상위 20% 유저가 ~80% 이벤트 점유
  - session_id는 같은 유저 30분 윈도우 묶음 (업계 표준)
- **파라미터 갱신**
  - `EVENT_COUNT`: 10,000 → **50,000**
  - `BACKFILL_DAYS`: 신설, **60일** (KST naive timestamp [today-60d, today)에 분산)
  - `HOUR_NOISE_PCT`: ±15% → **±20%**, 시작 시 1회 적용 후 합 100으로 정규화
  - `USER_COUNT`, `LECTURE_COUNT`: 변경 없음 (200, 20)
  - 에러율: 변경 없음 (0.5/3/8%)
- **실행 모드 확정**: 백필 1회 (스트리밍/Airflow/GitHub Actions/cron 모두 비채택)
- **분석 쿼리 4개 → 3개**: 시간대별 이벤트 추이 / 이벤트 비율(타입별 + 에러) / 조회 대비 구매 전환율
- **집계 테이블 도입**: 단일 wide fact 테이블 `agg_event_summary`
  - grain: `(bucket_hour, user_id, event_type)`, metrics: `(event_count, error_count)`
  - 분석은 모두 이 테이블에서 GROUP BY 조합으로 수행
- **성능 비교 방식 확정**: raw events 직접 쿼리 vs `agg_event_summary` 쿼리 EXPLAIN ANALYZE 비교 (X+Y 둘 다 만드는 방법 1은 50K에서 차이 미미 사유로 비채택)
- **`event_generator.py` 작성 완료** (~370 줄)
  - DB 연결 검증은 다음 세션으로 미룸 (psycopg2 미설치 + DB 미기동 상태)

### 확정 결정
DECISIONS.md #15~#26 신규/갱신. 요약:
- #15 Kaggle 가중치 재추출 (4,244,876건, event_type별 3개 dict)
- #16 추출값 그대로 사용 (러시아 패턴 + KST 변환), README 명시
- #17 가중치는 event_generator.py에 직접 상수로 박음
- #18 생성 방식 전환: 세션 퍼널 → state machine (#6 갱신)
- #19 상태 추적 단위: (user, lecture) 페어
- #20 유저 선택: Zipf(s=1) 가중
- #21 파라미터 갱신: 50K, 60일, ±20%
- #22 실행 모드: 백필 1회
- #23 session_id: 30분 윈도우
- #24 분석 쿼리 4개→3개 (#13 갱신)
- #25 집계 테이블 `agg_event_summary` 도입
- #26 성능 비교: raw vs agg EXPLAIN ANALYZE

### 미완 / 이슈
- **DB 연결 검증 미완**: venv에 psycopg2-binary 미설치, DB 컨테이너 미기동, event_generator.py 실행 안 함
- **`requirements.txt` 미작성**
- **`init.sql`에 `agg_event_summary` 테이블 미추가**
- **event_generator.py에 ETL 함수(events → agg) 미추가**
- **`queries.sql` 미작성**
- **docker-compose.yml에 app 서비스 미추가**

### 다음 세션 시작 시 바로 할 것
1. `requirements.txt` 작성 + venv에 psycopg2-binary 설치
2. DB 컨테이너 기동 후 `python event_generator.py` 실행해 raw events INSERT 검증 (50K, 통계 출력 확인)
3. `init.sql`에 `agg_event_summary` 테이블 추가
4. event_generator.py에 ETL 함수 추가 (events INSERT 후 agg INSERT 호출)
5. `queries.sql` 작성: 3개 분석 쿼리, 각 쿼리에 raw vs agg EXPLAIN ANALYZE 결과 주석 첨부
6. (선택) 시각화 도구 결정 후 Step 5 진행

---

## 2026-04-24 (세션 2)

### 세션 범위
문서화 정리. 구현 변경 없음.

### 수행
- 프로젝트 `CLAUDE.md` 최상단에 Python 규칙 2개 `@` import 추가
  - `@~/.claude/rules/python/coding-style.md`
  - `@~/.claude/rules/python/testing.md`
  - 이유: common 규칙은 글로벌 주입으로 이미 활성. Python 전용만 명시적 import로 선언
- `docs/DECISIONS.md` 신규 생성 — 1~14번 의사결정 기록 (Context / Decision / Alternatives / Tradeoffs 형식)
- `docs/PROGRESS.md` 신규 생성 — 본 문서

### 확정 결정
DECISIONS.md 참조. 요약:
- #14 프로젝트 규칙 import 방식

### 미완 / 이슈
- **Kaggle 시간 가중치 재추출 대기**: event_type별(view / cart / purchase) 시간대 가중치 3개를 Kaggle 30만건 샘플에서 따로 추출해야 함. 재추출 전까지는 전체 HOUR_WEIGHTS 하나를 3개에 동일 적용하는 임시 대체값 사용 가능
- **의사결정은 내렸지만 구현 미착수**: `event_generator.py` 본체

### 다음 세션 시작 시 바로 할 것
1. Kaggle 데이터에서 view/cart/purchase별 시간 가중치 재추출 (임시 대체로 진행해도 되는지 사용자 확인)
2. `event_generator.py` 구현 시작 (바텀 업: DB 연결 → 유저 생성 → 세션 생성 → 이벤트 생성 순)

---

## 2026-04-24 (세션 1)

### 세션 범위
DB 스키마 구현 + Docker Compose 초기화 + 이벤트 생성기 설계 확정.

### 수행
- `init.sql` 작성 — users / events 테이블, CHECK 제약 (device_type, event_type), FK 제약, 인덱스 2개 (`idx_events_timestamp`, `idx_events_user_id`)
- `docker-compose.yml` (DB 서비스만) 작성 — PostgreSQL 단독, 기동 명령 `docker compose -p eventlog up -d`
- 한글 디렉토리명 대응: `-p eventlog` 플래그 필수임을 확인
- 접속 정보 확정: DB `eventlog`, user `app`, pass `app`, port 5432
- 이벤트 생성기 Q1~Q4 의사결정 완료 — DECISIONS.md #6~#9 참조

### 확정 결정
DECISIONS.md 참조. 요약:
- #1 언어: Python
- #2 DB: PostgreSQL
- #3 컨테이너: Docker Compose
- #4 스키마: 비정규화
- #5 error: BOOLEAN 컬럼
- #6 생성 방식: 세션 단위 퍼널 시뮬레이션 (Q1 = B안)
- #7 전환 확률: 누적 조회 수 벨 커브 (Q2 = C안)
- #8 외부 파라미터: USER_COUNT, EVENT_COUNT 2개만 (Q3 = A안+X안)
- #9 시간 가중치: 세션 타입별 3개 분리 (Q4 = B안)
- #10 노이즈: ±15% + 유저별 개인차
- #11 에러율: view 0.5% / cart 3% / purchase 8%
- #12 시드 데이터: Kaggle 30만건 샘플
- #13 분석 쿼리: 4개 (최소 요구 2개 초과)

### 검증
- DB 기동 후 `\dt` / `\d users` / `\d events` 로 테이블·제약 확인
- 더미 INSERT 시도로 CHECK / FK 동작 확인
