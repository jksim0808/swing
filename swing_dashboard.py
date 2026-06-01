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
    st.error("데이터를 수집하지 못했습니다. 라이브러리(pykrx, FinanceDataReader) 설치 상태를 확인해주세요.")import os
from dotenv import load_dotenv
import time
import datetime
import pyperclip
import sys
import json
import random

# 💡 [핵심 변경] 새로운 구글 GenAI 라이브러리 임포트
from google import genai
from google.genai import types

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import undetected_chromedriver as uc

# .env 파일에서 정보 불러오기
load_dotenv()
NID = os.getenv("NAVER_ID")
NPW = os.getenv("NAVER_PW")
BLOG_ID = os.getenv("BLOG_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

is_mac = sys.platform == 'darwin'
CMD_CTRL = Keys.COMMAND if is_mac else Keys.CONTROL


def log(msg):
    """콘솔창에 시간을 포함하여 예쁘게 로그를 찍어주는 함수"""
    now = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    print(f"[{now}] {msg}")


def get_top_10_topics():
    """10개의 핫이슈 주제를 뽑아오는 함수 (신규 패키지 적용 완료)"""
    log("🔍 제미나이에게 오늘의 핫이슈 10가지를 물어봅니다...")
    
    # 💡 신규 패키지 방식: Client 객체 생성
    client = genai.Client(api_key=GEMINI_KEY)

    prompt = """
    오늘 네이버 및 sns에서 가장 비중 있게 다루는 최신 경제/주식/생활/정책 관련 이슈 10가지를 선정해.
    블로그 포스팅 제목으로 쓸 수 있는 명확한 한 줄 문장으로 만들어줘.
    반드시 다음과 같은 JSON 스트링 배열 형식으로만 대답해: ["주제1", "주제2", "주제3"]
    """

    for attempt in range(3):
        try:
            # 💡 신규 패키지 방식: generate_content 메서드 호출 및 config 적용
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            return json.loads(response.text.strip())
            
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "Quota" in error_msg:
                log(f"⏳ 구글 AI 호출 속도 제한(429) 걸림! 30초 휴식 후 재시도... ({attempt + 1}/3)")
                time.sleep(30)
            else:
                log(f"⚠️ 이슈 추출 실패. 5초 뒤 재시도... ({attempt + 1}/3)")
                time.sleep(5)

    return [f"오늘의 추천 트렌드 키워드 {i}" for i in range(1, 11)]


def get_gemini_content(topic):
    """각 주제별로 블로그 본문을 작성하는 함수 (신규 패키지 적용 완료)"""
    client = genai.Client(api_key=GEMINI_KEY)

    prompt = f"""
    '{topic}'에 대한 정보성 네이버 블로그 포스팅을 작성해줘.

    ★경고★: 마크다운 기호(###, **, * 등)나 HTML 태그를 절대 사용하지 마세요!
    대신 아래의 [본문 작성 예시]에 있는 기호(■, ▶), 번호(1., 2.), 그리고 '빈 줄(줄바꿈)' 형식을 완벽하게 똑같이 모방해서 가독성 좋게 작성해.

    [본문 작성 예시]
    ■ {topic}, 왜 주목받고 있을까요?
    여기에 관련된 서론이나 배경 설명을 2~3문장의 줄글로 자연스럽게 작성합니다. 기호 없이 순수 텍스트로만 씁니다.

    ▶ 핵심 쟁점 및 포인트
    1. 첫 번째 소주제 요약: 첫 번째 항목에 대한 상세한 설명과 분석을 적습니다.

    2. 두 번째 소주제 요약: 두 번째 항목에 대한 상세한 설명과 분석을 적습니다. (각 번호 항목 사이에는 반드시 빈 줄을 넣어주세요)

    3. 세 번째 소주제 요약: 세 번째 항목에 대한 상세한 설명과 분석을 적습니다.

    ■ 향후 전망 및 결론
    앞으로의 전망이나 해결책 등을 다시 줄글 형식으로 깔끔하게 마무리합니다.

    ---------------------------
    반드시 제시하는 키(title, body, tags)를 가진 JSON 오브젝트 형식으로만 대답해.
    🚨 [태그 작성 규칙]: 'tags' 배열 안의 키워드는 띄어쓰기나 특수문자(#, ?, ! 등)를 절대 포함하지 말고, 오직 '명사형 단어(한글/영문/숫자)'로만 3~5개 작성해.

    {{
        "title": "클릭을 유도하는 매력적인 블로그 글 제목",
        "body": "위 예시와 완벽히 동일한 서식으로 작성된 본문 텍스트",
        "tags": ["키워드1", "키워드2", "키워드3"]
    }}
    """

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            return json.loads(response.text.strip())
            
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "Quota" in error_msg:
                log(f"⏳ 구글 AI 호출 속도 제한(429) 걸림! 20초 휴식 후 재시도... ({attempt + 1}/3)")
                time.sleep(20)
            else:
                log(f"⚠️ AI 양식 오류 발생. 5초 뒤 재시도... ({attempt + 1}/3)")
                time.sleep(5)

    raise Exception("AI가 계속해서 응답하지 않거나 요금제 제한에 걸렸습니다.")


def login_naver(driver):
    """네이버에 1회만 로그인하는 함수"""
    log("🔑 네이버 로그인을 시도합니다...")
    driver.get("https://nid.naver.com/nidlogin.login")
    time.sleep(2)
    driver.find_element(By.ID, "id").click()
    pyperclip.copy(NID)
    driver.switch_to.active_element.send_keys(CMD_CTRL, 'v')
    time.sleep(1)
    driver.find_element(By.ID, "pw").click()
    pyperclip.copy(NPW)
    driver.switch_to.active_element.send_keys(CMD_CTRL, 'v')
    time.sleep(1)
    driver.find_element(By.ID, "log.login").click()
    time.sleep(4)
    log("✅ 네이버 로그인 완료!")


def post_single_article(driver, topic):
    """유지된 브라우저(driver)를 활용해 글 1개를 발행하는 함수"""
    try:
        log(f"📝 '{topic[:15]}...' 원고 작성 중...")
        post_data = get_gemini_content(topic)

        driver.get(f"https://blog.naver.com/{BLOG_ID}?Redirect=Write")
        time.sleep(6)

        try:
            driver.switch_to.alert.accept()
            time.sleep(1)
        except:
            pass

        driver.switch_to.default_content()
        WebDriverWait(driver, 15).until(EC.frame_to_be_available_and_switch_to_it("mainFrame"))
        time.sleep(3)

        try:
            driver.find_element(By.CSS_SELECTOR, ".se-popup-button.se-popup-button-cancel").click()
            time.sleep(1)
        except:
            pass
        try:
            driver.find_element(By.CSS_SELECTOR, ".se-help-panel-close-button").click()
            time.sleep(1)
        except:
            pass

        log("✍️ 에디터가 완전히 로딩될 때까지 5초간 넉넉히 대기합니다...")
        time.sleep(5)

        log("✍️ 화면에서 '제목' 입력칸을 강제로 찾아냅니다...")
        try:
            title_element = driver.find_element(By.XPATH, "//*[contains(@class, 'se-title')]//*[contains(text(), '제목') or contains(@placeholder, '제목')]")
        except:
            title_element = driver.find_element(By.CSS_SELECTOR, ".se-title-text, .se-document-title")

        ActionChains(driver).move_to_element(title_element).double_click().perform()
        time.sleep(1.5)

        pyperclip.copy(post_data['title'])
        ActionChains(driver).key_down(CMD_CTRL).send_keys('v').key_up(CMD_CTRL).perform()
        time.sleep(2)

        log("✍️ 엔터키를 사용하여 본문 영역으로 강제 진입합니다...")
        active_elem = driver.switch_to.active_element
        active_elem.send_keys(Keys.ENTER)
        time.sleep(2)

        pyperclip.copy(post_data['body'])
        ActionChains(driver).key_down(CMD_CTRL).send_keys('v').key_up(CMD_CTRL).perform()

        wait_time = round(random.uniform(15.0, 25.0), 1)
        log(f"⏳ 봇 탐지 회피: {wait_time}초간 글을 검토하는 척 대기합니다...")
        time.sleep(wait_time)

        publish_top_btn = WebDriverWait(driver, 10).until(EC.presence_of_element_located(
            (By.XPATH, "//*[(self::button or self::a) and contains(., '발행') and not(contains(., '예약'))]")))
        driver.execute_script("arguments[0].click();", publish_top_btn)
        time.sleep(3)

        try:
            tag_input = driver.find_element(By.CSS_SELECTOR, "input[placeholder*='태그'], textarea[placeholder*='태그']")
            for tag in post_data.get('tags', []):
                clean_tag = tag.replace(' ', '').replace('#', '')
                if clean_tag: 
                    tag_input.send_keys(clean_tag, Keys.ENTER)
                    time.sleep(0.5)
        except:
            pass

        publish_btns = driver.find_elements(By.XPATH, "//*[(self::button or self::a) and contains(., '발행') and not(contains(., '예약'))]")
        final_btn = next((btn for btn in reversed(publish_btns) if btn.is_displayed()), None)

        if final_btn:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", final_btn)
            time.sleep(2)
            ActionChains(driver).move_to_element(final_btn).click().perform()
        else:
            raise Exception("발행 버튼을 찾을 수 없습니다.")

        time.sleep(10)
        log("🎉 포스팅 성공!")
        return True

    except Exception as e:
        log(f"❌ 포스팅 실패: {e}")
        return False


def run_daily_job():
    """크롬을 한 번만 켜서 로그인을 유지한 채 10개를 작성하는 엔진"""
    log("==================================================")
    log("⏰ 오늘의 블로그 자동 포스팅을 시작합니다.")
    log("==================================================")

    topics = get_top_10_topics()
    success_count = 0

    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument("--window-size=1920,1080")

    driver = uc.Chrome(options=chrome_options, version_main=148)

    try:
        login_naver(driver)
        
        for index, topic in enumerate(topics):
            log(f"▶ [{index + 1}/{len(topics)}] 작업 시작: {topic[:20]}...")
            
            is_success = post_single_article(driver, topic)
            if is_success: 
                success_count += 1

            if index < len(topics) - 1:
                sleep_time = random.randint(300, 420)
                log(f"💤 네이버 스팸 필터 회피를 위해 {sleep_time}초 대기합니다...")
                time.sleep(sleep_time)
                
    finally:
        log("🧹 모든 작업을 마치고 브라우저를 닫습니다.")
        try:
            driver.quit()
        except:
            pass

    log(f"✅ 오늘의 미션 완료! 총 {success_count}개의 포스팅을 발행했습니다. 내일 다시 뵙겠습니다!")


if __name__ == "__main__":
    if not all([NID, NPW, BLOG_ID, GEMINI_KEY]):
        log("❌ 에러: .env 파일에 아이디, 비밀번호, API 키를 모두 입력해주세요.")
        sys.exit()

    log("🟢 블로그 자동화 봇이 가동되었습니다.")
    log("▶️ 프로그램을 켜셨으므로, 대기하지 않고 즉시 작업을 시작합니다!")

    run_daily_job()

    log("==================================================")
    log("⏳ 즉시 포스팅 작업이 모두 완료되었습니다.")
    log("💤 이제 봇은 수면 모드에 들어갑니다. 내일부터는 매일 [오전 08:00]에 알아서 작동합니다.")
    log("==================================================")

    while True:
        now = datetime.datetime.now()
        if now.hour == 8 and now.minute == 0:
            run_daily_job()
            time.sleep(3600)
        else:
            time.sleep(30)
