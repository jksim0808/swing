import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import io
import re
import time
from datetime import datetime, timedelta, timezone
import FinanceDataReader as fdr
from bs4 import BeautifulSoup
import concurrent.futures  # 🚀 일꾼을 여러 명 복제하는 마법의 도구

# =============================================================================
# [설정] 기본 셋팅
# =============================================================================
st.set_page_config(layout="wide", page_title="🎯 전천후 스윙 스캐너")
st.title("🎯 우량주 스윙 타점 스캐너 (안전망 풀가동 🛡️)")
st.markdown("차트 점수, **1차 목표가(전고점)**, **증권사 컨센서스**, **뉴스 호재**를 종합 분석합니다. \n\n*(※ 현재가 10,000원 이상 & 시가총액 1,000억 원 이상 우량/중형주 한정)*")

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
# 1. 데이터 수집 함수
# =============================================================================
@st.cache_data(ttl=3600*12)
def get_krx_info():
    df = fdr.StockListing('KRX')
    return df[['Name', 'Code', 'Marcap']].set_index('Name')

@st.cache_data(ttl=300)
def get_naver_top_universe():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    }
    krx_info = get_krx_info()
    df_list = []
    
    for sosok in [0, 1]:
        url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
        try:
            res = requests.get(url, headers=headers, timeout=5)
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
    
    full_df = full_df[full_df['현재가'] >= 10000]
    full_df['종목코드'] = full_df['종목명'].map(krx_info['Code'])
    full_df['시가총액'] = full_df['종목명'].map(krx_info['Marcap'])
    full_df = full_df.dropna(subset=['종목코드', '시가총액'])
    full_df = full_df[full_df['시가총액'] >= 100000000000]
    
    return full_df.sort_values(by='거래대금', ascending=False).head(100).reset_index(drop=True)

# =============================================================================
# 2. 증권사 목표가 및 뉴스 센티먼트 분석 (✨ 삼성전자 목표가 + 최신 헤드라인 부활!)
# =============================================================================
def get_fundamentals_and_news(code):
    target_price = "리포트 없음"
    news_status = "☁️ 특징 없음"
    news_headlines = "" # 📰 3.5 Flash 요원의 유산: 뉴스 제목 바구니
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    }
    
    # 📰 1. 뉴스 (네이버 모바일 API - 차단 없음 & 헤드라인 추출)
    try:
        url_news = f"https://m.stock.naver.com/api/news/stock/{code}?pageSize=10"
        res_news = requests.get(url_news, headers=headers, timeout=3)
        if res_news.status_code == 200:
            news_items = res_news.json()
            
            # 🔥 뉴스 제목 3개를 뽑아서 예쁜 텍스트로 만들기
            for news in news_items[:3]:
                title = news.get('tit', '')
                news_headlines += f"- {title}\n"
                
            pos_words = ['상승', '급등', '수주', '흑자', '돌파', '호실적', '성장', '최대', 'MOU', '계약', '기대', '강세', '수혜', '주목']
            neg_words = ['하락', '급락', '적자', '우려', '매도', '악재', '위기', '감소', '부진', '소송', '폭락', '약세']
            score = 0
            for news in news_items:
                title = news.get('tit', '')
                if any(w in title for w in pos_words): score += 1
                if any(w in title for w in neg_words): score -= 1
            if score >= 2: news_status = "🔥 호재 우세"
            elif score <= -2: news_status = "❄️ 악재 우세"
    except:
        news_headlines = "- 뉴스 로딩 실패"

    # 🎯 2. 목표가 (삼성전자도 무조건 잡아내는 텍스트 무차별 스캐닝)
    try:
        url_fn = f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A{code}"
        res_fn = requests.get(url_fn, headers=headers, timeout=3)
        
        if res_fn.status_code == 200:
            soup = BeautifulSoup(res_fn.text, 'html.parser')
            text = soup.get_text() # HTML 껍데기(태그) 무시하고 글자만 싹 뽑기
            
            # 정규식: '목표주가' 글씨 뒤에 30자 이내로 등장하는 4자리 이상의 숫자 무조건 포획!
            matches = re.findall(r'목표주가[^\d]{0,30}([1-9][\d,]{3,})', text)
            if matches:
                val = matches[0].replace(',', '').strip()
                if int(val) > 1000:
                    target_price = val
        else:
            target_price = f"오류({res_fn.status_code})"
    except Exception:
        target_price = "조회 실패"

    time.sleep(0.1) # 과부하 방지용 0.1초 휴식
    
    return target_price, news_status, news_headlines

