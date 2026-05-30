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
st.set_page_config(layout="wide", page_title="🎯 전천후 스윙 확률 스캐너")
st.title("🎯 전종목 스윙 타점 스캐너 (네이버 연동)")
st.markdown("테마 상관없이 현재 시장에서 돈이 가장 많이 몰린 종목 중 **'안전한 눌림목 확률'**이 높은 상위 30개를 추출합니다.")

KST = timezone(timedelta(hours=9))

# =============================================================================
# 1. 데이터 수집: 네이버 상위 종목 크롤링 및 종목코드 매핑
# =============================================================================
@st.cache_data(ttl=3600*12)
def get_krx_codes():
    """한국거래소 전체 종목 코드를 가져와 이름-코드 딕셔너리로 만듭니다."""
    df = fdr.StockListing('KRX')
    return df.set_index('Name')['Code'].to_dict()

@st.cache_data(ttl=300)
def get_naver_top_universe():
    """네이버 금융에서 코스피/코스닥 거래 상위 종목을 긁어옵니다."""
    headers = {'User-Agent': 'Mozilla/5.0'}
    code_map = get_krx_codes()
    df_list = []
    
    # 0: 코스피, 1: 코스닥 (각각 상위 100개씩 추출)
    for sosok in [0, 1]:
        url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
        try:
            res = requests.get(url, headers=headers)
            res.encoding = 'euc-kr'
            # HTML 표 읽기
            dfs = pd.read_html(io.StringIO(res.text))
            df = dfs[1].dropna(how='all') # 보통 2번째 표가 메인 데이터
            
            # 필요한 열만 추출 및 이름 변경
            df = df[['종목명', '현재가', '전일비', '등락률', '거래량', '거래대금']]
            df_list.append(df)
        except Exception as e:
            continue
            
    if not df_list:
        return pd.DataFrame()
        
    full_df = pd.concat(df_list, ignore_index=True)
    
    # 데이터 정제 (숫자형 변환)
    for col in ['현재가', '거래량', '거래대금']:
        full_df[col] = pd.to_numeric(full_df[col].astype(str).str.replace(',', ''), errors='coerce')
    full_df['등락률'] = pd.to_numeric(full_df['등락률'].astype(str).str.replace('%', ''), errors='coerce')
    
    # 불필요한 ETF, 스팩(SPAC), 우선주 등 필터링
    pattern = '|'.join(['KODEX', 'TIGER', 'KBSTAR', 'ACE', 'ARIRANG', 'HANARO', 'KOSEF', 'SOL', 'TIMEFOLIO', 'WOORI', '스팩', 'ETN', '제\d+호', '우$'])
    full_df = full_df[~full_df['종목명'].str.contains(pattern, case=False, regex=True)]
    
    # 너무 싼 동전주(1000원 미만) 제외
    full_df = full_df[full_df['현재가'] >= 1000]
    
    # 종목명으로 종목코드 매핑
    full_df['종목코드'] = full_df['종목명'].map(code_map)
    full_df = full_df.dropna(subset=['종목코드'])
    
    # 거래대금 상위 100개로 압축 (분석 속도 최적화)
    full_df = full_df.sort_values(by='거래대금', ascending=False).head(100).reset_index(drop=True)
    
    return full_df

