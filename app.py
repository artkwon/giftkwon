# Streamlit 기반 Coupang Wing 판매정보 크롤러
import os
import json
import datetime
import time
import io

import streamlit as st
import pandas as pd
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 설정 파일 (서버 내 저장) 경로
CONFIG_FILE = 'config.json'


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_config(cfg: dict):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f)


def login_wing(driver, username: str, password: str):
    driver.get("https://wing.coupang.com/")
    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input#username")))
    driver.find_element(By.CSS_SELECTOR, "input#username").send_keys(username)
    driver.find_element(By.CSS_SELECTOR, "input#password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "input#kc-login").click()
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "nav#wing-side-menu")))


def parse_metrics(driver):
    data = {}
    selectors = {
        '방문자': "visitor",
        '조회': "page-view",
        '구매전환율': "conversion",
        '장바구니': "add-to-cart",
        '주문': "order",
        '판매량': "unit-sold",
        '매출(원)': "gmv",
    }
    for key, cls in selectors.items():
        try:
            data[key] = driver.find_element(
                By.XPATH, f"//div[contains(@class,'{cls}')]//span[1]"
            ).text
        except:
            data[key] = ''
    return data


def crawl_data(username, password, option_id, start_date, end_date):
    # 설정 저장
    save_config({'username': username, 'password': password})
    
    # 날짜 리스트
    dates = []
    cur = start_date
    while cur <= end_date:
        dates.append(cur)
        cur += datetime.timedelta(days=1)

    # 브라우저 설정 (헤드리스)
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox") # 샌드박스 비활성화 (컨테이너 환경에서 필수)
    options.add_argument("--disable-dev-shm-usage") # /dev/shm 사용 비활성화 (메모리 문제 방지)
    options.binary_location = "/usr/bin/chromium-browser" # Streamlit Cloud 환경의 일반적인 Chromium 경로
    driver = uc.Chrome(options=options)

    # 로그인
    login_wing(driver, username, password)

    records = []
    for d in dates:
        ts = int(datetime.datetime.combine(d, datetime.time.min).timestamp() * 1000)
        url = (
            f"https://wing.coupang.com/tenants/business-insight/"
            f"sales-analysis/vendor-item-summary"
            f"?vendorItemId={option_id}"
            f"&startDate={ts}&endDate={ts}"
        )
        driver.get(url)
        time.sleep(2)
        metrics = parse_metrics(driver)
        metrics['날짜'] = d.strftime('%Y-%m-%d')
        records.append(metrics)

    driver.quit()

    # DataFrame 생성
    df = pd.DataFrame(records, columns=[
        '날짜','방문자','조회','구매전환율','장바구니','주문','판매량','매출(원)'
    ])

    # 증감율 계산 및 원본 데이터에 추가
    for col in df.columns[1:]: # '날짜' 컬럼을 제외한 나머지 컬럼에 대해 처리
        # 원본 데이터는 문자열이므로 숫자로 변환 가능한 형태로 전처리
        raw_cleaned = df[col].astype(str).str.replace(',', '').str.replace('%','')
        # 숫자로 변환할 수 없는 값은 NaN으로 만듭니다 (예: 빈 문자열)
        numeric_data = pd.to_numeric(raw_cleaned, errors='coerce')

        # 전일 대비 증감율 계산 (NaN은 0으로 처리)
        pct_change = numeric_data.pct_change().fillna(0)

        # 각 셀에 원본 값과 증감율을 함께 표시하는 문자열 생성
        # (▲증가율%) 또는 (▼감소율%) 형식
        new_col_values = []
        for i in range(len(df)):
            original_value = df.at[i, col]
            change_value = pct_change.iloc[i]

            if i == 0: # 첫 번째 행은 전일 대비 증감율이 없으므로 원본 값만 표시
                new_col_values.append(str(original_value))
            else:
                if pd.isna(original_value) or pd.isna(change_value): # 값이 NaN인 경우
                    new_col_values.append(str(original_value)) # 원본 값만 표시
                else:
                    if change_value >= 0:
                        change_text = f" (▲{change_value:.0%})" # 양수 또는 0일 경우
                    else:
                        change_text = f" (▼{change_value:.0%})" # 음수일 경우
                    new_col_values.append(f"{original_value}{change_text}")
        
        df[col] = new_col_values # 기존 컬럼을 증감율이 포함된 문자열로 업데이트

    return df

# --- Streamlit UI ---
st.set_page_config(page_title="Coupang Wing 크롤러", layout='wide')
st.title("🚀 Coupang Wing 판매정보 크롤러")

cfg = load_config()
username = st.text_input("아이디", value=cfg.get('username', ''), type="default")
password = st.text_input("비밀번호", value=cfg.get('password', ''), type="password")
option_id = st.text_input("옵션 ID")

col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input(
        "분석 시작일",
        value=datetime.date.today() - datetime.timedelta(days=7)
    )
with col2:
    end_date = st.date_input("분석 종료일", value=datetime.date.today())

if st.button("데이터 크롤링 시작"):
    with st.spinner("크롤링 중... 잠시만 기다려 주세요."):
        df = crawl_data(
            username, password, option_id,
            start_date, end_date
        )
    st.success("데이터 수집 완료!")
    
    # Styler를 사용하여 증감율에 따른 색상 적용
    # st.dataframe은 셀 안에 직접 색을 넣는 기능을 제한적으로 지원하므로,
    # HTML로 직접 렌더링하는 대신, Streamlit의 기본 dataframe 기능을 활용하면서
    # 증감율을 문자열로 통합하는 방식으로 처리했습니다.
    # 만약 색상 구분이 필요하다면, Streamlit 대신 st.markdown(df.to_html()) 방식이나
    # 보다 복잡한 커스텀 컴포넌트를 고려해야 합니다.
    st.dataframe(df)

    # Excel 다운로드
    # df에 이미 증감율 텍스트가 포함되어 있으므로, 그대로 excel로 저장됩니다.
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    buffer.seek(0)
    st.download_button(
        label="엑셀 다운로드",
        data=buffer,
        file_name=f"sales_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# 파일 저장 안내
st.info("이 스크립트를 'app.py'로 저장한 후, 터미널에서 'streamlit run app.py'를 실행하세요.")
