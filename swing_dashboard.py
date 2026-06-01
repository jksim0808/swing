import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
import FinanceDataReader as fdr
import concurrent.futures
from pykrx import stock

# =============================================================================
# [설정] 기본 셋팅
# =============================================================================
st.set_page_config(layout="wide", page_title="🎯 전천후 스윙 스캐너")
st.title("🎯 우량주 스윙 타점 스캐너 (초고속 Lite 🚀)")
st.markdown("차트 점수, **당일 등락률**, **1차 목표가(전고점)**를 3초 안에 초고속으로 스캔합니다. \n\n*(※ 현재가 10,000원 이상 & 시가총액 1,000억 원 이상 우량/중형주 한정)*")

with st.expander("📖 AI 스캐너 상태값 선별 기준 및 매매 로직 (클릭하여 펼치기)", expanded=False):
    st.markdown("""
    이 스캐너는 **'최근 20일 이내에 의미 있는 대량 거래량을 동반한 장대양봉(세력 개입)'**이 있었는가를 가장 먼저 확인합니다.
    * **일반 우량주:** 하루 상승률 **5%** 이상 & 거래량 평소 대비 **3배** 이상
    * **👑 초대형주(시가총액 10조 이상):** 무거운 엉덩이를 감안하여 하루 상승률 **3%** 이상 & 거래량 평소 대비 **2배** 이상으로 예외 적용

    * **🎯 S급 눌림목 (+최고점):** 세력 개입 흔적이 있으며, 주가가 20일선 근처(-2% ~ +5% 구간)로 조정을 받았고, **거래량이 평소의 60% 이하로 바싹 마른 상태**입니다. 매도세가 멈춘 가장 이상적인 스윙 진입 타점입니다.
    * **🟡 지지선 근접:** 주가가 20일선 근처까지 내려왔지만, 아직 거래량이 충분히 줄어들지 않아 지지 여부 확인이 필요합니다.
    * **🔥 급등 진행형:** 세력 개입 후 주가가 20일선 대비 10% 이상 치솟아 올라가고 있는 구간으로 신규 진입 시 고점에 물릴 위험이 큽니다.
    * **📉 추세 이탈:** 주가가 20일선(생명선) 아래로 뚫고 내려간 단기 하락 추세입니다.
    * **▪️ 관망:** 최근 의미 있는 상승(기준봉)이 없었거나, 시장의 소외를 받고 있는 상태입니다.
    """)

KST = timezone(timedelta(hours=9))

# =============================================================================
# 1. 🚀 혁신적인 데이터 수집 함수 (pykrx + fdr 사용, 크롤링 X)
# =============================================================================
@st.cache_data(ttl=300)
def get_krx_top_universe():
    # 1. 오늘 날짜(또는 가장 최근 평일) 기준 거래소 데이터 호출
    today = datetime.now(KST)
    if today.hour < 15 or today.weekday() >= 5: # 장중이거나 주말이면 어제(또는 금요일) 데이터 기준
        target_date = (today - timedelta(days=1)).strftime('%Y%m%d')
    else:
        target_date = today.strftime('%Y%m%d')

    try:
        # 2. pykrx로 시장 전체 종목의 거래대금, 등락률, 종가 등 핵심 정보 일괄 조회
        df_ohlcv = stock.get_market_ohlcv(target_date, market="ALL")
        df_marcap = stock.get_market_cap(target_date, market="ALL")
        
        # 데이터 병합
        full_df = pd.concat([df_ohlcv, df_marcap], axis=1)
        full_df = full_df.reset_index()
        full_df.rename(columns={'티커': '종목코드', '종가': '현재가', '거래량': '거래량', '거래대금': '거래대금', '등락률': '등락률', '시가총액': '시가총액'}, inplace=True)
        
        # 3. 종목코드에 해당하는 종목명 매핑
        full_df['종목명'] = full_df['종목코드'].apply(lambda x: stock.get_market_ticker_name(x))
        
        # 4. 필터링 로직 (ETF, 스팩 등 제외 및 가격/시총 기준 적용)
        pattern = '|'.join(['KODEX', 'TIGER', 'KBSTAR', 'ACE', 'ARIRANG', 'HANARO', 'KOSEF', 'SOL', 'TIMEFOLIO', 'WOORI', '스팩', 'ETN', '제\d+호', '우$'])
        full_df['종목명'] = full_df['종목명'].astype(str).fillna('')
        full_df = full_df[~full_df['종목명'].str.contains(pattern, case=False, regex=True)]
        
        full_df = full_df[full_df['현재가'] >= 10000]
        full_df = full_df[full_df['시가총액'] >= 100000000000]
        
        # 5. 거래대금 상위 100개 종목 추출 (이전의 top universe 100개와 동일)
        return full_df.sort_values(by='거래대금', ascending=False).head(100).reset_index(drop=True)
        
    except Exception as e:
        print(f"Error fetching data: {e}")
        return pd.DataFrame()

