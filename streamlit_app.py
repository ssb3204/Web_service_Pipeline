"""
라이브클래스 이벤트 로그 대시보드 (Streamlit)

queries.sql의 분석 3개를 시각화한다.
사이드바에서 분석 항목을 선택한다.

DB 연결은 환경변수에서 읽되, 로컬 실행을 위해 localhost 폴백 제공.
"""

from __future__ import annotations

import os
from typing import Final

import pandas as pd
import plotly.graph_objects as go
import psycopg2
import streamlit as st
from plotly.subplots import make_subplots

# ============================================================
# DB 연결 설정
# ============================================================

DB_CONFIG: Final[dict] = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "dbname": os.environ.get("DB_NAME", "eventlog"),
    "user": os.environ.get("DB_USER", "app"),
    "password": os.environ.get("DB_PASSWORD", "app"),
}


@st.cache_data(ttl=300, show_spinner=False)
def run_query(sql: str) -> pd.DataFrame:
    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


# ============================================================
# 페이지 함수
# ============================================================

_Q1_SQL = """
    SELECT
        EXTRACT(HOUR FROM timestamp)::INT AS hour,
        COUNT(*) AS event_count,
        SUM(CASE WHEN error_check THEN 1 ELSE 0 END) AS error_count,
        ROUND(
            SUM(CASE WHEN error_check THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
            2
        ) AS error_rate_pct
    FROM events
    GROUP BY hour
    ORDER BY hour
"""

_Q2_SQL = """
    SELECT
        event_type,
        COUNT(*) AS event_count,
        SUM(CASE WHEN error_check THEN 1 ELSE 0 END) AS error_count,
        ROUND(
            SUM(CASE WHEN error_check THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
            2
        ) AS error_rate_pct
    FROM events
    GROUP BY event_type
    ORDER BY event_count DESC
"""

_Q3_SQL = """
    SELECT
        SUM(CASE WHEN event_type = 'view'     THEN 1 ELSE 0 END) AS view_count,
        SUM(CASE WHEN event_type = 'cart'     THEN 1 ELSE 0 END) AS cart_count,
        SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchase_count
    FROM events
"""


