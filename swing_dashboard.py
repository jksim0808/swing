import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import io
from datetime import datetime, timedelta, timezone
import FinanceDataReader as fdr

# =============================================================================
# [설정] 기본 셋팅 및 모의투자 세션 초기화
# =============================================================================
st.set_page_config(layout="wide", page_title="🎯 전천후 스윙 스캐너 & 모의투자")
st.title("🎯 실전 스윙 스캐너 & 모의투자 시스템")

KST = timezone(timedelta(hours=9))

# 가상 매매(모의투자) 기록을 저장할 세션 스테이트 초기화
if 'portfolio' not in st.session_state:
    st.session_state.portfolio = pd.DataFrame(columns=['매수일자', '종목명', '매수가', '1차 목표가(전고점)', '손절가(-3%)', '기대수익률(%)'])

# =============================================================================
# 1. 데이터 수집 함수 (한국거래소 & 네이버 금융)
# =============================================================================
@st.cache_data(ttl=3600*12)
def get_krx_codes():
    df = fdr.StockListing('KRX')
    return df.set_index('Name')['Code'].to_dict()

@st.cache_data(ttl=300)
def get_naver_top_universe():
    headers = {'User-Agent': 'Mozilla/5.0'}
    code_map = get_krx_codes()
    df_list = []
    
    for sosok in [0, 1]:
        url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
        try:
            res = requests.get(url, headers=headers)
            res.encoding = 'euc-kr'
            dfs = pd.read_html(io.StringIO(res.text))
            df = dfs[1].dropna(how='all') 
            df = df[['종목명', '현재가', '전일비', '등락률', '거래량', '거래대금']]
            df_list.append(df)
        except: continue
            
    if not df_list: return pd.DataFrame()
        
    full_df = pd.concat(df_list, ignore_index=True)
    
    for col in ['현재가', '거래량', '거래대금']:
        full_df[col] = pd.to_numeric(full_df[col].astype(str).str.replace(',', ''), errors='coerce')
    full_df['등락률'] = pd.to_numeric(full_df['등락률'].astype(str).str.replace('%', ''), errors='coerce')
    
    pattern = '|'.join(['KODEX', 'TIGER', 'KBSTAR', 'ACE', 'ARIRANG', 'HANARO', 'KOSEF', 'SOL', 'TIMEFOLIO', 'WOORI', '스팩', 'ETN', '제\d+호', '우$'])
    full_df = full_df[~full_df['종목명'].str.contains(pattern, case=False, regex=True)]
    full_df = full_df[full_df['현재가'] >= 1000]
    full_df['종목코드'] = full_df['종목명'].map(code_map)
    full_df = full_df.dropna(subset=['종목코드']).sort_values(by='거래대금', ascending=False).head(100).reset_index(drop=True)
    
    return full_df

# =============================================================================
# 2. 일봉 분석 & 전고점(목표가) 탐색 알고리즘
# =============================================================================
def analyze_swing_probability(ticker, days=60):
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
        
        # 🎯 [추가된 로직] 최근 60일 전고점(최고가) 및 목표 수익률 계산
        highest_price = df['고가'].max()
        target_yield = ((highest_price - current_price) / current_price) * 100
        
        score = 40 
        status = "▪️ 관망"
        
        df['is_bull'] = (df['종가'] > df['시가'] * 1.05) & (df['거래량'] > df['Vol_MA5'].shift(1) * 3)
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
        
    except Exception:
        return 0, "분석 에러", pd.DataFrame(), 0, 0

# =============================================================================
# 3. 탭(Tab) 기반 UI 구성
# =============================================================================
tab1, tab2 = st.tabs(["🔍 1. 실시간 스윙 스캐너", "📝 2. 나의 모의투자 일지"])

