import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# -------------------------------------------------------------------
# 1. 페이지 설정 및 API 키
# -------------------------------------------------------------------
st.set_page_config(
    page_title="스마트 태양광-ESS 에너지 시뮬레이터",
    page_icon="☀️",
    layout="wide"
)

# 발급받으신 기상청 공공데이터 API 키
API_KEY = "bef4e395ec061a6a0aa3e92a38af699d2fe16f3921787d2fc1b57d5bda732639"

# 한국전력 통계 기준 24시간 일반 가정 전력 소비량 모델 (kWh)
HOURLY_CONSUMPTION_MODEL = [
    0.3, 0.25, 0.2, 0.2, 0.2, 0.25, 
    0.4, 0.8,  0.9, 0.5, 0.4, 0.4,  
    0.4, 0.45, 0.4, 0.5, 0.6, 0.8,  
    1.2, 1.4,  1.3, 1.1, 0.7, 0.4   
]

# -------------------------------------------------------------------
# 2. 공공데이터 API 연동 (기상청 일사량 수집)
# -------------------------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_solar_data(target_date):
    url = "http://apis.data.go.kr/1360000/AsosHourlyInfoService/getWthrDataList"
    params = {
        'serviceKey': API_KEY,
        'pageNo': '1',
        'numOfRows': '24',
        'dataType': 'JSON',
        'dataCd': 'ASOS',
        'dateCd': 'HR',
        'startDt': target_date,
        'startH': '00',
        'endDt': target_date,
        'endH': '23',
        'stnIds': '108' # 서울/경기 관측소 기준
    }
    try:
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            items = response.json()['response']['body']['items']['item']
            rad_list = [float(item.get('icsr', 0) or 0) for item in items]
            if len(rad_list) == 24:
                return rad_list, True
    except Exception:
        pass
    
    # 예외 처리용 백업 표준 일사량 데이터
    return [0, 0, 0, 0, 0, 0, 0.1, 0.5, 1.2, 1.8, 2.3, 2.5, 2.6, 2.4, 2.0, 1.4, 0.7, 0.2, 0, 0, 0, 0, 0, 0], False

# -------------------------------------------------------------------
# 3. ESS 시뮬레이션 핵심 연산 알고리즘
# -------------------------------------------------------------------
def run_ess_sim(generation, consumption, capacity, efficiency):
    eff = efficiency / 100.0
    soc = 0.0
    soc_history = []
    grid_no_ess = []
    grid_with_ess = []
    
    for gen, con in zip(generation, consumption):
        # ESS 미사용 시 외부 구매량
        grid_no_ess.append(max(0.0, con - gen))
        
        # ESS 사용 시 충·방전 연산
        diff = gen - con
        if diff > 0:  # 잉여 전력 발생 -> ESS 충전
            charge = diff * eff
            soc = min(capacity, soc + charge)
            grid_with_ess.append(0.0)
        else:         # 전력 부족 발생 -> ESS 방전
            need = abs(diff)
            discharge_limit = soc * eff
            if discharge_limit >= need:
                soc -= (need / eff)
                grid_with_ess.append(0.0)
            else:
                rem = need - discharge_limit
                soc = 0.0
                grid_with_ess.append(rem)
                
        soc_history.append(round(soc, 2))
        
    return soc_history, grid_no_ess, grid_with_ess

# -------------------------------------------------------------------
# 4. Streamlit 화면 구성 (웹UI & 폰트 안 깨지는 영문 차트)
# -------------------------------------------------------------------
st.title("☀️ 가정용 태양광-ESS 에너지 효율 시뮬레이터")
st.markdown("기상청 **실시간 일사량 API 데이터**를 활용해, 배터리(ESS) 설치 후 **우리 집 외부 전력 구매량이 얼마나 줄어드는지** 한눈에 비교해보세요.")

# 사이드바 설정
st.sidebar.header("⚙️ 시뮬레이션 조건 설정")
yesterday = datetime.now() - timedelta(days=1)
selected_date = st.sidebar.
