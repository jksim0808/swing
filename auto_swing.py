import os
import pandas as pd
import numpy as np
import requests
import io
from datetime import datetime, timedelta, timezone
import FinanceDataReader as fdr
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))

def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}
    try:
        requests.post(url, json=payload)
    except:
        pass

def get_krx_info():
    df = fdr.StockListing('KRX')
    return df[['Name', 'Code', 'Marcap']].set_index('Name')

def get_naver_top_universe():
    headers = {'User-Agent': 'Mozilla/5.0'}
    krx_info = get_krx_info()
    df_list = []
    
    for sosok in [0, 1]:
        url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
        try:
            res = requests.get(url, headers=headers)
            res.encoding = 'euc-kr'
            dfs = pd.read_html(io.StringIO(res.text))
            df = dfs[1].dropna(how='all') 
            df = df[['종목명', '현재가', '등락률', '거래대금']]
            df_list.append(df)
        except: continue
            
    if not df_list: return pd.DataFrame()
        
    full_df = pd.concat(df_list, ignore_index=True)
    for col in ['현재가', '거래대금']:
        full_df[col] = pd.to_numeric(full_df[col].astype(str).str.replace(',', ''), errors='coerce')
    
    pattern = '|'.join(['KODEX', 'TIGER', 'KBSTAR', 'ACE', 'ARIRANG', 'HANARO', 'KOSEF', 'SOL', 'TIMEFOLIO', 'WOORI', '스팩', 'ETN', '제\d+호', '우$'])
    full_df = full_df[~full_df['종목명'].str.contains(pattern, case=False, regex=True)]
    
    full_df = full_df[full_df['현재가'] >= 10000]
    full_df['종목코드'] = full_df['종목명'].map(krx_info['Code'])
    full_df['시가총액'] = full_df['종목명'].map(krx_info['Marcap'])
    full_df = full_df.dropna(subset=['종목코드', '시가총액'])
    full_df = full_df[full_df['시가총액'] >= 100000000000]
    
    return full_df.sort_values(by='거래대금', ascending=False).head(100).reset_index(drop=True)

def get_fundamentals_and_news(code):
    headers = {'User-Agent': 'Mozilla/5.0'}
    news_status = "☁️ 보통"
    try:
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
    return news_status

def analyze_swing_probability(ticker, days=60):
    end_date = datetime.now(KST)
    start_date = end_date - timedelta(days=days)
    try:
        df = fdr.DataReader(ticker, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        if len(df) < 20: return 0, "관망", 0, 0
        
        df = df.reset_index()
        df.rename(columns={'Open': '시가', 'High': '고가', 'Close': '종가', 'Volume': '거래량'}, inplace=True)
        
        df['Vol_MA5'] = df['거래량'].rolling(window=5).mean()
        df['MA20'] = df['종가'].rolling(window=20).mean()
        
        current_price = df['종가'].iloc[-1]
        current_vol = df['거래량'].iloc[-1]
        ma20 = df['MA20'].iloc[-1]
        highest_price = df['고가'].max()
        target_yield = ((highest_price - current_price) / current_price) * 100
        
        df['is_bull'] = (df['종가'] > df['시가'] * 1.05) & (df['거래량'] > df['Vol_MA5'].shift(1) * 3)
        recent_bull = df.iloc[-20:][df.iloc[-20:]['is_bull'] == True]
        
        if not recent_bull.empty:
            if ma20 * 0.98 <= current_price <= ma20 * 1.05 and current_vol < df['Vol_MA5'].iloc[-2] * 0.6:
                return 85, "🎯 S급 눌림목", highest_price, target_yield
    except: pass
    return 0, "관망", 0, 0

if __name__ == "__main__":
    # GitHub Secrets에서 보안 값 불러오기
    BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not BOT_TOKEN or not CHAT_ID:
        print("Error: 토큰이나 챗 아이디가 없습니다.")
        exit()

    universe_df = get_naver_top_universe()
    s_class_results = []
    
    if not universe_df.empty:
        for i, row in universe_df.iterrows():
            code, name = row['종목코드'], row['종목명']
            score, status, high_price, target_yield = analyze_swing_probability(code)
            
            if status == "🎯 S급 눌림목":
                news_status = get_fundamentals_and_news(code)
                s_class_results.append({
                    "종목명": name, "현재가": row['현재가'], 
                    "목표가": high_price, "기대수익": target_yield, "뉴스": news_status
                })
                
    if not s_class_results:
        msg = f"📊 [AI 스윙 스캐너 정기 리포트]\n\n({datetime.now(KST).strftime('%m월 %d일 %H:%M')})\n오늘은 완벽한 'S급 눌림목' 조건에 부합하는 우량주가 없습니다. 현금을 지키며 관망을 추천합니다."
    else:
        msg = f"🎯 [S급 눌림목 발견!] ({datetime.now(KST).strftime('%m월 %d일 %H:%M')})\n\n"
        for res in s_class_results:
            msg += f"🔥 <b>{res['종목명']}</b>\n"
            msg += f"• 현재가: {int(res['현재가']):,}원\n"
            msg += f"• 목표가: {int(res['목표가']):,}원 (+{res['기대수익']:.1f}%)\n"
            msg += f"• 뉴스분위기: {res['뉴스']}\n\n"
            
    send_telegram_message(BOT_TOKEN, CHAT_ID, msg)
    print("텔레그램 발송 완료!")
