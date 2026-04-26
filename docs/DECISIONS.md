# 설계 의사결정 기록 (DECISIONS)

본 문서는 이벤트 로그 파이프라인 과제 진행 중 내린 기술/설계 의사결정을 근거와 대안과 함께 기록한다. 새로운 결정이 추가될 때 아래에 append 한다.

각 항목은 다음 형식을 따른다.
- **Context**: 왜 이 결정이 필요했는가
- **Decision**: 무엇을 선택했는가
- **Alternatives**: 검토한 다른 선택지
- **Tradeoffs**: 이 결정으로 얻는 것과 잃는 것

---

## 1. 구현 언어

- **Context**: 과제 전체를 구현할 주 언어 선택 필요
- **Decision**: Python
- **Alternatives**: Node.js, Go
- **Tradeoffs**:
  - 얻음: 익숙한 언어, 데이터 처리용 라이브러리 생태계 풍부, 인프라/데이터 엔지니어링 인턴 포지션에서 요구되는 스크립팅 능력 부합
  - 잃음: 타입 안정성은 Go 대비 약함 (type annotation + ruff로 보완)

---

## 2. 데이터베이스 엔진

- **Context**: 이벤트 로그 append-heavy 워크로드 + Docker 환경에서 동작 + 단독 분석 쿼리 수행 가능해야 함
- **Decision**: PostgreSQL
- **Alternatives**: SQLite
- **Tradeoffs**:
  - 얻음:
    - 동시 쓰기에 강함 (이벤트 생성기가 bulk insert 할 때 락 경합 적음)
    - Docker Compose 멀티 서비스 구성과 궁합이 좋음 (별도 컨테이너)
    - 분석용 SQL 문법(윈도우 함수 등)을 제약 없이 사용 가능
  - 잃음:
    - SQLite 대비 초기 기동 시간 증가
    - 별도 컨테이너라 리소스 사용량 약간 증가

---

## 3. 컨테이너 오케스트레이션

- **Context**: 과제 요구사항 — `docker compose up` 한 번으로 전체 파이프라인이 기동되어야 함
- **Decision**: Docker Compose (v2)
- **Alternatives**: 수동 실행 스크립트, 단일 Dockerfile
- **Tradeoffs**:
  - 얻음: 재현 가능성, 서비스 간 의존성(depends_on / healthcheck) 명시 가능
  - 잃음: 프로젝트 루트 디렉토리명이 한글이라 기본 project name이 깨져 `-p eventlog` 플래그를 수동 지정해야 함 (README에 명시 필요)

---

## 4. DB 스키마 정규화 수준

- **Context**: users / events 관계에서 정규화 vs 비정규화 선택
- **Decision**: 비정규화 (events 테이블이 user_id만 FK로 유지, device_type 같은 유저 속성은 users 테이블에만)
- **Alternatives**: 3NF 정규화 (sessions 테이블 분리, lectures 테이블 분리)
- **Tradeoffs**:
  - 얻음:
    - 이벤트 로그는 append-only → 쓰기 경합 없음
    - 분석 쿼리에서 JOIN 부담 최소화
    - BigQuery / Redshift 같은 분석 DB의 철학과 일치
  - 잃음:
    - 강의 이름이 바뀌면 일괄 갱신 필요 (본 과제에서는 lecture_id만 저장해서 이 문제 회피)
    - sessions 메타데이터(세션 시작 시간 등)를 별도로 관리하고 싶으면 추가 설계 필요
- **Note**: 프로덕션 환경이라면 sessions 테이블 분리 고려 가능. README에도 동일 문구 명시 예정.

---

## 5. error 처리 방식

- **Context**: view / cart / purchase 각 단계에서 에러 발생 가능. 에러를 어떻게 표현할 것인가
- **Decision**: `events.error_check` BOOLEAN 컬럼 (event_type과 직교)
- **Alternatives**: `event_type = 'error'` 별도 타입
- **Tradeoffs**:
  - 얻음:
    - 어느 단계에서 에러가 발생했는지 (event_type + error_check) 조합으로 바로 판별 가능
    - 예: `event_type='purchase' AND error_check=TRUE` → 결제 단계 실패
  - 잃음:
    - error 자체가 별도 이벤트 타입인 모델 대비 카운팅이 조금 더 번거로움 (WHERE 절 추가 필요)