# =============================================================================
# 3. 일봉 분석 알고리즘 (초대형주 예외 로직)
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
# ✨ 통합 데이터 캐싱 (🚀 멀티스레딩 초고속 엔진 장착!)
# =============================================================================
@st.cache_data(ttl=300, show_spinner=False)
def get_fully_analyzed_data(universe_df):
    results = []
    charts_data = {}
    
    # 일꾼 1명이 1개 종목을 처리하는 전용 작업 지시서
    def process_stock(row):
        code, name = row['종목코드'], row['종목명']
        marcap_100m = int(row['시가총액'] / 100000000)
        is_mega_cap = marcap_100m >= 100000 
        
        score, status, analyzed_df, high_price, target_yield = analyze_swing_probability(code, is_mega_cap=is_mega_cap)
        
        if score > 0:
            # 💡 기존 2개에서 3개(news_headlines)를 받는 것으로 수정!
            analyst_target, news_status, news_headlines = get_fundamentals_and_news(code)
            
            return {
                "상태": status,
                "점수": score, 
                "종목명": name,
                "시가총액(억)": marcap_100m, 
                "현재가": row['현재가'], 
                "1차 목표가(전고점)": high_price, 
                "전고점 기대수익(%)": target_yield, 
                "증권사 목표가": analyst_target,
                "뉴스 온도계": news_status,
                "최신 뉴스": news_headlines, # 👈 바구니에 담아주기!
                "종목코드": code
            }, name, analyzed_df
        return None

    # 🚀 일꾼 5명을 동시에 투입해서 초고속으로 네이버 데이터를 긁어옵니다!
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # 모든 종목을 일꾼들에게 던져줌
        futures = [executor.submit(process_stock, row) for i, row in universe_df.iterrows()]
        
        # 완료된 작업부터 순서대로 수거
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                item, name, df = res
                results.append(item)
                charts_data[name] = df
                
    return results, charts_data

# =============================================================================
# 4. 메인 화면 렌더링
# =============================================================================
universe_df = get_naver_top_universe()

if not universe_df.empty:
    with st.spinner("🔄 우량주 필터링 및 네이버 금융 데이터 수집 중입니다. (약 15~20초 소요)"):
        results, charts_data = get_fully_analyzed_data(universe_df)
    
    if results:
        top_30_df = pd.DataFrame(results).sort_values(by="점수", ascending=False).head(30).reset_index(drop=True)
        display_df = top_30_df.copy()
        
        def format_target(x):
            # 💡 에러 메시지("403 차단" 등)를 '정보 없음'으로 가리지 않고 그대로 노출시킵니다!
            if str(x).isdigit(): return f"{int(x):,} 원"
            return str(x) 
        display_df['증권사 목표가'] = display_df['증권사 목표가'].apply(format_target)
        
        selected_rows = st.dataframe(
            display_df[['상태', '점수', '종목명', '시가총액(억)', '현재가', '1차 목표가(전고점)', '전고점 기대수익(%)', '증권사 목표가', '뉴스 온도계']],
            use_container_width=True, selection_mode="single-row", on_select="rerun", hide_index=True,
            column_config={
                "점수": st.column_config.NumberColumn("🔥 점수", format="%d 점"),
                "시가총액(억)": st.column_config.NumberColumn("🏢 시가총액", format="%d 억"),
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
            t_marcap = top_30_df.iloc[idx]['시가총액(억)']
            t_news_list = top_30_df.iloc[idx]['최신 뉴스'] # 👈 뉴스 꺼내오기!
            
            st.markdown("---")
            col_chart, col_summary = st.columns([3, 1])
            with col_summary:
                st.info(f"**💡 {t_name} 요약**")
                st.write(f"- **시가총액:** {int(t_marcap):,}억 원")
                st.write(f"- **현재가:** {int(t_price):,}원")
                st.write(f"- **목표가(전고점):** {int(t_target):,}원")
                st.write(f"- **손절가(-3%):** {int(t_price * 0.97):,}원")
                st.write(f"- **기대수익률:** +{t_yield:.1f}%")
                st.write(f"- **뉴스 분위기:** {t_news}")
                st.markdown("**📰 최신 주요 뉴스**") # 👈 화면에 그리기
                st.markdown(t_news_list)
            
            with col_chart:
                df_chart = charts_data[t_name]
                
                # 💡 날짜 데이터를 안전하게 문자열로 변환하여 차트 증발 현상 방지
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
    st.error("데이터를 수집하지 못했습니다. 네이버 금융 연결 상태를 확인해주세요.")
