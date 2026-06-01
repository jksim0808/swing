import os
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
