import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
import FinanceDataReader as fdr

# =============================================================================
# [설정] 기본 셋팅
# =============================================================================
st.set_page_config(layout="wide", page_title="📈 주도주 스윙매매 스캐너")
st.title("🏄‍♂️ 주도 테마 눌림목 스윙 스캐너")
st.markdown("단기 급등 후 거래량이 죽으며 지지선을 버티는 **'안전한 스윙 타점'**을 찾습니다.")

KST = timezone(timedelta(hours=9))


# =============================================================================
# 1. 핵심 데이터 로드 (과거 3개월 치 일봉 데이터)
# =============================================================================
@st.cache_data(ttl=3600)
def get_market_data(ticker, days=90):
    """특정 종목의 과거 N일치 일봉 데이터를 가져옵니다."""
    end_date = datetime.now(KST)
    start_date = end_date - timedelta(days=days)
    try:
        df = fdr.DataReader(ticker, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        if not df.empty:
            df = df.reset_index()
            # FinanceDataReader의 컬럼명을 표준화
            df.rename(columns={'Date': '날짜', 'Open': '시가', 'High': '고가', 'Low': '저가', 'Close': '종가', 'Volume': '거래량'},
                      inplace=True)
            return df
    except Exception as e:
        pass
    return pd.DataFrame()


# -----------------------------------------------------------------------------
# 💡 가상의 주도 테마 및 관심 종목 리스트 (실전에서는 실시간 랭킹 API 연동 필요)
# -----------------------------------------------------------------------------
# 스윙은 '시장의 관심이 쏠린 대장주'에서 해야 하므로 테마별 대장주를 세팅합니다.
THEME_STOCKS = {
    "🤖 반도체/AI": {"SK하이닉스": "000660", "한미반도체": "042700", "이수페타시스": "041510"},
    "🔋 2차전지": {"에코프로": "086520", "포스코홀딩스": "005490", "LG에너지솔루션": "373220"},
    "⚡ 전력설비": {"HD현대일렉트릭": "267260", "LS일렉트릭": "010120", "제룡전기": "033100"},
    "🧬 바이오": {"알테오젠": "196170", "HLB": "028300", "삼천당제약": "000250"}
}


# =============================================================================
# 2. 스윙매매(눌림목) 타점 분석 알고리즘
# =============================================================================
def analyze_swing_target(df):
    """
    일봉 데이터를 분석하여 스윙(눌림목) 진입 매력도를 평가합니다.
    """
    if len(df) < 20:
        return 0, "데이터 부족", df

    # 1. 이동평균선 계산
    df['MA5'] = df['종가'].rolling(window=5).mean()
    df['MA20'] = df['종가'].rolling(window=20).mean()
    df['MA60'] = df['종가'].rolling(window=60).mean()
    df['Vol_MA5'] = df['거래량'].rolling(window=5).mean()

    current_price = df['종가'].iloc[-1]
    current_vol = df['거래량'].iloc[-1]
    ma20 = df['MA20'].iloc[-1]

    # 2. 기준봉(최근 20일 내 대량 거래 장대양봉) 찾기
    df['is_bull_candle'] = (df['종가'] > df['시가'] * 1.05) & (df['거래량'] > df['Vol_MA5'].shift(1) * 3)
    recent_bull = df.iloc[-20:][df.iloc[-20:]['is_bull_candle'] == True]

    score = 50  # 기본 점수
    status = "▪️ 관망"

    if not recent_bull.empty:
        score += 20  # 기준봉이 있으면 +20점

        # 3. 눌림목 조건 확인 (주가는 20일선 근처 지지, 거래량은 바닥)
        if current_price >= ma20 * 0.98 and current_price <= ma20 * 1.05:  # 20일선 근처
            if current_vol < df['Vol_MA5'].iloc[-2] * 0.7:  # 거래량이 확 죽었을 때
                score += 30
                status = "🎯 1급 눌림목"
            else:
                status = "🟡 지지 테스트 중"
    else:
        # 기준봉이 없고 20일선 아래면 추세 이탈
        if current_price < ma20:
            score -= 20
            status = "📉 추세 이탈"

    return min(100, score), status, df


# =============================================================================
# 3. 대시보드 UI (사이드바 및 메인 화면)
# =============================================================================
st.sidebar.header("🔍 스윙 종목 필터")
selected_theme = st.sidebar.selectbox("주도 테마 선택", list(THEME_STOCKS.keys()))

st.subheader(f"[{selected_theme}] 테마 대장주 스윙 타점 분석")

# 선택한 테마의 종목들을 분석하여 표로 출력
results = []
charts_data = {}

with st.spinner("과거 일봉 데이터를 분석 중입니다..."):
    for name, code in THEME_STOCKS[selected_theme].items():
        df = get_market_data(code)
        if not df.empty:
            score, status, analyzed_df = analyze_swing_target(df)
            current_p = analyzed_df['종가'].iloc[-1]
            prev_p = analyzed_df['종가'].iloc[-2]
            change_pct = ((current_p - prev_p) / prev_p) * 100

            results.append({
                "종목명": name,
                "종목코드": code,
                "스윙 매력도": score,
                "상태": status,
                "현재가": current_p,
                "등락률(%)": round(change_pct, 2)
            })
            charts_data[name] = analyzed_df

if results:
    result_df = pd.DataFrame(results).sort_values(by="스윙 매력도", ascending=False)

    # 디스플레이용 포맷팅
    display_df = result_df.copy()
    display_df['스윙 매력도'] = display_df['스윙 매력도'].apply(lambda x: f"{x} 점")
    display_df['현재가'] = display_df['현재가'].apply(lambda x: f"{int(x):,} 원")
    display_df['등락률(%)'] = display_df['등락률(%)'].apply(lambda x: f"{x:+.2f}%")

    st.dataframe(
        display_df[['상태', '스윙 매력도', '종목명', '현재가', '등락률(%)']],
        use_container_width=True,
        hide_index=True
    )

    # -------------------------------------------------------------------------
    # 4. 차트 시각화 (선택한 종목의 일봉 차트)
    # -------------------------------------------------------------------------
    st.markdown("---")
    selected_stock = st.selectbox("📊 정밀 분석할 종목의 일봉 차트를 선택하세요:", result_df['종목명'].tolist())

    if selected_stock:
        df_chart = charts_data[selected_stock]

        fig = go.Figure()

        # 캔들스틱 (일봉)
        fig.add_trace(go.Candlestick(
            x=df_chart['날짜'], open=df_chart['시가'], high=df_chart['고가'], low=df_chart['저가'], close=df_chart['종가'],
            increasing_line_color='#ff4b4b', decreasing_line_color='#0068c9', name="일봉"
        ))

        # 이동평균선
        fig.add_trace(
            go.Scatter(x=df_chart['날짜'], y=df_chart['MA5'], mode='lines', line=dict(color='#ff9900', width=1.5),
                       name="5일선"))
        fig.add_trace(
            go.Scatter(x=df_chart['날짜'], y=df_chart['MA20'], mode='lines', line=dict(color='#cc00ff', width=2.5),
                       name="20일선(생명선)"))

        # 거래량 바차트 (서브플롯 효과)
        colors = ['#ff4b4b' if df_chart['종가'].iloc[i] >= df_chart['시가'].iloc[i] else '#0068c9' for i in
                  range(len(df_chart))]
        fig.add_trace(
            go.Bar(x=df_chart['날짜'], y=df_chart['거래량'], name="거래량", marker_color=colors, opacity=0.5, yaxis='y2'))

        fig.update_layout(
            title=f"<b>{selected_stock}</b> 일봉 차트 (최근 3개월)",
            height=600,
            template="plotly_dark",
            xaxis=dict(rangeslider=dict(visible=False), type='category'),  # 주말 공백 제거
            yaxis=dict(title="주가", side='right', domain=[0.3, 1]),
            yaxis2=dict(title="거래량", side='right', domain=[0, 0.2], showgrid=False),
            hovermode="x unified",
            margin=dict(l=20, r=20, t=50, b=20)
        )
        st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("데이터를 불러올 수 없습니다.")

st.markdown("---")
with st.expander("📖 스윙매매 타점 분석 로직 설명"):
    st.markdown("""
    * **기준봉 포착:** 최근 20일 이내에 평소 거래량의 3배 이상이 터지면서 5% 이상 급등한 양봉(세력 개입)이 있는지 확인합니다.
    * **1급 눌림목 (🎯):** 주가가 급등 후 하락하다가 **20일 이동평균선(생명선)** 근처(-2% ~ +5%)에서 지지받고 있으며, 이때 **거래량이 평소보다 확연히 줄어들었을 때(매도세 고갈)** 가장 높은 점수를 부여합니다.
    * **추세 이탈 (📉):** 주가가 20일선 아래로 뚫고 내려가면 단기 하락 추세로 전환되었다고 판단하여 점수를 깎습니다.
    """)