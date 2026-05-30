import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import io
from datetime import datetime, timedelta, timezone
import FinanceDataReader as fdr
from bs4 import BeautifulSoup

# =============================================================================
# [설정] 기본 셋팅
# =============================================================================
st.set_page_config(layout="wide", page_title="🎯 전천후 스윙 스캐너")
st.title("🎯 우량주 스윙 타점 스캐너 (1만 원 이상)")
st.markdown("차트 점수, **1차 목표가(전고점)**, **증권사 컨센서스**, **실시간 뉴스 호재 분석**을 한눈에 종합 분석합니다. (10,000원 이상 안정적 종목 한정)")

KST = timezone(timedelta(hours=9))

# =============================================================================
# 1. 데이터 수집 함수
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
    
    # 10,000원 이상 종목만 필터링
    full_df = full_df[full_df['현재가'] >= 10000]
    
    full_df['종목코드'] = full_df['종목명'].map(code_map)
    
    return full_df.dropna(subset=['종목코드']).sort_values(by='거래대금', ascending=False).head(100).reset_index(drop=True)

# =============================================================================
# 2. 증권사 목표가 및 뉴스 센티먼트 분석
# =============================================================================
def get_fundamentals_and_news(code):
    headers = {'User-Agent': 'Mozilla/5.0'}
    target_price = "N/A"
    news_status = "☁️ 보통"
    
    try:
        url_main = f"https://finance.naver.com/item/main.naver?code={code}"
        res_main = requests.get(url_main, headers=headers, timeout=2)
        soup_main = BeautifulSoup(res_main.text, 'html.parser')
        
        cns_eps = soup_main.select_one('#_step_bank_cns')
        if cns_eps:
            target_price = cns_eps.text.strip().replace(',', '')
        
        url_news = f"https://finance.naver.com/item/news_news.naver?code={code}&page=1"
        res_news = requests.get(url_news, headers=headers, timeout=2)
        soup_news = BeautifulSoup(res_news.content.decode('euc-kr', 'replace'), 'html.parser')
        
        titles = soup_news.select('.title a')
        pos_words = ['상승', '급등', '수주', '흑자', '돌파', '호실적', '성장', '최대', 'MOU', '계약', '기대', '강세', '수혜']
        neg_words = ['하락', '급락', '적자', '우려', '매도', '악재', '위기', '감소', '부진', '소송', '폭락', '약세', '쇼크']
        
        score = 0
        for title in titles[:10]:
            text = title.text
            if any(word in text for word in pos_words): score += 1
            if any(word in text for word in neg_words): score -= 1
            
        if score >= 2: news_status = "🔥 호재 우세"
        elif score <= -2: news_status = "❄️ 악재 우세"
        else: news_status = "☁️ 특징 없음"
    except: pass
        
    return target_price, news_status

# =============================================================================
# 3. 일봉 분석 알고리즘
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
    except:
        return 0, "에러", pd.DataFrame(), 0, 0

# =============================================================================
# ✨ 통합 데이터 캐싱 (종목 분석 + 펀더멘털/뉴스 동시 수집)
# =============================================================================
@st.cache_data(ttl=300, show_spinner=False)
def get_fully_analyzed_data(universe_df):
    results = []
    charts_data = {}
    
    for i, row in universe_df.iterrows():
        code, name = row['종목코드'], row['종목명']
        score, status, analyzed_df, high_price, target_yield = analyze_swing_probability(code)
        
        if score > 0:
            analyst_target, news_status = get_fundamentals_and_news(code)
            
            results.append({
                "상태": status,
                "점수": score, # 순수 숫자 유지
                "종목명": name,
                "현재가": row['현재가'], # 순수 숫자 유지
                "1차 목표가(전고점)": high_price, # 순수 숫자 유지
                "전고점 기대수익(%)": target_yield, # 순수 숫자 유지
                "증권사 목표가": analyst_target,
                "뉴스 온도계": news_status,
                "종목코드": code
            })
            charts_data[name] = analyzed_df
            
    return results, charts_data

