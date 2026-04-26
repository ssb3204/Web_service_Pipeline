"""
event_generator.py — 라이브클래스 이벤트 로그 백필 생성기.

200명 유저, 50,000 이벤트, 20 강의, 최근 60일에 분산 → PostgreSQL INSERT.

생성 모델:
- 시간 우선 샘플(VIEW_HOUR_WEIGHTS, ±20% 노이즈) → action 점수 비교 → action 결정
- (user, lecture) 페어별 상태 추적 (view_count / cart / purchase)
- view→cart 강의 선택은 누적 조회수 벨커브 가중 (3~5번 피크)
- 유저는 Zipf 가중치(s=1)로 활동 편차 부여
- session_id: 같은 유저 30분 윈도우 = 동일 session_id

가중치 출처: Kaggle 'eCommerce behavior data from multi category store'
2019-Oct.csv 10% 샘플(4.24M건), UTC→KST 변환, scripts/extract_weights.py 참조.
"""

from __future__ import annotations

import os
import random
import sys
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import execute_values

# ---- Configuration ----------------------------------------------------------

USER_COUNT = 200
EVENT_COUNT = 50_000
LECTURE_COUNT = 20
BACKFILL_DAYS = 60
HOUR_NOISE_PCT = 0.20
SESSION_WINDOW_MIN = 30
ZIPF_S = 1.0
RANDOM_SEED = 42

DEVICE_MOBILE_PCT = 0.60

# 전체 이벤트 비율 목표 (96/2/2). hour_weight과 곱해져 시간대별로 변조됨.
ACTION_RATIO = {"view": 0.96, "cart": 0.02, "purchase": 0.02}

# 행동별 에러 발생률 (글로벌 이커머스 벤치마크).
ERROR_RATES = {"view": 0.005, "cart": 0.03, "purchase": 0.08}

# 누적 조회수 → cart 매력도 벨커브 (1~2 낮음, 3~5 피크, 6+ 하락).
BELL_CURVE = {1: 1, 2: 2, 3: 4, 4: 5, 5: 4, 6: 3, 7: 2}
BELL_CURVE_DEFAULT = 1  # 8회 이상

# Kaggle 추출값 (정규화된 % per hour, KST). 합계 ≒ 100.
VIEW_HOUR_WEIGHTS = {
    0: 7.09, 1: 7.29, 2: 6.53, 3: 5.07, 4: 3.20, 5: 1.77,
    6: 1.05, 7: 0.65, 8: 0.53, 9: 0.74, 10: 1.33, 11: 2.55,
    12: 3.66, 13: 4.47, 14: 4.94, 15: 5.27, 16: 5.43, 17: 5.58,
    18: 5.48, 19: 5.34, 20: 5.11, 21: 5.00, 22: 5.55, 23: 6.37,
}
CART_HOUR_WEIGHTS = {
    0: 5.45, 1: 5.01, 2: 4.32, 3: 3.26, 4: 2.21, 5: 1.29,
    6: 0.72, 7: 0.44, 8: 0.37, 9: 0.45, 10: 0.80, 11: 1.89,
    12: 3.73, 13: 5.20, 14: 6.16, 15: 6.78, 16: 7.04, 17: 7.32,
    18: 7.34, 19: 6.80, 20: 6.41, 21: 5.90, 22: 5.61, 23: 5.49,
}
PURCHASE_HOUR_WEIGHTS = {
    0: 5.09, 1: 4.78, 2: 4.04, 3: 3.22, 4: 2.27, 5: 1.35,
    6: 0.88, 7: 0.48, 8: 0.39, 9: 0.37, 10: 0.76, 11: 1.86,
    12: 3.81, 13: 5.56, 14: 6.63, 15: 6.92, 16: 7.15, 17: 7.39,
    18: 7.49, 19: 7.00, 20: 6.57, 21: 5.58, 22: 5.33, 23: 5.07,
}

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "eventlog"),
    "user": os.getenv("DB_USER", "app"),
    "password": os.getenv("DB_PASSWORD", "app"),
}

KST = ZoneInfo("Asia/Seoul")


# ---- Helpers ----------------------------------------------------------------

def apply_noise_and_normalize(
    weights: dict[int, float], pct: float, rng: random.Random
) -> dict[int, float]:
    """각 시간 가중치에 ±pct 노이즈 부여 후 합 100으로 정규화."""
    noised = {h: w * (1 + rng.uniform(-pct, pct)) for h, w in weights.items()}
    total = sum(noised.values())
    return {h: v / total * 100 for h, v in noised.items()}


def sample_hour(weights_pct: dict[int, float], rng: random.Random) -> int:
    hours = list(weights_pct.keys())
    pcts = list(weights_pct.values())
    return rng.choices(hours, weights=pcts, k=1)[0]


def zipf_weights(n: int, s: float) -> list[float]:
    raw = [1.0 / ((i + 1) ** s) for i in range(n)]
    total = sum(raw)
    return [r / total for r in raw]