# =============================================================================
# 2. 일봉 분석 알고리즘 (초대형주 예외 로직)
# =============================================================================
def analyze_swing_probability(ticker, is_mega_cap=False, days=60):
    end_date = datetime.now(KST)
    start_date = end_date - timedelta(days=days)
    try:
        df = fdr.DataReader(ticker, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        if len(df) < 20: return 0, "데이터 부족", pd.DataFrame(), 0, 0
        
        df = df.reset_index()
        df.rename(columns={'Date': '날짜', 'Open': '시가', 'High': '고가', 'Low': '저가', 'Close': '종가', 'Volume': '거래량'}, inplace=True)
        
        df['MA5'] = df['종가'].rolling(window=5).mean()
        df['MA20'] = df['종가'].rolling(window=20).mean()
        df['Vol_MA5'] = df['거래량'].rolling(window=5).mean()
        
        current_price = df['종가'].iloc[-1]
        current_vol = df['거래량'].iloc[-1]
        ma20 = df['MA20'].iloc[-1]
        
        highest_price = df['고가'].max()
        target_yield = ((highest_price - current_price) / current_price) * 100
        
        score = 40 
        status = "▪️ 관망"
        
        surge_ratio = 1.03 if is_mega_cap else 1.05
        vol_ratio = 2.0 if is_mega_cap else 3.0
        
        df['is_bull'] = (df['종가'] > df['시가'] * surge_ratio) & (df['거래량'] > df['Vol_MA5'].shift(1) * vol_ratio)
        recent_bull = df.iloc[-20:][df.iloc[-20:]['is_bull'] == True]
        
        if not recent_bull.empty:
            score += 25 
            if ma20 * 0.98 <= current_price <= ma20 * 1.05:
                score += 15
                status = "🟡 지지선 근접"
                if current_vol < df['Vol_MA5'].iloc[-2] * 0.6:
                    score += 20
                    status = "🎯 S급 눌림목"
            elif current_price > ma20 * 1.10:
                score += 5
                status = "🔥 급등 진행형"
        else:
            if current_price < ma20:
                score -= 20
                status = "📉 추세 이탈"
                
        return min(99, score), status, df, highest_price, target_yield
    except:
        return 0, "에러", pd.DataFrame(), 0, 0

# =============================================================================
# ✨ 통합 데이터 캐싱 (🚀 멀티스레딩 초고속 엔진 장착)
# =============================================================================
@st.cache_data(ttl=300, show_spinner=False)
def get_fully_analyzed_data(universe_df):
    results = []
    charts_data = {}
    
    def process_stock(row):
        code, name = row['종목코드'], row['종목명']
        marcap_100m = int(row['시가총액'] / 100000000)
        is_mega_cap = marcap_100m >= 100000 
        
        score, status, analyzed_df, high_price, target_yield = analyze_swing_probability(code, is_mega_cap=is_mega_cap)
        
        if score > 0:
            return {
                "상태": status,
                "점수": score, 
                "종목명": name,
                "시가총액(억)": marcap_100m, 
                "현재가": row['현재가'], 
                "당일 등락률(%)": row['등락률'], 
                "1차 목표가(전고점)": high_price, 
                "전고점 기대수익(%)": target_yield, 
                "종목코드": code
            }, name, analyzed_df
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_stock, row) for i, row in universe_df.iterrows()]
        
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                item, name, df = res
                results.append(item)
                charts_data[name] = df
                
    return results, charts_data

