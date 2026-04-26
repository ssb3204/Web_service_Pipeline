"""
Kaggle eCommerce 데이터에서 event_type별 시간 가중치(KST 기준)를 추출.

입력: 2019-Oct.csv (UTC 타임스탬프)
처리: 10% 랜덤 샘플 (random_state=3) → UTC→Asia/Seoul 변환 → 시간대별 분포
출력: VIEW/CART/PURCHASE_HOUR_WEIGHTS dict (정규화된 % 비율)
"""

import sys
from pathlib import Path

import pandas as pd

CSV_PATH = Path(r"C:\Users\ryanp\Desktop\2019-Oct.csv")
SAMPLE_FRAC = 0.10
RANDOM_STATE = 3
CHUNKSIZE = 500_000
EVENT_TYPES = ("view", "cart", "purchase")


def load_sample() -> pd.DataFrame:
    if not CSV_PATH.exists():
        sys.exit(f"CSV not found: {CSV_PATH}")

    print(f"Reading {CSV_PATH.name} in chunks of {CHUNKSIZE:,} rows...")
    samples = []
    total_rows = 0
    for i, chunk in enumerate(
        pd.read_csv(
            CSV_PATH,
            chunksize=CHUNKSIZE,
            usecols=["event_time", "event_type"],
        )
    ):
        total_rows += len(chunk)
        sampled = chunk.sample(frac=SAMPLE_FRAC, random_state=RANDOM_STATE)
        samples.append(sampled)
        if (i + 1) % 10 == 0:
            print(f"  processed {total_rows:,} rows, sampled {sum(len(s) for s in samples):,}")

    df = pd.concat(samples, ignore_index=True)
    print(f"Total rows scanned : {total_rows:,}")
    print(f"Sampled rows       : {len(df):,}")
    return df


def convert_to_kst_hour(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["event_time"] = pd.to_datetime(df["event_time"], utc=True, format="mixed")
    df["hour_kst"] = df["event_time"].dt.tz_convert("Asia/Seoul").dt.hour
    return df


def compute_weights(df: pd.DataFrame) -> dict[str, dict[int, float]]:
    result: dict[str, dict[int, float]] = {}
    for et in EVENT_TYPES:
        sub = df.loc[df["event_type"] == et, "hour_kst"]
        counts = sub.value_counts().sort_index()
        total = counts.sum()
        weights = (counts / total * 100).round(2)
        result[et] = {int(h): float(weights.get(h, 0.0)) for h in range(24)}
    return result


def print_dict(name: str, weights: dict[int, float]) -> None:
    print(f"\n{name} = {{")
    for h in range(24):
        v = weights.get(h, 0.0)
        comma = "," if h < 23 else ""
        print(f"    {h:>2}: {v:>5.2f}{comma}")
    print("}")


def main() -> None:
    df = load_sample()

    print("\nEvent type distribution in sample:")
    print(df["event_type"].value_counts().to_string())

    df = convert_to_kst_hour(df)
    weights = compute_weights(df)

    for et in EVENT_TYPES:
        print_dict(f"{et.upper()}_HOUR_WEIGHTS", weights[et])


if __name__ == "__main__":
    main()