def bell_curve_score(view_count: int) -> int:
    return BELL_CURVE.get(view_count, BELL_CURVE_DEFAULT)


# ---- User generation -------------------------------------------------------

def generate_users(rng: random.Random, base_dt: datetime) -> list[dict]:
    users = []
    for i in range(1, USER_COUNT + 1):
        device = "mobile" if rng.random() < DEVICE_MOBILE_PCT else "desktop"
        # 백필 시작 이전(60~90일 전)에 가입한 유저로 가정.
        offset_days = rng.randint(BACKFILL_DAYS, BACKFILL_DAYS + 30)
        created_at = base_dt - timedelta(
            days=offset_days,
            hours=rng.randint(0, 23),
            minutes=rng.randint(0, 59),
        )
        users.append(
            {
                "user_id": f"user_{i:04d}",
                "name": f"User {i:03d}",
                "created_at": created_at,
                "device_type": device,
            }
        )
    return users


# ---- Event generation ------------------------------------------------------

def pre_allocate_timestamps(
    view_weights_noisy: dict[int, float],
    base_dt: datetime,
    rng: random.Random,
) -> list[datetime]:
    """[base_dt - BACKFILL_DAYS, base_dt) 범위에 EVENT_COUNT개 timestamp 생성.
    일자: 균등, 시간: VIEW_HOUR_WEIGHTS 가중, 분/초: 균등.
    """
    start = base_dt - timedelta(days=BACKFILL_DAYS)
    timestamps = []
    for _ in range(EVENT_COUNT):
        day_offset = rng.randint(0, BACKFILL_DAYS - 1)
        hour = sample_hour(view_weights_noisy, rng)
        minute = rng.randint(0, 59)
        second = rng.randint(0, 59)
        ts = start + timedelta(
            days=day_offset, hours=hour, minutes=minute, seconds=second
        )
        timestamps.append(ts)
    timestamps.sort()
    return timestamps


def pick_action_and_lecture(
    user: str,
    hour: int,
    state: dict,
    weights_v: dict[int, float],
    weights_c: dict[int, float],
    weights_p: dict[int, float],
    rng: random.Random,
) -> tuple[str, str]:
    """1) hour에서 가능한 action 점수 비교 후 샘플
    2) 선택된 action에 맞는 lecture 결정 (cart는 벨커브 가중)
    3) 상태가 안 맞으면 view로 폴백 (순서 보장: view→cart→purchase).
    """
    action_weights = [
        ("view", ACTION_RATIO["view"] * weights_v[hour]),
        ("cart", ACTION_RATIO["cart"] * weights_c[hour]),
        ("purchase", ACTION_RATIO["purchase"] * weights_p[hour]),
    ]
    actions = [a for a, _ in action_weights]
    aw = [w for _, w in action_weights]
    action = rng.choices(actions, weights=aw, k=1)[0]

    user_state = state.setdefault(user, {})

    if action == "purchase":
        candidates = [
            l for l, s in user_state.items() if s["cart"] and not s["purchase"]
        ]
        if candidates:
            return "purchase", rng.choice(candidates)
        action = "cart"  # 폴백

    if action == "cart":
        weighted = [
            (l, bell_curve_score(s["view_count"]))
            for l, s in user_state.items()
            if s["view_count"] >= 1 and not s["cart"]
        ]
        if weighted:
            lectures = [l for l, _ in weighted]
            ws = [w for _, w in weighted]
            return "cart", rng.choices(lectures, weights=ws, k=1)[0]
        action = "view"  # 폴백

    # view: 강의 균등 선택
    lecture = f"lec_{rng.randint(1, LECTURE_COUNT):02d}"
    return "view", lecture


def update_state(state: dict, user: str, action: str, lecture: str) -> None:
    user_state = state.setdefault(user, {})
    lec_state = user_state.setdefault(
        lecture, {"view_count": 0, "cart": False, "purchase": False}
    )
    if action == "view":
        lec_state["view_count"] += 1
    elif action == "cart":
        lec_state["cart"] = True
    elif action == "purchase":
        lec_state["purchase"] = True


def assign_session_ids(events: list[dict]) -> None:
    """events는 timestamp 오름차순 가정. 같은 유저의 30분 이내 이벤트는 동일 session_id."""
    last_ts: dict[str, datetime] = {}
    last_sid: dict[str, str] = {}
    window = timedelta(minutes=SESSION_WINDOW_MIN)
    session_counter = 0
    for ev in events:
        u = ev["user_id"]
        ts = ev["timestamp"]
        if u in last_ts and ts - last_ts[u] <= window:
            ev["session_id"] = last_sid[u]
        else:
            session_counter += 1
            sid = f"sess_{session_counter:05d}"
            ev["session_id"] = sid
            last_sid[u] = sid
        last_ts[u] = ts


