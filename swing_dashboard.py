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
    
    # 너무 싼 동전주(1