# =============================================================================
# 2. 핵심 알고리즘: 일봉 분석 및 스윙 확률(점수) 계산
# =============================================================================
def analyze_swing_probability(ticker, days=60):
    """특정 종목의 과거 일봉 데이터를 바탕으로 눌림목 성공 확률(점수)을 계산합니다."""
    end_date = datetime.now(KST)
    start_date = end_date - timedelta(days=days)
    
    try:
        # 일봉 데이터 로드
        df = fdr.DataReader(ticker, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        if len(df) < 20: return 0, "데이터 부족", pd.DataFrame()
        
        df = df.reset_index()
        df.rename(columns={'Date': '날짜', 'Open': '시가', 'High': '고가', 'Low': '저가', 'Close': '종가', 'Volume': '거래량'}, inplace=True)
        
        # 이동평균선 계산
        df['MA5'] = df['종가'].rolling(window=5).mean()
        df['MA20'] = df['종가'].rolling(window=20).mean()
        df['Vol_MA5'] = df['거래량'].rolling(window=5).mean()
        
        current_price = df['종가'].iloc[-1]
        current_vol = df['거래량'].iloc[-1]
        ma20 = df['MA20'].iloc[-1]
        
        score = 40 # 기본 시작 점수
        status = "▪️ 관망"
        
        # 조건 1: 돈이 들어왔는가? (최근 20일 내 거래량 3배 이상 터진 장대양봉)
        df['is_bull'] = (df['종가'] > df['시가'] * 1.05) & (df['거래량'] > df['Vol_MA5'].shift(1) * 3)
        recent_bull = df.iloc[-20:][df.iloc[-20:]['is_bull'] == True]
        
        if not recent_bull.empty:
            score += 25 # 세력(큰돈) 개입 흔적 
            
            # 조건 2: 20일 생명선 지지 (주가가 MA20의 -2% ~ +5% 구간에 위치)
            if ma20 * 0.98 <= current_price <= ma20 * 1.05:
                score += 15
                status = "🟡 지지선 근접"
                
                # 조건 3: 거래량 고갈 (매도세가 말랐는가?)
                if current_vol < df['Vol_MA5'].iloc[-2] * 0.6:
                    score += 20
                    status = "🎯 S급 눌림목"
            
            # 조건 4: 급등 중인 경우 (돌파)
            elif current_price > ma20 * 1.10:
                score += 5
                status = "🔥 급등 진행형"
        else:
            if current_price < ma20:
                score -= 20
                status = "📉 추세 이탈"
                
        # 최대 점수 99점으로 제한 (심리적 신뢰도)
        return min(99, score), status, df
        
    except Exception:
        return 0, "분석 에러", pd.DataFrame()

# =============================================================================
# 3. 대시보드 렌더링 및 UI
# =============================================================================
st.subheader("🔍 실시간 데이터 수집 및 분석 중...")

# 캐시된 유니버스 가져오기
universe_df = get_naver_top_universe()

if not universe_df.empty:
    # 프로그래스 바 (분석 진행 상황 표시)
    progress_text = "상위 100개 종목의 과거 차트 패턴을 정밀 분석하고 있습니다..."
    my_bar = st.progress(0, text=progress_text)
    
    results = []
    charts_data = {}
    total_stocks = len(universe_df)
    
    # 100개 종목 순회하며 점수 매기기
    for i, row in universe_df.iterrows():
        code = row['종목코드']
        name = row['종목명']
        
        score, status, analyzed_df = analyze_swing_probability(code)
        
        if score > 0:
            results.append({
                "상태": status,
                "스윙 확률(점수)": score,
                "종목명": name,
                "현재가": row['현재가'],
                "등락률": row['등락률'],
                "거래대금(백만)": row['거래대금'],
                "종목코드": code
            })
            charts_data[name] = analyzed_df
            
        # 프로그래스 바 업데이트
        my_bar.progress((i + 1) / total_stocks, text=f"분석 중: {name} ({i+1}/{total_stocks})")
        
    my_bar.empty() # 분석 완료 시 프로그래스 바 숨기기
    
    # 결과가 있다면 점수순으로 정렬하여 상위 30개 추출
    if results:
        result_df = pd.DataFrame(results)
        top_30_df = result_df.sort_values(by="스윙 확률(점수)", ascending=False).head(30)
        
        st.subheader("🏆 눌림목 스윙 확률 상위 Top 30 종목")
        
        # 출력용 데이터 포맷팅
        display_df = top_30_df.copy()
        display_df['스윙 확률(점수)'] = display_df['스윙 확률(점수)'].apply(lambda x: f"🔥 {x} 점")
        display_df['현재가'] = display_df['현재가'].apply(lambda x: f"{int(x):,} 원")
        display_df['등락률'] = display_df['등락률'].apply(lambda x: f"{x:+.2f} %")
        display_df['거래대금(백만)'] = display_df['거래대금(백만)'].apply(lambda x: f"{int(x):,}")
        
        # 데이터프레임 출력
        selected_rows = st.dataframe(
            display_df[['상태', '스윙 확률(점수)', '종목명', '현재가', '등락률', '거래대금(백만)']],
            use_container_width=True,
            selection_mode="single-row",
            on_select="rerun",
            hide_index=True
        )

        # ---------------------------------------------------------------------
        # 4. 종목 클릭 시 일봉 차트 시각화
        # ---------------------------------------------------------------------
        if hasattr(selected_rows, 'selection') and len(selected_rows.selection.rows) > 0:
            selected_idx = selected_rows.selection.rows[0]
            target_name = top_30_df.iloc[selected_idx]['종목명']
            
            st.markdown("---")
            st.markdown(f"### 📊 {target_name} 정밀 일봉 차트 (최근 60일)")
            
            df_chart = charts_data[target_name]
            
            if not df_chart.empty:
                fig = go.Figure()
                
                # 캔들스틱
                fig.add_trace(go.Candlestick(
                    x=df_chart['날짜'], open=df_chart['시가'], high=df_chart['고가'], low=df_chart['저가'], close=df_chart['종가'],
                    increasing_line_color='#ff4b4b', decreasing_line_color='#0068c9', name="일봉"
                ))
                
                # 이동평균선
                fig.add_trace(go.Scatter(x=df_chart['날짜'], y=df_chart['MA5'], mode='lines', line=dict(color='#ff9900', width=1.5), name="5일선"))
                fig.add_trace(go.Scatter(x=df_chart['날짜'], y=df_chart['MA20'], mode='lines', line=dict(color='#cc00ff', width=2.5), name="20일선(생명선)"))
                
                # 거래량
                colors = ['#ff4b4b' if df_chart['종가'].iloc[i] >= df_chart['시가'].iloc[i] else '#0068c9' for i in range(len(df_chart))]
                fig.add_trace(go.Bar(x=df_chart['날짜'], y=df_chart['거래량'], name="거래량", marker_color=colors, opacity=0.5, yaxis='y2'))
                
                fig.update_layout(
                    height=500, template="plotly_dark",
                    xaxis=dict(rangeslider=dict(visible=False), type='category'), # 주말 공백 제거
                    yaxis=dict(side='right', domain=[0.3, 1]),
                    yaxis2=dict(side='right', domain=[0, 0.2], showgrid=False),
                    hovermode="x unified", margin=dict(l=10, r=40, t=10, b=10)
                )
                st.plotly_chart(fig, use_container_width=True)
else:
    st.error("네이버 데이터를 불러오지 못했습니다. 통신 상태를 확인해주세요.")
