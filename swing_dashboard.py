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
# [설정] 기본 셋팅 (쇼츠 세로 화면을 위해 centered 레이아웃 사용)
# =============================================================================
st.set_page_config(layout="centered", page_title="오늘의 핫스윙 스캐너")

# 📱 쇼츠용 커스텀 CSS (거대한 폰트와 모바일 최적화 레이아웃)
st.markdown("""
<style>
    /* 전체 배경을 어둡게 설정 */
    .stApp { background-color: #0E1117; }
    
    /* 요소들 간격 좁히기 */
    .block-container { padding-top: 2rem; padding-bottom: 0rem; max-width: 900px; }
    
    /* 텍스트 스타일링 */
    .shorts-title { font-size: 55px; font-weight: 900; color: #FF4B4B; text-align: center; margin-bottom: 0px; line-height: 1.2; }
    .shorts-subtitle { font-size: 35px; color: #AAAAAA; text-align: center; margin-top: 10px; margin-bottom: 40px; }
    .stock-name { font-size: 110px; font-weight: 900; color: #FFFFFF; text-align: center; margin-top: 0px; margin-bottom: 20px; line-height: 1.1; }
    .status-badge { font-size: 45px; background-color: #FF9900; color: #000000; padding: 10px 40px; border-radius: 50px; font-weight: bold; }
    .yield-text { font-size: 80px; font-weight: 900; color: #00FF00; margin-top: 30px; text-align: center; }
    .price-info { font-size: 40px; color: #DDDDDD; text-align: center; margin-top: 20px; line-height: 1.5; }
    
    /* AI 성우가 읽을 대본 영역 (화면 하단에 깔끔하게 배치) */
    .script-box { background-color: #1E1E1E; border-left: 10px solid #FF4B4B; padding: 30px; border-radius: 15px; margin-top: 40px; font-size: 32px; color: #E0E0E0; line-height: 1.6; }
</style>
""", unsafe_allow_html=True)

KST = timezone(timedelta(hours=9))

# =============================================================================
# 1. 데이터 수집 함수 (기존과 동일)
# =============================================================================
@st.cache_data(ttl=3600*12)
def get_krx_info():
    df = fdr.StockListing('KRX')
    return df[['Name', 'Code', 'Marcap']].set_index('Name')

@st.cache_data(ttl=300)
def get_naver_top_universe():
    headers = {'User-Agent': 'Mozilla/5.0'}
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
# 2. 증권사 목표가 및 뉴스 센티먼트 분석 (기존과 동일)
# =============================================================================
def get_fundamentals_and_news(code):
    headers = {'User-Agent': 'Mozilla/5.0'}
    target_price, news_status = "N/A", "☁️ 보통"
    try:
        url_main = f"https://finance.naver.com/item/main.naver?code={code}"
        res_main = requests.get(url_main, headers=headers, timeout=5)
        soup_main = BeautifulSoup(res_main.text, 'html.parser')
        
        cns_eps = soup_main.select_one('#_step_bank_cns')
        if cns_eps: target_price = cns_eps.text.strip().replace(',', '')
        
        url_news = f"https://finance.naver.com/item/news_news.naver?code={code}&page=1"
        res_news = requests.get(url_news, headers=headers, timeout=5)
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
# 3. 일봉 분석 알고리즘 (기존과 동일)
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

@st.cache_data(ttl=300, show_spinner=False)
def get_fully_analyzed_data(universe_df):
    results, charts_data = [], {}
    for i, row in universe_df.iterrows():
        code, name = row['종목코드'], row['종목명']
        marcap_100m = int(row['시가총액'] / 100000000)
        score, status, analyzed_df, high_price, target_yield = analyze_swing_probability(code, is_mega_cap=(marcap_100m >= 100000))
        if score > 0:
            analyst_target, news_status = get_fundamentals_and_news(code)
            results.append({
                "상태": status, "점수": score, "종목명": name, "시가총액(억)": marcap_100m, 
                "현재가": row['현재가'], "1차 목표가(전고점)": high_price, 
                "전고점 기대수익(%)": target_yield, "증권사 목표가": analyst_target, "뉴스 온도계": news_status
            })
            charts_data[name] = analyzed_df
    return results, charts_data


# =============================================================================
# 4. 메인 화면 렌더링 (🔥 쇼츠용 극대화 UI)
# =============================================================================
universe_df = get_naver_top_universe()