# =============================================================================
# 3. 메인 화면 렌더링
# =============================================================================
universe_df = get_krx_top_universe()

if not universe_df.empty:
    with st.spinner("🔄 우량주 필터링 및 차트 데이터 분석 중입니다... (초고속 스캔 🚀)"):
        results, charts_data = get_fully_analyzed_data(universe_df)
    
    if results:
        top_30_df = pd.DataFrame(results).sort_values(by="점수", ascending=False).head(30).reset_index(drop=True)
        display_df = top_30_df.copy()
        
        selected_rows = st.dataframe(
            display_df[['상태', '점수', '종목명', '시가총액(억)', '현재가', '당일 등락률(%)', '1차 목표가(전고점)', '전고점 기대수익(%)']],
            use_container_width=True, selection_mode="single-row", on_select="rerun", hide_index=True,
            column_config={
                "점수": st.column_config.NumberColumn("🔥 점수", format="%d 점"),
                "시가총액(억)": st.column_config.NumberColumn("🏢 시가총액", format="%d 억"),
                "현재가": st.column_config.NumberColumn("현재가", format="%d 원"),
                "당일 등락률(%)": st.column_config.NumberColumn("📈 당일 수익률", format="%.2f %%"),
                "1차 목표가(전고점)": st.column_config.NumberColumn("1차 목표가", format="%d 원"),
                "전고점 기대수익(%)": st.column_config.NumberColumn("🎯 기대수익(%)", format="%.1f %%")
            }
        )

        if hasattr(selected_rows, 'selection') and len(selected_rows.selection.rows) > 0:
            idx = selected_rows.selection.rows[0]
            t_name = top_30_df.iloc[idx]['종목명']
            t_price = top_30_df.iloc[idx]['현재가']
            t_change = top_30_df.iloc[idx]['당일 등락률(%)']
            t_target = top_30_df.iloc[idx]['1차 목표가(전고점)']
            t_yield = top_30_df.iloc[idx]['전고점 기대수익(%)']
            t_marcap = top_30_df.iloc[idx]['시가총액(억)']
            
            st.markdown("---")
            col_chart, col_summary = st.columns([3, 1])
            with col_summary:
                st.info(f"**💡 {t_name} 요약**")
                st.write(f"- **시가총액:** {int(t_marcap):,}억 원")
                st.write(f"- **현재가:** {int(t_price):,}원")
                st.write(f"- **당일 수익률:** {t_change:+.2f}%") 
                st.write(f"- **목표가(전고점):** {int(t_target):,}원")
                st.write(f"- **손절가(-3%):** {int(t_price * 0.97):,}원")
                st.write(f"- **기대수익률:** +{t_yield:.1f}%")
            
            with col_chart:
                df_chart = charts_data[t_name]
                
                date_str = pd.to_datetime(df_chart['날짜']).dt.strftime('%Y-%m-%d')
                
                fig = go.Figure(go.Candlestick(
                    x=date_str, open=df_chart['시가'], high=df_chart['고가'], low=df_chart['저가'], close=df_chart['종가'],
                    increasing_line_color='#ff4b4b', decreasing_line_color='#0068c9', name="일봉"
                ))
                fig.add_trace(go.Scatter(x=date_str, y=df_chart['MA5'], mode='lines', line=dict(color='#ff9900', width=1.5), name="5일선"))
                fig.add_trace(go.Scatter(x=date_str, y=df_chart['MA20'], mode='lines', line=dict(color='#cc00ff', width=2.5), name="20일선(생명선)"))
                fig.add_hline(y=t_target, line_dash="dot", line_color="red", annotation_text="1차 목표가 (전고점)", annotation_position="top right")
                
                fig.update_layout(height=450, template="plotly_dark", margin=dict(l=0, r=40, t=20, b=0), xaxis=dict(rangeslider=dict(visible=False), type='category'))
                st.plotly_chart(fig, use_container_width=True)
else:
    st.error("데이터를 수집하지 못했습니다. 라이브러리(pykrx, FinanceDataReader) 설치 상태를 확인해주세요.")
