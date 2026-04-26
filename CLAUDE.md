# 이벤트 로그 파이프라인 과제 - Claude Code 컨텍스트


## 개발 진행 규칙 (필수 준수)

1. 감정적인 표현, 이모지 사용 금지
2. 작업은 바텀 업(bottom-up) 방식으로 진행
3. 한 단계를 완료할 때마다 사용자가 요구했던 원 프롬프트와 대조하여 누락된 항목이 없는지 체크
4. 누락이 없으면 정상 동작 여부 테스트 → 성공 시에만 다음 단계로 이동
5. 한 번에 큰 덩어리로 작업하지 말고 작은 단위로 쪼개서 단계별로 진행
6. 모든 설계/구현 의사결정은 사용자가 직접 내린다. Claude는 선택지와 트레이드오프만 제시한다.

---

## 작업 진행 상황 (2026-04-25 기준)

> 본 섹션은 **현재 스냅샷**. 시간순 누적 로그는 `docs/PROGRESS.md`, 결정 누적은 `docs/DECISIONS.md` 참조.

### 완료
- **Step 2 (DB 스키마, 부분)**: `init.sql` 작성 + 기동 테스트 완료
  - users / events 테이블, CHECK·FK 제약, 인덱스 2개 동작 확인
  - **미완**: `agg_event_summary` 집계 테이블 추가 필요 (#25)
- **Docker Compose (DB 서비스만)**: `docker-compose.yml`
  - 기동 명령: `docker compose -p eventlog up -d` (한글 디렉토리명 사유로 `-p` 필수)
  - 접속 정보: DB `eventlog`, user `app`, pass `app`, port 5432
- **Kaggle 가중치 재추출 (2026-04-25)**: `scripts/extract_weights.py` 작성·실행
  - 2019-Oct.csv 4,244만건 → 10% 청크 샘플(4,244,876건), random_state=3
  - VIEW(408만) / CART(9.2만) / PURCHASE(7.4만) 3개 dict 확보
  - event_generator.py에 직접 상수로 박음 (#17)
- **Python venv**: 프로젝트 루트 `.venv` (pandas 3.0.2, pyarrow, tzdata 설치됨)
- **`event_generator.py` 작성 완료 (~370 줄)**
  - 모델: state machine (이벤트 1개씩, hour 먼저 샘플 → action 점수 비교)
  - 파라미터: USER 200 / EVENT 50,000 / LECTURE 20 / BACKFILL 60일 / NOISE ±20%
  - Zipf(s=1) 유저 가중, (user, lecture) 페어 상태, 누적 조회수 벨커브 cart, 30분 윈도우 session_id
  - 백필 1회 모드 (스케줄러 X)
  - **미완**: psycopg2-binary 미설치 + DB 미기동 → 실제 INSERT 검증 안 됨

### 설계 결정 변경 (이번 세션 핵심)
- 생성 모델: 세션 퍼널(#6 원안) → **state machine** (#18로 갱신)
- 시간 가중치: 세션 시작 시간 적용(#9 원안) → **이벤트 단위 hour-first 샘플** + 가중치는 ±20% 노이즈 시작 시 1회 적용 (#21)
- 이벤트 수: 10K → **50K** (#21)
- 기간: 미명시 → **60일 백필** (#21, #22)
- 분석 쿼리: 4개 → **3개** (시간대별 추이 / 이벤트 비율(타입+에러) / 조회→구매 전환) (#24)
- 집계: 없음 → **단일 wide fact `agg_event_summary` 도입** (#25)
- 성능 비교: 없음 → **raw events vs `agg_event_summary` EXPLAIN ANALYZE 비교** (#26)

### 다음 단계 (다음 세션 시작 시 즉시)
1. `requirements.txt` 작성 + venv에 psycopg2-binary 설치
2. DB 컨테이너 기동 후 `python event_generator.py` 실행해 50K INSERT 검증
3. `init.sql`에 `agg_event_summary` 테이블 추가
4. event_generator.py 마지막에 ETL 함수 추가 (events → agg INSERT INTO ... SELECT)
5. `queries.sql` 작성: 3개 분석 쿼리, 각각 raw vs agg EXPLAIN ANALYZE 결과 주석 첨부

### 미착수
- Step 4: `docker-compose.yml`에 app 서비스 추가 (depends_on + healthcheck)
- Step 5: 시각화 (도구 미결정 — Streamlit / Metabase / Grafana 후보)
- README.md (DECISIONS.md 발췌 기반)

---

## 과제 개요

### 지원 포지션
인프라 / 데이터 엔지니어링 인턴

### 과제 배경 (원문)
> 웹 서비스에서는 유저의 행동(클릭, 구매, 에러 등)을 이벤트 로그로 기록하고, 이를 분석해 서비스를 개선합니다.
> 이 과제에서는 이벤트를 생성하고 → 저장하고 → 분석하고 → 시각화하는 작은 파이프라인을 직접 만들어 보세요.

### 구현 범위
라이브클래스(온라인 강의 플랫폼)의 웹 서비스 이벤트 로그 파이프라인 구축.
이벤트 생성 → 저장 → 분석 → 시각화의 전체 흐름을 구현한다.

### 평가 관점 (포지션 특성상 예상)
- 데이터 파이프라인 구성 능력 (생성 → 저장 → 분석 단계가 끊김 없이 동작하는지)
- DB 스키마 설계의 합리성 및 근거
- Docker/인프라 구성 (재현 가능성, 한 번에 기동되는지)
- 분석 쿼리의 목적성 및 실무적 유의미성

---

## 기술 스택 결정사항

| 항목 | 결정 | 결정 이유 |
|------|------|-----------|
| 언어 | Python | 익숙한 언어 |
| DB | PostgreSQL | 이벤트 로그 특성상 append-heavy 구조에 적합, 동시 쓰기에 강함, Docker 환경과 궁합이 좋음. SQLite는 동시 쓰기 취약 및 Docker 멀티 서비스 구성에 부적합 |
| 컨테이너 | Docker Compose | 과제 요구사항 (docker compose up 한 번으로 전체 스택 실행) |
| 시각화 | 미정 | 추후 결정 예정 |

---

## DB 설계

### 설계 원칙
- **비정규화** 선택
- 이유: 이벤트 로그는 append-only 특성상 분석 쿼리 성능이 중요하고 JOIN 비용이 부담됨
- README에 "정규화를 고려했으나 이벤트 로그 특성상 비정규화 선택. 프로덕션이라면 sessions 테이블 분리도 고려 가능"이라고 명시할 것
- 참고: 실무에서 BigQuery, Redshift 같은 분석용 DB는 아예 정규화를 지양함

### 테이블 구조

#### users 테이블
```sql
CREATE TABLE users (
    user_id     VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    created_at  TIMESTAMP NOT NULL,
    device_type VARCHAR NOT NULL  -- 'mobile' 또는 'desktop'
);
```

#### events 테이블
```sql
CREATE TABLE events (
    event_id     VARCHAR PRIMARY KEY,
    user_id      VARCHAR REFERENCES users(user_id),
    session_id   VARCHAR NOT NULL,
    event_type   VARCHAR NOT NULL,  -- 'view', 'cart', 'purchase'
    error_check  BOOLEAN NOT NULL DEFAULT FALSE,
    lecture_id   VARCHAR,           -- view/cart/purchase 모두 해당 강의 ID
    timestamp    TIMESTAMP NOT NULL
);
```

### error_check 설계 이유
- `error`를 별도 이벤트 타입으로 만들지 않고 **boolean 컬럼**으로 처리
- 이유: 어느 단계(event_type)에서 에러가 발생했는지 바로 알 수 있음
- 예: event_type='purchase' + error_check=TRUE → 구매 단계에서 에러 발생

---

## 이벤트 생성기 설계 (확정) — Q1~Q4 결정사항

### 이벤트 타입 (3가지)
| 타입 | 의미 | Kaggle 매핑 |
|------|------|-------------|
| `view` | 강의 조회 | view |
| `cart` | 찜하기 | cart |
| `purchase` | 실구매 완료 | purchase |

- 이벤트 타입 비율(원래 96/2/2)은 **결과값**이지 입력 파라미터가 아님
- 세션 퍼널 파라미터(전환율, 벨커브 등)에 의해 결과적으로 유사 비율이 나옴
- 완전히 96/2/2가 안 나와도 허용 (사용자 합의)

---

### Q1. 생성 방식: 세션 단위 퍼널 시뮬레이션 (B안)

```
유저 생성 (USER_COUNT명)
while 총 이벤트 수 < EVENT_COUNT:
    1. 세션 타입 결정 (view-only / cart-reaching / purchase-reaching)
    2. 세션 시작 시간 샘플링 (Q4에서 정한 세션타입별 시간 가중치 사용)
    3. 유저 선택
    4. 세션 내에서 강의들을 view
    5. view한 강의 중 일부를 cart (Q2 벨 커브)
    6. cart한 강의 중 일부를 purchase (Q2 벨 커브)
    7. 세션 내 이벤트들을 시간순으로 기록 (세션 시작 직후부터 수 분 이내)
```

- 독립 랜덤이 아니라 **세션 기반 퍼널** → session_id가 실제 식별자로 의미를 가짐
- view 없이 purchase 불가능 (순서 보장)

---

### Q2. 조회 수 기반 전환 확률: 벨 커브 (C안)

유저-강의 쌍으로 **누적 조회 수**를 세션 간에 걸쳐 추적하고, 해당 값에 따라 cart/purchase 전환 확률이 벨 커브를 그림.

| 누적 조회 수 | 구매 확률 경향 | 해석 |
|-------------|----------------|------|
| 1~2회 | 낮음 | 단순 관심 |
| 3~5회 | 피크 | 진지한 고려 |
| 6회+ | 하락 | 고민만 하고 안 사는 유형 |

- 구체 파라미터(피크 위치, 분포 모양)는 구현 시 결정
- **상태 관리 필요**: `user_lecture_view_count[(user_id, lecture_id)]` 같은 카운터 유지

---

### Q3. 외부 노출 파라미터: 상수 2개만 (A안 + X안)

```python
USER_COUNT = 200
EVENT_COUNT = 10000
```

- 위 2개만 코드 상단 상수로 노출 → 변경 시 이 값만 수정
- 세션 타입 비율, 세션당 view 분포, 전환율 벨커브, 시간 간격 등은 **내부 상수로 은닉**
- 이벤트 수가 `EVENT_COUNT`에 도달하면 세션 생성 루프 종료

---

### Q4. 시간 가중치: 세션 타입별 3개 분리 (B안)

```python
VIEW_HOUR_WEIGHTS     = {...}  # view-only 세션 시작 시간 분포
CART_HOUR_WEIGHTS     = {...}  # cart-reaching 세션 시작 시간 분포
PURCHASE_HOUR_WEIGHTS = {...}  # purchase-reaching 세션 시작 시간 분포
```

- **적용 대상**: 세션 **시작 시간**에만 적용 (세션 내 개별 이벤트는 시작 시간 + 짧은 랜덤 간격)
- **로직**: 세션 타입을 먼저 결정 → 그 타입의 시간 가중치에서 세션 시작 시간 샘플링
- **Kaggle 재추출 필요** (아직 확보 안 됨): event_type별로 필터링한 시간대 분포를 Kaggle 데이터에서 각각 추출
- 재추출 완료 전까지는 아래 전체 가중치로 3개 모두 임시 대체 가능 (평가 시그널은 약해짐)

---

### 노이즈 정책

- **시간대 가중치 노이즈**: 각 시간 가중치에 ±15% (날마다 트래픽이 조금씩 다름)
- **유저별 행동 패턴 노이즈**: 세션당 view 수, 전환 확률에 유저별 개인차 노이즈 (일부는 많이 보고 사고, 일부는 바로 삼)

---

### 에러율 (글로벌 이커머스 벤치마크)

| 단계 | 에러율 | 근거 |
|------|--------|------|
| view | 0.5% | 페이지 로딩 오류, 네트워크 불안정 |
| cart | 3% | 찜하기 기능 오류 |
| purchase | 8% | 결제 처리 실패 (8~15% 벤치마크) |

- 에러 **발생률**: purchase가 가장 높음
- 에러 **절대량**: view가 가장 많음 (view 이벤트 수가 압도적)

---

### Kaggle 데이터 출처

- 데이터셋: `eCommerce behavior data from multi category store` (mkechinov)
- 사용: 전체 4,244만건 중 30만건 랜덤 샘플 (random_state=3)
- UTC → Asia/Seoul (UTC+9) 변환
- 러시아 이커머스 데이터지만 한국 서비스 시뮬레이션이므로 UTC+9 적용

### 전체 시간 가중치 (참고용, 재추출 전 임시 대체값)
```python
HOUR_WEIGHTS = {
    0: 6.58, 1: 6.73, 2: 5.59, 3: 4.70, 4: 2.80,
    5: 1.73, 6: 1.31, 7: 0.54, 8: 0.67, 9: 0.57,
    10: 0.84, 11: 1.78, 12: 5.27, 13: 7.60, 14: 9.36,
    15: 8.07, 16: 9.93, 17: 8.71, 18: 10.00, 19: 9.41,
    20: 8.14, 21: 7.65, 22: 7.00, 23: 6.53
}
```
- 피크: 18시, 저점: 7~9시
- 이 값은 **전체 이벤트 평균**. 세션 타입별 가중치가 확보되면 교체.

---

## 분석 쿼리 (Step 3)

총 4개 쿼리 작성 (최소 요구사항 2개 초과)

1. **시간대별 이벤트 추이** (요구사항)
   - 시간대별 전체 이벤트 발생 수

2. **에러 이벤트 비율 + 발생 단계** (요구사항)
   - 전체 이벤트 중 에러 비율
   - 어느 단계(view/cart/purchase)에서 에러가 가장 많이 발생하는지

3. **유저별 조회 → 구매 전환 횟수**
   - 동일 유저가 몇 번 view 후 purchase에 이르는지

4. **전체 기준 전환율**
   - 전체 view 수 대비 purchase 수

---

## 분석 스토리
> "유저가 강의를 몇 번 조회한 후 구매로 이어지는지 전환 흐름을 파악하고,
> 동시에 어느 단계에서 에러가 주로 발생하는지 서비스 안정성을 모니터링한다"

- 유저별: 몇 번 view 후 purchase하는지
- 전체: view 대비 purchase 전환율
- 에러: view/cart/purchase 중 어느 단계에서 에러가 집중되는지
- 시간대: 언제 트래픽과 구매가 몰리는지

---

## 구현 요구사항

### Step 1: 이벤트 생성기
- 파일명: `event_generator.py`
- 위 가중치를 반영한 랜덤 이벤트 생성
- 유저 수: 200명 (users 테이블에 먼저 생성)
- 총 이벤트: 약 10,000건
- 강의 수: 약 20개 (lecture_id: lec_001 ~ lec_020)
- 실행 시 PostgreSQL에 자동 저장

### Step 2: 저장소
- PostgreSQL 사용
- 위 스키마 그대로 구현
- README에 스키마 및 선택 이유 포함

### Step 3: 분석 쿼리
- `queries.sql` 파일에 4개 쿼리 작성
- 각 쿼리에 주석으로 분석 목적 명시

### Step 4: Docker Compose
- `docker-compose.yml` 작성
- 서비스 구성: app(이벤트 생성기) + db(PostgreSQL)
- `docker compose up` 실행 시 자동으로 이벤트 생성 → 저장까지 동작
- DB 초기화 SQL은 `init.sql`로 분리

### Step 5: 시각화
- 추후 결정 예정

---

## 프로젝트 구조 (권장)
```
project/
├── CLAUDE.md
├── README.md
├── docker-compose.yml
├── init.sql                  # DB 스키마 초기화
├── event_generator.py        # 이벤트 생성기
├── queries.sql               # 분석 쿼리 4개
└── requirements.txt
```

---

## README 작성 가이드
Claude Code는 아래 내용을 README.md에 반드시 포함할 것

### README 필수 항목 (과제 제출 요구사항)
아래 3가지는 반드시 포함. 분량은 짧아도 됨.

1. **실행 방법**
   - 필요한 도구, 설치 명령어, 실행 명령어를 순서대로 작성

2. **스키마 설명**
   - 테이블을 이렇게 설계한 이유를 2~3줄로 설명

3. **구현하면서 고민한 점**
   - 어떤 결정을 했는지, 왜 그렇게 했는지 자유롭게 작성
   - 잘 모르는 부분이 있었다면 어떻게 해결했는지도 포함 가능

### 추가로 포함할 내용 (본 과제 맥락)

1. **이벤트 설계 이유** (Step 1 요구사항)
   - 라이브클래스 플랫폼 맥락에서 view/cart/purchase 선택 이유
   - Kaggle 데이터셋 기반 가중치 설계 설명

2. **저장소 선택 이유** (Step 2 요구사항)
   - PostgreSQL 선택 이유 (SQLite 대비)
   - 비정규화 선택 이유 (정규화 고려했으나 이벤트 로그 특성상 선택)

3. **DB 스키마** (Step 2 요구사항)
   - users, events 테이블 DDL 포함

4. **실행 방법 상세**
   - `docker compose up` 명령어
   - 분석 쿼리 실행 방법

---

## 주의사항
- 시각화(Step 5)는 추후 별도 지시 예정, 현재는 구현하지 말 것
- docker compose up 한 번으로 전체 파이프라인이 자동 실행되어야 함
- 이벤트 생성기는 DB가 준비된 후 실행되도록 depends_on 및 healthcheck 설정 필요