---

## 6. 이벤트 생성기 — 생성 방식 (Q1)

- **Context**: 10,000건을 어떻게 생성할 것인가
- **Decision**: 세션 단위 퍼널 시뮬레이션
  - 세션 타입 결정 (view-only / cart-reaching / purchase-reaching)
  - 세션 시작 시간 샘플링
  - 세션 내에서 view → cart → purchase 순서로 이벤트 발생
- **Alternatives**:
  - A안: 독립 랜덤 (각 이벤트를 독립적으로 샘플링)
  - B안: 세션 단위 퍼널 시뮬레이션 (선택)
- **Tradeoffs**:
  - 얻음: session_id가 실제 식별자로 의미를 가짐, 퍼널 분석 쿼리가 실제 동작함 (view 없이 purchase 불가능이 강제됨)
  - 잃음: 구현 복잡도 증가, 상태 관리(세션 내 view한 강의 추적) 필요

---

## 7. 이벤트 생성기 — 전환 확률 모델 (Q2)

- **Context**: 유저가 강의를 몇 번 보면 사는가
- **Decision**: 누적 조회 수 기반 벨 커브 (3~5회 피크)
- **Alternatives**:
  - A안: 고정 확률 (모든 view에 동일한 구매 확률)
  - B안: 단조 증가 확률 (볼수록 살 확률 상승)
  - C안: 벨 커브 (선택)
- **Tradeoffs**:
  - 얻음: "여러 번 보고 고민만 하다 안 사는 유저" 패턴을 자연스럽게 모델링. 분석 쿼리 "유저별 조회→구매 전환 횟수"가 의미 있는 분포를 보임
  - 잃음: `user_lecture_view_count[(user_id, lecture_id)]` 상태 관리 필요, 파라미터 튜닝 부담

---

## 8. 이벤트 생성기 — 외부 파라미터 (Q3)

- **Context**: 코드 상단에 몇 개의 튜닝 상수를 노출할 것인가
- **Decision**: `USER_COUNT`, `EVENT_COUNT` 2개만 노출. 나머지(세션 타입 비율, 전환율 곡선 모양, 시간 간격 등)는 내부 상수로 은닉
- **Alternatives**:
  - 모든 파라미터를 최상단에 노출 → 튜닝은 쉽지만 "뭘 건드려야 할지" 혼란
  - CLI 인자로 노출 → 과제 범위 초과
- **Tradeoffs**:
  - 얻음: 수정 포인트 명확. 과제 채점자 입장에서 "얼마나 생성할지"만 눈에 띔
  - 잃음: 내부 상수 수정하려면 코드 읽어야 함 (의도된 트레이드오프)

---

## 9. 이벤트 생성기 — 시간 가중치 (Q4)

- **Context**: 이벤트 발생 시각에 하루 중 어떤 시간대가 더 밀집하도록 할 것인가
- **Decision**: 세션 타입별로 시간 가중치 3개 분리 (`VIEW_HOUR_WEIGHTS`, `CART_HOUR_WEIGHTS`, `PURCHASE_HOUR_WEIGHTS`). 적용은 세션 **시작 시간**에만 하고, 세션 내 개별 이벤트는 시작 시간 + 짧은 랜덤 간격
- **Alternatives**:
  - A안: 전체 이벤트 평균 가중치 하나로 통일
  - B안: 세션 타입별 3개 분리 (선택)
- **Tradeoffs**:
  - 얻음: "구매는 저녁에, 탐색은 오후에" 같은 실제 행동 패턴 반영. 시간대별 분석 쿼리에서 타입별로 다른 분포가 보임
  - 잃음: Kaggle 데이터에서 event_type별로 필터링하여 가중치를 **재추출**해야 함 (아직 미수행). 재추출 전까지는 HOUR_WEIGHTS 하나를 3개에 동일 적용하는 임시 대체값 사용

