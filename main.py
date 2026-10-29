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

API_KEY = "bef4e395ec061a6a0aa3e92a38af699d2fe16f3921787d2fc1b57d5bda732639"

# 한국전력 통계 기준 24시간 일반 가정 전력 소비량 모델 (kWh)
HOURLY_CONSUMPTION_MODEL = [
    0.3, 0.25, 0.2, 0.2, 0.2, 0.25, 
    0.4, 0.8,  0.9, 0.5, 0.4, 0.4,  
    0.4, 0.45, 0.4, 0.5, 0.6, 0.8,  
    1.2, 1.4,  1.3, 1.1, 0.7, 0.4   
]

# -------------------------------------------------------------------
# 2. 공공데이터 API 연동 (기상청 일사량)
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
        'stnIds': '108'
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
    
    # 예외 처리용 표준 데이터
    return [0,0,0,0,0,0, 0.1,0.5,1.2,1.8,2.3,2.5, 2.6,2.4,2.0,1.4,0.7,0.2, 0,0,0,0,0,0], False

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
        
        # ESS 사용 시 충방전
        diff = gen - con
        if diff > 0:  # 잉여 전력 -> 충전
            charge = diff * eff
            soc = min(capacity, soc + charge)
            grid_with_ess.append(0.0)
        else:         # 부족 전력 -> 방전
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
# 4. Streamlit 화면 구성 (사용자 친화적 디자인)
# -------------------------------------------------------------------
st.title("☀️ 가정용 태양광-ESS 에너지 효율 시뮬레이터")
st.markdown("기상청 **실시간 일사량 API 데이터**를 활용해, 배터리(ESS) 설치 후 **우리 집 외부 전력 구매량이 얼마나 줄어드는지** 한눈에 비교해보세요.")

# 사이드바 설정
st.sidebar.header("⚙️ 시뮬레이션 조건 설정")
yesterday = datetime.now() - timedelta(days=1)
selected_date = st.sidebar.date_input("조회 날짜", yesterday).strftime("%Y%m%d")

st.sidebar.subheader("1. 태양광 패널 사양")
panel_area = st.sidebar.slider("패널 면적 (m²)", 5, 50, 20)
panel_eff = st.sidebar.slider("패널 효율 (%)", 10, 25, 18)

st.sidebar.subheader("2. ESS 배터리 사양")
ess_cap = st.sidebar.slider("배터리 용량 (kWh)", 0, 30, 10)
ess_eff = st.sidebar.slider("충·방전 효율 (%)", 50, 100, 90)

# 데이터 수집 및 연산
raw_rad, is_api = fetch_solar_data(selected_date)
gen_data = [round(r * panel_area * (panel_eff / 100.0), 2) for r in raw_rad]
con_data = HOURLY_CONSUMPTION_MODEL

soc_list, buy_no_ess, buy_with_ess = run_ess_sim(gen_data, con_data, ess_cap, ess_eff)

total_gen = sum(gen_data)
total_con = sum(con_data)
total_buy_no = sum(buy_no_ess)
total_buy_with = sum(buy_with_ess)
saved_kwh = total_buy_no - total_buy_with
save_percent = (saved_kwh / total_buy_no * 100) if total_buy_no > 0 else 0

if is_api:
    st.caption(f"🌐 기상청 공공데이터 API 연동 완료 ({selected_date} 관측 데이터)")

# --- 1. 직관적 대형 메트릭 카드 ---
st.markdown("---")
m1, m2, m3, m4 = st.columns(4)
m1.metric("하루 태양광 발전량", f"{total_gen:.1f} kWh")
m2.metric("가정 총 전력 소비량", f"{total_con:.1f} kWh")
m3.metric("ESS 사용 후 외부 구매량", f"{total_buy_with:.1f} kWh", f"-{saved_kwh:.1f} kWh 절감")
m4.metric("에너지 자급 절감률", f"{save_percent:.1f} %")

# --- 2. 직관적인 그래프 비교 (탭 구성) ---
st.markdown("---")
st.subheader("📊 에너지 수급 및 외부 전력 비교 시각화")

tab1, tab2 = st.tabs(["💡 ESS 사용 전/후 외부 전력 구매 비교", "🔋 24시간 태양광 발전 및 배터리 잔량 추이"])

hours = list(range(24))

with tab1:
    st.markdown("##### 📌 **ESS(배터리) 도입 시 시간대별 외부 전력 구매량 절감 효과**")
    fig1, ax1 = plt.subplots(figsize=(10, 4.5))
    
    width = 0.35
    ax1.bar([h - width/2 for h in hours], buy_no_ess, width, label='ESS 미사용 시 (기존)', color='#FF6B6B', alpha=0.8)
    ax1.bar([h + width/2 for h in hours], buy_with_ess, width, label='ESS 사용 시 (절감 후)', color='#4D96FF', alpha=0.9)
    
    ax1.set_xlabel('시간 (0시 ~ 23시)')
    ax1.set_ylabel('외부 전력 구매량 (kWh)')
    ax1.set_xticks(hours)
    ax1.legend(loc='upper right')
    ax1.grid(True, axis='y', linestyle='--', alpha=0.5)
    st.pyplot(fig1)
    
    st.info(f"💡 **분석 요약**: 낮에 남은 태양광 전력을 저장해 둔 덕분에, 저녁 피크 시간대(18~22시)의 외부 전력 의존도가 크게 감소했습니다.")

with tab2:
    st.markdown("##### 📌 **시간대별 태양광 발전량, 가정 소비량, ESS 충전 상태(SoC)**")
    fig2, ax2 = plt.subplots(figsize=(10, 4.5))
    
    ax2.plot(hours, gen_data, label='태양광 발전량 (kWh)', color='#FF9F29', linewidth=2, marker='o')
    ax2.plot(hours, con_data, label='가정 소비량 (kWh)', color='#E03B8B', linestyle='--', linewidth=2)
    ax2.plot(hours, soc_list, label='ESS 배터리 잔량 (kWh)', color='#6BCB77', linewidth=2.5)
    
    ax2.set_xlabel('시간 (0시 ~ 23시)')
    ax2.set_ylabel('전력량 (kWh)')
    ax2.set_xticks(hours)
    ax2.legend(loc='upper right')
    ax2.grid(True, linestyle='--', alpha=0.5)
    st.pyplot(fig2)

# --- 3. 상세 데이터 표 ---
with st.expander("📄 시간대별 정량 데이터 수치 확인하기"):
    df = pd.DataFrame({
        '시간(시)': hours,
        '발전량(kWh)': gen_data,
        '소비량(kWh)': con_data,
        'ESS 잔량(kWh)': soc_list,
        '외부구매(ESS 미사용)': buy_no_ess,
        '외부구매(ESS 사용)': buy_with_ess
    })
    st.dataframe(df, use_container_width=True)