if not universe_df.empty:
    with st.spinner("🔄 데이터 분석 중..."):
        results, charts_data = get_fully_analyzed_data(universe_df)
    
    if results:
        # 점수가 가장 높은 1등 종목 딱 1개만 추출
        top_stock = pd.DataFrame(results).sort_values(by="점수", ascending=False).iloc[0]
        
        t_name = top_stock['종목명']
        t_status = top_stock['상태']
        t_price = int(top_stock['현재가'])
        t_target = int(top_stock['1차 목표가(전고점)'])
        t_yield = top_stock['전고점 기대수익(%)']
        t_news = top_stock['뉴스 온도계']
        df_chart = charts_data[t_name]

        # ---------------------------------------------------------
        # [화면 상단] 어그로 타이틀 & 1등 종목 정보 (HTML 적용)
        # ---------------------------------------------------------
        st.markdown(f'<div class="shorts-title">🚨 AI 포착 오늘의 S급 스윙 🚨</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="shorts-subtitle">거래대금 상위 100종목 알고리즘 분석 완료</div>', unsafe_allow_html=True)
        
        st.markdown(f'<div style="text-align: center;"><span class="status-badge">{t_status}</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="stock-name">{t_name}</div>', unsafe_allow_html=True)
        
        st.markdown(f'<div class="yield-text">목표 수익률 +{t_yield:.1f}%</div>', unsafe_allow_html=True)
        
        st.markdown(f'''
        <div class="price-info">
            ▪️ <b>현재가:</b> {t_price:,} 원<br>
            ▪️ <b>1차 목표가:</b> {t_target:,} 원<br>
            ▪️ <b>뉴스 분위기:</b> {t_news}
        </div>
        ''', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ---------------------------------------------------------
        # [화면 중단] 모바일에 꽉 차는 거대한 차트
        # ---------------------------------------------------------
        date_str = pd.to_datetime(df_chart['날짜']).dt.strftime('%m-%d')
        fig = go.Figure()
        
        # 캔들스틱 굵기 증가
        fig.add_trace(go.Candlestick(
            x=date_str, open=df_chart['시가'], high=df_chart['고가'], low=df_chart['저가'], close=df_chart['종가'],
            increasing_line_color='#ff4b4b', decreasing_line_color='#0068c9', name="일봉"
        ))
        
        # 이평선 굵기 증가
        fig.add_trace(go.Scatter(x=date_str, y=df_chart['MA5'], mode='lines', line=dict(color='#ff9900', width=4), name="5일선"))
        fig.add_trace(go.Scatter(x=date_str, y=df_chart['MA20'], mode='lines', line=dict(color='#cc00ff', width=6), name="20일선"))
        
        # 목표가 점선 라인 굵기 및 폰트 증가
        fig.add_hline(y=t_target, line_dash="dash", line_color="red", line_width=3, 
                      annotation_text="목표가", annotation_font_size=30, annotation_font_color="red")
        
        fig.update_layout(
            height=600,  # 모바일 화면을 꽉 채우기 위해 세로 길이 대폭 증가
            template="plotly_dark",
            margin=dict(l=10, r=60, t=10, b=10),
            xaxis=dict(rangeslider=dict(visible=False), type='category', tickfont=dict(size=20)),
            yaxis=dict(tickfont=dict(size=25)), # y축 가격 폰트 키우기
            showlegend=False # 모바일 화면이 좁으므로 레전드 숨김
        )
        st.plotly_chart(fig, use_container_width=True)

        # ---------------------------------------------------------
        # [화면 하단] 🎙️ Playwright가 긁어갈 AI 대본 (TTS용)
        # ---------------------------------------------------------
        # 이 텍스트는 화면 하단에 예쁜 박스 형태로 표시되며, 동시에 Playwright가 음성 합성을 위해 추출해 갑니다.
        script_content = f"""
        AI가 포착한 오늘의 핫한 스윙 종목, 바로 {t_name} 입니다. 
        현재 차트 상태는 {t_status} 이며, 최근 발생한 의미 있는 거래량을 동반한 상승 이후, 20일선 근처에서 조정을 받고 있습니다.
        현재가 {t_price:,}원에서 진입 시, 이전 고점인 {t_target:,}원까지 약 {t_yield:.1f}% 의 기대 수익이 예상됩니다. 
        관련 뉴스와 시장 분위기는 {t_news} 상태입니다. 단기 스윙 타점, 지금 바로 확인해보세요!
        """
        st.markdown(f'<div class="script-box" id="tts_script">{script_content}</div>', unsafe_allow_html=True)

else:
    st.error("데이터를 수집하지 못했습니다. 연결 상태를 확인해주세요.")