# -----------------------------------------------------------------------------
# [TAB 1] 스윙 스캐너
# -----------------------------------------------------------------------------
with tab1:
    st.markdown("현재 시장을 주도하는 종목 중 **안전한 눌림목 확률**이 높은 30개를 추출하고 **목표가(전고점)**를 계산합니다.")
    
    universe_df = get_naver_top_universe()
    
    if not universe_df.empty:
        my_bar = st.progress(0, text="상위 100개 종목 정밀 분석 중...")
        results, charts_data = [], {}
        total_stocks = len(universe_df)
        
        for i, row in universe_df.iterrows():
            code, name = row['종목코드'], row['종목명']
            score, status, analyzed_df, high_price, target_yield = analyze_swing_probability(code)
            
            if score > 0:
                results.append({
                    "상태": status,
                    "점수": score,
                    "종목명": name,
                    "현재가": row['현재가'],
                    "1차 목표가(전고점)": high_price,
                    "전고점까지 남은 수익(%)": target_yield,
                    "종목코드": code
                })
                charts_data[name] = analyzed_df
                
            my_bar.progress((i + 1) / total_stocks, text=f"분석 중: {name} ({i+1}/{total_stocks})")
            
        my_bar.empty()
        
        if results:
            top_30_df = pd.DataFrame(results).sort_values(by="점수", ascending=False).head(30).reset_index(drop=True)
            
            display_df = top_30_df.copy()
            display_df['점수'] = display_df['점수'].apply(lambda x: f"🔥 {x} 점")
            display_df['현재가'] = display_df['현재가'].apply(lambda x: f"{int(x):,} 원")
            display_df['1차 목표가(전고점)'] = display_df['1차 목표가(전고점)'].apply(lambda x: f"{int(x):,} 원")
            display_df['전고점까지 남은 수익(%)'] = display_df['전고점까지 남은 수익(%)'].apply(lambda x: f"🎯 +{x:.1f}% 기대")
            
            selected_rows = st.dataframe(
                display_df[['상태', '점수', '종목명', '현재가', '1차 목표가(전고점)', '전고점까지 남은 수익(%)']],
                use_container_width=True, selection_mode="single-row", on_select="rerun", hide_index=True
            )

            # 종목 선택 시 액션
            if hasattr(selected_rows, 'selection') and len(selected_rows.selection.rows) > 0:
                idx = selected_rows.selection.rows[0]
                t_name = top_30_df.iloc[idx]['종목명']
                t_price = top_30_df.iloc[idx]['현재가']
                t_target = top_30_df.iloc[idx]['1차 목표가(전고점)']
                t_yield = top_30_df.iloc[idx]['전고점까지 남은 수익(%)']
                
                st.markdown("---")
                col_chart, col_buy = st.columns([3, 1])
                
                with col_buy:
                    st.success(f"**{t_name}** 분석 결과")
                    st.write(f"- **현재가:** {int(t_price):,}원")
                    st.write(f"- **1차 목표가:** {int(t_target):,}원")
                    st.write(f"- **손절가(-3%):** {int(t_price * 0.97):,}원")
                    st.write(f"- **기대수익률:** +{t_yield:.1f}%")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    # 🛒 모의투자 매수 버튼
                    if st.button(f"🛒 '{t_name}' 가상 매수하기", use_container_width=True, type="primary"):
                        new_trade = pd.DataFrame([{
                            '매수일자': datetime.now(KST).strftime('%Y-%m-%d %H:%M'),
                            '종목명': t_name,
                            '매수가': int(t_price),
                            '1차 목표가(전고점)': int(t_target),
                            '손절가(-3%)': int(t_price * 0.97),
                            '기대수익률(%)': round(t_yield, 1)
                        }])
                        st.session_state.portfolio = pd.concat([st.session_state.portfolio, new_trade], ignore_index=True)
                        st.toast(f"✅ {t_name} 모의 매수 완료! '나의 모의투자 일지' 탭을 확인하세요.", icon="📈")
                
                with col_chart:
                    df_chart = charts_data[t_name]
                    fig = go.Figure(go.Candlestick(
                        x=df_chart['날짜'], open=df_chart['시가'], high=df_chart['고가'], low=df_chart['저가'], close=df_chart['종가'],
                        increasing_line_color='#ff4b4b', decreasing_line_color='#0068c9', name="일봉"
                    ))
                    fig.add_trace(go.Scatter(x=df_chart['날짜'], y=df_chart['MA5'], mode='lines', line=dict(color='#ff9900', width=1.5), name="5일선"))
                    fig.add_trace(go.Scatter(x=df_chart['날짜'], y=df_chart['MA20'], mode='lines', line=dict(color='#cc00ff', width=2.5), name="20일선(생명선)"))
                    # 전고점 목표가 가이드라인 (점선)
                    fig.add_hline(y=t_target, line_dash="dot", line_color="red", annotation_text="1차 목표가 (전고점)", annotation_position="top right")
                    
                    fig.update_layout(height=450, template="plotly_dark", margin=dict(l=0, r=40, t=20, b=0), xaxis=dict(rangeslider=dict(visible=False), type='category'))
                    st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------------
# [TAB 2] 모의투자 일지
# -----------------------------------------------------------------------------
with tab2:
    st.subheader("📝 나의 모의투자 포트폴리오")
    st.markdown("스캐너에서 가상 매수한 종목들이 기록됩니다. (※ 새로고침하면 기록이 초기화됩니다.)")
    
    if st.session_state.portfolio.empty:
        st.info("아직 가상 매수한 종목이 없습니다. 스캐너 탭에서 종목을 골라 '가상 매수하기' 버튼을 눌러보세요!")
    else:
        st.dataframe(st.session_state.portfolio, use_container_width=True, hide_index=True)
        
        if st.button("🗑️ 전체 기록 초기화"):
            st.session_state.portfolio = pd.DataFrame(columns=['매수일자', '종목명', '매수가', '1차 목표가(전고점)', '손절가(-3%)', '기대수익률(%)'])
            st.rerun()