# =============================================================================
# 4. 메인 화면 렌더링
# =============================================================================
universe_df = get_naver_top_universe()

if not universe_df.empty:
    with st.spinner("🔄 데이터를 수집하고 차트를 분석 중입니다. (약 15~20초 소요, 이후 즉시 반응)"):
        results, charts_data = get_fully_analyzed_data(universe_df)
    
    if results:
        top_30_df = pd.DataFrame(results).sort_values(by="점수", ascending=False).head(30).reset_index(drop=True)
        
        display_df = top_30_df.copy()
        
        # 증권사 목표가는 "N/A"(문자)가 섞일 수 있으므로 포맷팅 처리
        def format_target(x):
            if x == "N/A" or not str(x).isdigit(): return "정보 없음"
            return f"{int(x):,} 원"
        display_df['증권사 목표가'] = display_df['증권사 목표가'].apply(format_target)
        
        # 💡 [핵심 해결] 데이터를 문자열로 바꾸지 않고, column_config를 통해 '보이는 모습'만 꾸며줍니다.
        selected_rows = st.dataframe(
            display_df[['상태', '점수', '종목명', '현재가', '1차 목표가(전고점)', '전고점 기대수익(%)', '증권사 목표가', '뉴스 온도계']],
            use_container_width=True, 
            selection_mode="single-row", 
            on_select="rerun", 
            hide_index=True,
            column_config={
                "점수": st.column_config.NumberColumn("🔥 점수", format="%d 점"),
                "현재가": st.column_config.NumberColumn("현재가", format="%d 원"),
                "1차 목표가(전고점)": st.column_config.NumberColumn("1차 목표가", format="%d 원"),
                "전고점 기대수익(%)": st.column_config.NumberColumn("🎯 기대수익(%)", format="%.1f %%")
            }
        )

        if hasattr(selected_rows, 'selection') and len(selected_rows.selection.rows) > 0:
            idx = selected_rows.selection.rows[0]
            t_name = top_30_df.iloc[idx]['종목명']
            t_price = top_30_df.iloc[idx]['현재가']
            t_target = top_30_df.iloc[idx]['1차 목표가(전고점)']
            t_yield = top_30_df.iloc[idx]['전고점 기대수익(%)']
            t_news = top_30_df.iloc[idx]['뉴스 온도계']
            
            st.markdown("---")
            col_chart, col_summary = st.columns([3, 1])
            
            with col_summary:
                st.info(f"**💡 {t_name} 요약**")
                st.write(f"- **현재가:** {int(t_price):,}원")
                st.write(f"- **목표가(전고점):** {int(t_target):,}원")
                st.write(f"- **손절가(-3%):** {int(t_price * 0.97):,}원")
                st.write(f"- **기대수익률:** +{t_yield:.1f}%")
                st.write(f"- **뉴스 분위기:** {t_news}")
            
            with col_chart:
                df_chart = charts_data[t_name]
                fig = go.Figure(go.Candlestick(
                    x=df_chart['날짜'], open=df_chart['시가'], high=df_chart['고가'], low=df_chart['저가'], close=df_chart['종가'],
                    increasing_line_color='#ff4b4b', decreasing_line_color='#0068c9', name="일봉"
                ))
                fig.add_trace(go.Scatter(x=df_chart['날짜'], y=df_chart['MA5'], mode='lines', line=dict(color='#ff9900', width=1.5), name="5일선"))
                fig.add_trace(go.Scatter(x=df_chart['날짜'], y=df_chart['MA20'], mode='lines', line=dict(color='#cc00ff', width=2.5), name="20일선(생명선)"))
                fig.add_hline(y=t_target, line_dash="dot", line_color="red", annotation_text="1차 목표가 (전고점)", annotation_position="top right")
                
                fig.update_layout(height=450, template="plotly_dark", margin=dict(l=0, r=40, t=20, b=0), xaxis=dict(rangeslider=dict(visible=False), type='category'))
                st.plotly_chart(fig, use_container_width=True)
else:
    st.error("데이터를 수집하지 못했습니다. 네이버 금융 연결 상태를 확인해주세요.")