def generate_events(
    users: list[dict], rng: random.Random, base_dt: datetime
) -> list[dict]:
    weights_v = apply_noise_and_normalize(VIEW_HOUR_WEIGHTS, HOUR_NOISE_PCT, rng)
    weights_c = apply_noise_and_normalize(CART_HOUR_WEIGHTS, HOUR_NOISE_PCT, rng)
    weights_p = apply_noise_and_normalize(PURCHASE_HOUR_WEIGHTS, HOUR_NOISE_PCT, rng)

    user_ids = [u["user_id"] for u in users]
    user_w = zipf_weights(USER_COUNT, ZIPF_S)

    timestamps = pre_allocate_timestamps(weights_v, base_dt, rng)

    state: dict = {}
    events: list[dict] = []
    for i, ts in enumerate(timestamps, start=1):
        user = rng.choices(user_ids, weights=user_w, k=1)[0]
        action, lecture = pick_action_and_lecture(
            user, ts.hour, state, weights_v, weights_c, weights_p, rng
        )
        is_error = rng.random() < ERROR_RATES[action]
        events.append(
            {
                "event_id": f"evt_{i:05d}",
                "user_id": user,
                "event_type": action,
                "error_check": is_error,
                "lecture_id": lecture,
                "timestamp": ts,
            }
        )
        update_state(state, user, action, lecture)

    assign_session_ids(events)
    return events


# ---- DB Insert -------------------------------------------------------------

def insert_users(conn, users: list[dict]) -> None:
    rows = [
        (u["user_id"], u["name"], u["created_at"], u["device_type"]) for u in users
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO users (user_id, name, created_at, device_type) VALUES %s "
            "ON CONFLICT (user_id) DO NOTHING",
            rows,
        )
    conn.commit()


def insert_events(conn, events: list[dict]) -> None:
    rows = [
        (
            e["event_id"],
            e["user_id"],
            e["session_id"],
            e["event_type"],
            e["error_check"],
            e["lecture_id"],
            e["timestamp"],
        )
        for e in events
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO events "
            "(event_id, user_id, session_id, event_type, error_check, lecture_id, timestamp) "
            "VALUES %s ON CONFLICT (event_id) DO NOTHING",
            rows,
            page_size=1000,
        )
    conn.commit()


def aggregate_to_summary(conn) -> None:
    """events를 (bucket_hour, user_id, event_type)로 사전 집계해 agg_event_summary에 적재.

    백필 1회 모드 → TRUNCATE 후 전량 재계산하여 idempotent 보장.
    raw events와의 EXPLAIN ANALYZE 비교 대상이 되는 wide fact 테이블.
    """
    with conn.cursor() as cur:
        cur.execute("TRUNCATE agg_event_summary;")
        cur.execute(
            """
            INSERT INTO agg_event_summary
                (bucket_hour, user_id, event_type, event_count, error_count)
            SELECT
                date_trunc('hour', timestamp) AS bucket_hour,
                user_id,
                event_type,
                COUNT(*) AS event_count,
                SUM(CASE WHEN error_check THEN 1 ELSE 0 END) AS error_count
            FROM events
            GROUP BY date_trunc('hour', timestamp), user_id, event_type
            """
        )
    conn.commit()


# ---- Main ------------------------------------------------------------------

def print_stats(events: list[dict]) -> None:
    type_counts = Counter(e["event_type"] for e in events)
    total = len(events)
    print(f"  total           : {total:,}")
    for et in ("view", "cart", "purchase"):
        c = type_counts[et]
        print(f"  {et:<15} : {c:>6,} ({c / total * 100:5.2f}%)")
    err = sum(1 for e in events if e["error_check"])
    print(f"  errors          : {err:>6,} ({err / total * 100:5.2f}%)")
    sessions = len({e["session_id"] for e in events})
    print(f"  sessions        : {sessions:>6,} (avg {total / sessions:.2f} ev/sess)")


def main() -> None:
    rng = random.Random(RANDOM_SEED)
    base_dt = datetime.now(KST).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )

    print(f"Backfill window : [{base_dt - timedelta(days=BACKFILL_DAYS)}, {base_dt}) KST")

    print("Generating users...")
    users = generate_users(rng, base_dt)
    print(f"  {len(users)} users")

    print("Generating events...")
    events = generate_events(users, rng, base_dt)
    print_stats(events)

    print(
        f"\nConnecting to PostgreSQL ({DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']})..."
    )
    try:
        conn = psycopg2.connect(**DB_CONFIG)
    except psycopg2.OperationalError as e:
        print(f"DB connection failed: {e}")
        print("Make sure docker compose is running:  docker compose -p eventlog up -d")
        sys.exit(1)

    try:
        print("Inserting users...")
        insert_users(conn, users)
        print("Inserting events...")
        insert_events(conn, events)
        print("Aggregating to agg_event_summary...")
        aggregate_to_summary(conn)
        print("Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