---

## 10. 노이즈 정책

- **Context**: 결정론적 분포만 쓰면 데이터가 부자연스러움
- **Decision**:
  - 시간대 가중치에 ±15% 노이즈 (날마다 트래픽이 조금씩 다름)
  - 유저별 개인차 노이즈 (세션당 view 수, 전환 확률에 유저 단위 랜덤)
- **Alternatives**: 노이즈 없이 결정론적
- **Tradeoffs**:
  - 얻음: 현실에 가까운 데이터, 분석 쿼리 결과도 더 자연스러움
  - 잃음: 재현성은 random_seed 고정으로 확보 가능하지만 테스트 시 정확한 값 기대는 어려움

---

## 11. 에러율 수치

- **Context**: view / cart / purchase 각 단계의 에러 발생률
- **Decision**: view 0.5%, cart 3%, purchase 8%
- **Alternatives**: 균등 (전부 같은 비율), 극단 (purchase만 높고 나머지 0)
- **Tradeoffs**:
  - 얻음: 글로벌 이커머스 벤치마크(purchase 8~15%)에 준거. 분석 스토리("결제 단계 에러가 가장 많다")가 자연스럽게 재현됨
  - 잃음: 수치는 어디까지나 가정. 실 서비스 튜닝 시 변경 필요 (README에 벤치마크 출처 명시 예정)

---

## 12. 시드 데이터 출처

- **Context**: 시간 가중치를 뽑아낼 참고 데이터 필요
- **Decision**: Kaggle `eCommerce behavior data from multi category store` (mkechinov) — 4,244만건 중 30만건 랜덤 샘플 (random_state=3). UTC → Asia/Seoul (UTC+9) 변환
- **Alternatives**: 완전 합성 (임의 분포로 직접 가중치 정의)
- **Tradeoffs**:
  - 얻음: 가중치에 "근거"가 생김. README에서 설명 가능
  - 잃음: 러시아 이커머스 데이터 → 한국 서비스로 매핑할 때 UTC+9 단순 변환. 문화적 패턴(점심시간, 출퇴근 시간대 등)의 정확한 이식은 아님

---

## 13. 분석 쿼리 개수

- **Context**: 과제 최소 요구 2개. 몇 개를 작성할 것인가
- **Decision**: 4개 (시간대별 이벤트 추이 / 에러 비율 + 단계 / 유저별 조회→구매 전환 횟수 / 전체 전환율)
- **Alternatives**: 2개 (최소 요구만)
- **Tradeoffs**:
  - 얻음: 분석 스토리가 자체 완결 (유저 단위 + 전체 단위 + 안정성 모니터링 + 트래픽 패턴)
  - 잃음: 작성·검증 부담 증가. 단 본 과제에서는 퍼널 기반 생성기의 동작 검증 역할도 겸해서 가치가 더 큼

---

## 14. 프로젝트 규칙 import 방식 (2026-04-24)

- **Context**: `~/.claude/rules/` 아래 글로벌 규칙들을 프로젝트에 어떻게 적용할지
- **Decision**: 프로젝트 `CLAUDE.md` 최상단에 Python 전용 규칙 2개만 `@` import
  - `@~/.claude/rules/python/coding-style.md`
  - `@~/.claude/rules/python/testing.md`
- **Alternatives**:
  - common 규칙까지 모두 명시적 import
  - import 없이 글로벌 주입에만 의존
- **Tradeoffs**:
  - 얻음: common 규칙은 이미 글로벌로 주입됨 → 중복 방지. Python 전용은 명시적으로 선언되어 프로젝트가 Python 기반임이 파일에서도 드러남
  - 잃음: 없음

---

## 15. Kaggle 가중치 재추출 (2026-04-25)