def page_q1() -> None:
    st.subheader("Q1. 시간대별 이벤트 추이")
    st.caption("0~23시 분포로 트래픽 패턴과 시간대별 에러율을 동시에 확인 (이중축)")

    df = run_query(_Q1_SQL)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=df["hour"],
            y=df["event_count"],
            name="이벤트 수",
            mode="lines+markers",
            line={"color": "#1f77b4", "width": 3},
            marker={"size": 8},
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            x=df["hour"],
            y=df["error_rate_pct"],
            name="에러율 (%)",
            marker={"color": "#d62728"},
            opacity=0.45,
        ),
        secondary_y=True,
    )
    fig.update_xaxes(title_text="시간대 (시)", dtick=1)
    fig.update_yaxes(title_text="이벤트 수", secondary_y=False)
    fig.update_yaxes(title_text="에러율 (%)", secondary_y=True)
    fig.update_layout(
        hovermode="x unified",
        height=500,
        margin={"t": 30, "b": 40, "l": 40, "r": 40},
        legend={"orientation": "h", "y": 1.1},
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("원본 데이터"):
        st.dataframe(df, use_container_width=True, hide_index=True)


def page_q2() -> None:
    st.subheader("Q2. 이벤트 타입별 비율")
    st.caption("view / cart / purchase 비율 (파이) + 단계별 에러율 (바)")

    df = run_query(_Q2_SQL)

    TYPE_COLORS = {"view": "#1f77b4", "cart": "#ff7f0e", "purchase": "#2ca02c"}
    colors = [TYPE_COLORS.get(t, "#7f7f7f") for t in df["event_type"]]

    fig = make_subplots(
        rows=1,
        cols=2,
        specs=[[{"type": "pie"}, {"type": "bar"}]],
        subplot_titles=("이벤트 타입 비율", "단계별 에러율 (%)"),
    )

    fig.add_trace(
        go.Pie(
            labels=df["event_type"],
            values=df["event_count"],
            marker={"colors": colors},
            textinfo="label+percent",
            hole=0.35,
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            x=df["event_type"],
            y=df["error_rate_pct"],
            marker={"color": colors},
            text=df["error_rate_pct"].apply(lambda v: f"{v}%"),
            textposition="outside",
        ),
        row=1,
        col=2,
    )

    fig.update_layout(
        height=480,
        showlegend=False,
        margin={"t": 60, "b": 40, "l": 40, "r": 40},
    )
    fig.update_yaxes(title_text="에러율 (%)", row=1, col=2)

    st.plotly_chart(fig, use_container_width=True)

    with st.expander("원본 데이터"):
        st.dataframe(df, use_container_width=True, hide_index=True)


def page_q3() -> None:
    st.subheader("Q3. 조회 → 구매 전환율")
    st.caption("view → cart → purchase 퍼널 (절대수) + 단계별 전환율 카드")

    row = run_query(_Q3_SQL).iloc[0]
    view_cnt = int(row["view_count"])
    cart_cnt = int(row["cart_count"])
    purchase_cnt = int(row["purchase_count"])

    view_to_cart = round(cart_cnt * 100.0 / view_cnt, 1) if view_cnt else 0
    cart_to_purchase = round(purchase_cnt * 100.0 / cart_cnt, 1) if cart_cnt else 0
    view_to_purchase = round(purchase_cnt * 100.0 / view_cnt, 1) if view_cnt else 0

    # 퍼널 차트
    fig = go.Figure(go.Funnel(
        y=["view", "cart", "purchase"],
        x=[view_cnt, cart_cnt, purchase_cnt],
        textinfo="value+percent initial",
        textposition="inside",
        marker={"color": ["#1f77b4", "#ff7f0e", "#2ca02c"]},
        connector={"line": {"color": "#cccccc", "width": 2}},
    ))
    fig.update_layout(
        height=420,
        margin={"t": 30, "b": 30, "l": 120, "r": 40},
    )
    st.plotly_chart(fig, use_container_width=True)

    # 전환율 메트릭 카드 3개
    col1, col2, col3 = st.columns(3)
    col1.metric("view → cart", f"{view_to_cart}%")
    col2.metric("cart → purchase", f"{cart_to_purchase}%")
    col3.metric("view → purchase (전체)", f"{view_to_purchase}%")

    with st.expander("원본 데이터"):
        st.dataframe(
            pd.DataFrame({
                "단계": ["view", "cart", "purchase"],
                "이벤트 수": [view_cnt, cart_cnt, purchase_cnt],
            }),
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# 메인
# ============================================================


def main() -> None:
    st.set_page_config(
        page_title="이벤트 로그 대시보드",
        layout="wide",
    )
    st.title("라이브클래스 이벤트 로그 대시보드")
    st.caption(
        "이벤트 50K건 / 60일 백필 / Asia/Seoul 기준. queries.sql 분석 3개를 시각화."
    )

    with st.sidebar:
        st.header("설정")

        page = st.radio(
            "분석 항목",
            ["Q1. 시간대별 추이", "Q2. 이벤트 비율", "Q3. 전환율"],
        )

        st.divider()
        st.subheader("데이터셋")

        try:
            meta = run_query(
                """
                SELECT
                    (SELECT COUNT(*) FROM users)                    AS users,
                    (SELECT COUNT(*) FROM events)                   AS events,
                    (SELECT COUNT(DISTINCT session_id) FROM events) AS sessions
                """
            )
            row = meta.iloc[0]
            st.metric("총 유저", f"{int(row['users']):,}")
            st.metric("총 이벤트", f"{int(row['events']):,}")
            st.metric("총 세션", f"{int(row['sessions']):,}")
        except Exception as exc:
            st.error(f"DB 연결 실패: {exc}")
            st.stop()

    if page.startswith("Q1"):
        page_q1()
    elif page.startswith("Q2"):
        page_q2()
    else:
        page_q3()


if __name__ == "__main__":
    main()