- **Context**: #9에서 세션 타입별 시간 가중치 3개 분리 결정했으나 Kaggle 데이터에서 event_type별로 따로 추출한 적 없음. 30만 샘플 그대로 분리하면 cart/purchase 표본이 ~6천건으로 노이즈 큼
- **Decision**: 2019-Oct.csv 4,244만건에서 10% 청크 샘플(4,244,876건) 추출, random_state=3, UTC→KST 변환, event_type별 정규화 → VIEW(408만) / CART(9.2만) / PURCHASE(7.4만) 3개 dict 확보
- **Alternatives**: 30만 샘플 그대로 분리(노이즈 큼), 4,244만 전수(메모리 부담)
- **Tradeoffs**:
  - 얻음: 시간대당 cart/purchase 표본 ~3,000+건 → 안정적 분포, 세 분포 모양이 명확히 다름 (view U자형, cart/purchase 저녁 단봉)
  - 잃음: 100만 vs 424만 처리 시간 차이는 작음 (둘 다 1분 내). 4,244만 전수 처리는 미수행

---

## 16. 시간 가중치 적용 방식 (2026-04-25, #9 갱신)

- **Context**: 추출 결과 view 분포에서 0~3시 새벽 트래픽이 한국 서비스치고 높음 (러시아 데이터 KST 변환 영향)
- **Decision**: 추출값 그대로 사용 (옵션 A). README에 "데이터셋 출처(러시아) 영향으로 새벽 view 비율이 다소 높음. 시간 시프트 없이 원자료 보존" 명시
- **Alternatives**:
  - B. 시간 시프트 (한국 일과에 맞게 임의 오프셋)
  - C. 핸드 디자인 (한국 패턴 가정값으로 대체)
- **Tradeoffs**:
  - 얻음: 데이터 근거 명확함 (Kaggle 추출값 그대로 = 거짓말 안 함)
  - 잃음: "한국 서비스 시뮬레이션"치고 새벽 트래픽 부자연스러움. 평가자가 짚을 가능성

---

## 17. 가중치 저장 위치

- **Context**: VIEW/CART/PURCHASE_HOUR_WEIGHTS 3개 dict를 어디에 둘지
- **Decision**: `event_generator.py` 안에 직접 상수로 박음
- **Alternatives**: `weights.py` 별도 파일 → import, CLAUDE.md에만 기록 후 추후 옮김
- **Tradeoffs**:
  - 얻음: 단일 파일 자족, 평가자가 한 파일만 봐도 모든 게 보임. 일회성 과제에 적합
  - 잃음: 가중치 갱신 시 코드 파일 수정 필요 (재추출 자주 안 함)

---

## 18. 이벤트 생성 방식 전환: state machine (2026-04-25, #6 갱신)

- **Context**: 세션 단위 퍼널(#6)은 부키팅 효과(같은 세션 이벤트가 같은 시간 버킷에 떨어지는 부수 효과)와 session_id 의미 구성의 인위성 우려
- **Decision**: state machine 기반 모델로 전환
  - hour 먼저 샘플 (VIEW_HOUR_WEIGHTS 기준, ±20% 노이즈 적용본)
  - 가능 action 점수 = `ACTION_RATIO[a] × HOUR_WEIGHTS[a][hour]`
  - 점수 정규화 후 action 결정
  - action에 맞는 lecture 선택 (cart는 누적 조회수 벨커브 가중)
  - 상태가 안 맞으면 view로 폴백 (순서 보장: view→cart→purchase)
- **Alternatives**: 세션 퍼널 유지(#6), 독립 랜덤
- **Tradeoffs**:
  - 얻음: 부키팅 효과 제거 (각 이벤트가 자기 타입 가중치 따름), 구현 단순, 순서 강제력 자연스러움
  - 잃음: 세션 개념 상실 → session_id를 30분 윈도우 사후 그룹핑으로 인위 부여(#23)

---

## 19. 상태 추적 단위

- **Context**: state machine 모델에서 state를 유저 단위로 vs (유저, 강의) 페어 단위로 추적할지
- **Decision**: (user, lecture) 페어 단위. 한 유저가 lecture_A는 viewed 상태고 lecture_B는 carted 상태로 별개 관리
- **Alternatives**: 유저 단위 (한 유저가 어떤 강의든 봤으면 view 상태 1)
- **Tradeoffs**:
  - 얻음: "다른 강의 본 적 있어서 처음 본 강의도 바로 차트" 같은 비현실 상황 방지. 누적 조회수 벨커브가 강의별로 의미 있게 동작
  - 잃음: 메모리 사용량 증가 (200 유저 × 20 강의 = 최대 4,000 셀), 본 스코프엔 영향 없음

---

## 20. 유저 선택 분포: Zipf 가중

- **Context**: 매 이벤트마다 유저 선택 방식
- **Decision**: Zipf(s=1.0) 가중. 상위 유저가 더 자주 선택됨 → 상위 20% 유저가 ~80% 이벤트 점유
- **Alternatives**: 균등 랜덤(편차 작음, 비현실), 유저 타입 분류(heavy/medium/light, 구현 복잡)
- **Tradeoffs**:
  - 얻음: 80/20 법칙 반영. 분석 쿼리 "유저별 조회→구매 전환"에서 헤비 유저 vs 라이트 유저 패턴 비교 가능
  - 잃음: random_state 고정으로 재현성 확보하나, 상위 유저 ID(user_0001~)가 결정론적으로 헤비가 됨 (실제로는 무방)

---

## 21. 파라미터 갱신 (2026-04-25, #8 보강)

- **Context**: 분석 시그널 강화 + 시간 분포 풍부함을 위해 데이터 양 증가 결정
- **Decision**:
  - `EVENT_COUNT`: 10,000 → **50,000**
  - `BACKFILL_DAYS`: 신설, **60일** (KST naive timestamp [today-60d, today)에 분산)
  - `HOUR_NOISE_PCT`: ±15% → **±20%**, 시작 시 1회 적용 후 합 100으로 정규화
  - `USER_COUNT`, `LECTURE_COUNT`: 변경 없음 (200, 20)
- **Alternatives**: 20K/30일 (직관적이지만 일평균 적음), 100K+/90일+ (오버엔지니어링)
- **Tradeoffs**:
  - 얻음: 일평균 ~833건 / 시간당 ~35건 / 유저당 ~250건 → 벨커브 충분히 드러나고 시간대별 노이즈 미미
  - 잃음: INSERT 시간 약간 증가 (그래도 5초 이내)

---

## 22. 실행 모드: 백필 1회

- **Context**: 백필(과거 timestamp 일괄 INSERT) vs 스트리밍(NOW() 지속 INSERT) vs 하이브리드 / 스케줄링 도구(Airflow / GitHub Actions / cron) 선택
- **Decision**: 백필 1회 모드. 스케줄링 도구 일절 사용 안 함. `docker compose up` → DB 기동 → event_generator.py 실행 → 50K INSERT → 종료
- **Alternatives**:
  - 스트리밍 단독 (분석/시각화 즉시 못 봄)
  - 하이브리드 (백필 + 무한 루프 스트리밍)
  - Airflow 컨테이너 (오버엔지니어링, compose 복잡도 5배)
  - GitHub Actions (로컬 평가 환경에서 작동 안 함)
- **Tradeoffs**:
  - 얻음: 과제 원문 "docker compose up 한 번으로 실행"에 정확히 부합. 평가자가 1분 안에 분석/시각화 결과 확인 가능. 인턴 과제 스코프에 맞음
  - 잃음: 운영 시뮬레이션 측면(실시간 수집)은 보여주지 않음. README에 "프로덕션이라면 Kafka/Pub-Sub + Airflow DAG 같은 패턴" 한 줄 명시 예정

---

## 23. session_id 정의: 30분 활동 윈도우

- **Context**: state machine 전환으로 세션 개념 사라짐. 그러나 events 스키마는 session_id NOT NULL 요구
- **Decision**: 같은 유저의 직전 이벤트로부터 30분 이내면 동일 session_id, 초과 시 새 UUID. 사후 그룹핑 방식
- **Alternatives**: 매 이벤트마다 새 UUID(의미 없음), 같은 유저+같은 날짜=동일 session_id(너무 거침)
- **Tradeoffs**:
  - 얻음: Google Analytics / Adobe Analytics 업계 표준 정의. 평가자가 묻기 좋고 답변 깔끔. "세션당 평균 이벤트 수" 같은 보너스 분석 가능
  - 잃음: 세션이 사용자 의도가 아닌 시간 휴리스틱으로 결정됨 (실 서비스에서도 동일하게 휴리스틱 사용)

---

## 24. 분석 쿼리 갯수·범위 (2026-04-25, #13 갱신)

- **Context**: 사용자가 분석 쿼리 범위 재검토
- **Decision**: 4개 → **3개**로 축소
  - 시간대별 이벤트 추이
  - 이벤트 비율 (이벤트 타입별 발생 비율 + 에러 이벤트 비율)
  - 조회 대비 구매 전환율
- **Alternatives**: 4개 유지 (#13 원안), 2개로 더 축소 (최소 요구만)
- **Tradeoffs**:
  - 얻음: 분석 의도 명확, 시각화 대시보드 차트 3개로 깔끔하게 매핑. 두 번째 쿼리가 타입 비율 + 에러 비율을 한 차트에 표현 가능
  - 잃음: 유저별 단위 분석(원안 #3)이 빠짐. 다만 집계 테이블에 user_id가 grain으로 들어가서 추후 SQL 한 번이면 추가 가능

---

## 25. 집계 테이블 도입: 단일 wide fact

- **Context**: 분석 쿼리를 raw events에서 직접 vs 별도 집계 테이블에서 수행
- **Decision**: 단일 wide fact 테이블 `agg_event_summary` 도입. 분석은 모두 이 테이블에서 GROUP BY 조합으로 수행
  - grain: `(bucket_hour, user_id, event_type)` (PK)
  - metrics: `(event_count, error_count)`
- **Alternatives**:
  - X. 분석별 특화 테이블 3개 (단순하지만 새 분석 추가마다 테이블 폭증)
  - C. MATERIALIZED VIEW (기능 동일, 명시적 ETL 단계 약함)
  - 집계 없이 raw 직접 쿼리 (50K에선 가능하나 시그널 약함)
- **Tradeoffs**:
  - 얻음: fact table 패턴 (데이터 엔지니어링 표준). 새 분석 추가 시 SQL만 추가하면 됨. 시각화 도구가 한 테이블만 보면 됨. README 스토리 깔끔
  - 잃음: 분석 시 GROUP BY 작성 필요(SELECT * 대비 한 단계 복잡), 50K 스케일에선 성능 이득 미미

---

## 26. 성능 비교 방식: raw vs agg EXPLAIN ANALYZE

- **Context**: 집계 테이블 도입 효과를 어떻게 검증할지
- **Decision**: Y(`agg_event_summary`)만 만들고, 같은 분석 쿼리를 raw events 직접 vs Y에서 각각 `EXPLAIN ANALYZE` 실행해 쿼리 플랜 + 실행 시간 비교. queries.sql 주석에 결과 첨부
- **Alternatives**:
  - 방법 1: X(특화 테이블 3개) + Y 둘 다 만들고 timing 측정 (작업량 1.5배, 50K에선 차이 ms 단위 노이즈)
  - 방법 3: Y만 만들고 비교 없이 진행 (시그널 약함)
- **Tradeoffs**:
  - 얻음: 작업량 절반, "raw 풀스캔 vs fact 인덱스 스캔" 차이 또렷이 보임. PostgreSQL 내장 도구로 측정 (외부 의존 없음)
  - 잃음: X 패턴 코드는 보유하지 못함. 다만 README에 트레이드오프 설명 가능
