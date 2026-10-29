import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# -------------------------------------------------------------------
# 1. 기본 설정 및 API 키 정의
# -------------------------------------------------------------------
st.set_page_config(
    page_title="태양광-ESS 전력 수급 시뮬레이터",
    page_icon="☀️",
    layout="wide"
)

# 발급받으신 기상청 공공데이터 API 키 적용
API_KEY = "bef4e395ec061a6a0aa3e92a38af699d2fe16f3921787d2fc1b57d5bda732639"

# 한국전력 통계 기준 24시간 일반 가정 전력 소비량 모델 (단위: kWh)
# (새벽 저소비 -> 아침 피크 -> 낮 완만 -> 저녁 귀가 피크)
HOURLY_CONSUMPTION_MODEL = [
    0.3, 0.25, 0.2, 0.2, 0.2, 0.25, 
    0.4, 0.8,  0.9, 0.5, 0.4, 0.4,  
    0.4, 0.45, 0.4, 0.5, 0.6, 0.8,  
    1.2, 1.4,  1.3, 1.1, 0.7, 0.4   
]

# -------------------------------------------------------------------
# 2. 공공데이터 API 연동 함수 (기상청 일사량 수집)
# -------------------------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_solar_radiation_data(target_date, stn_id="108"):
    """
    기상청 ASOS 시간자료 조회 API를 통해 지정된 날짜의 일사량(icsr) 데이터를 수집합니다.
    """
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
        'stnIds': stn_id  # 108: 서울/경기 관측소 기준
    }
    
    try:
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            items = data['response']['body']['items']['item']
            
            radiation_list = []
            for item in items:
                # 일사량(icsr) 값이 없거나 None인 경우 0.0으로 예외 처리
                val = item.get('icsr')
                radiation = float(val) if val and val.strip() else 0.0
                radiation_list.append(radiation)
                
            if len(radiation_list) == 24:
                return radiation_list, True
    except Exception as e:
        pass
    
    # API 호출 실패 시 백업용 맑은 날 일사량 표준 패턴 반환 (예외 처리)
    fallback_radiation = [
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.1, 0.5, 1.2, 1.8, 2.3, 2.5,
        2.6, 2.4, 2.0, 1.4, 0.7, 0.2,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    ]
    return fallback_radiation, False

# -------------------------------------------------------------------
# 3. ESS 시뮬레이션 핵심 연산 알고리즘
# -------------------------------------------------------------------
def run_ess_simulation(generation, consumption, ess_capacity, ess_efficiency):
    eff_factor = ess_efficiency / 100.0
    soc = 0.0  # 초기 배터리 잔량 (kWh)
    
    soc_history = []
    grid_buy_no_ess = []
    grid_buy_with_ess = []
    
    for gen, con in zip(generation, consumption):
        # 1) ESS 미사용 시 외부 전력 구매량
        grid_no_ess = max(0.0, con - gen)
        grid_buy_no_ess.append(grid_no_ess)
        
        # 2) ESS 사용 시 충·방전 매커니즘
        diff = gen - con
        
        if diff > 0:  # 잉여 전력 발생 -> ESS 충전
            charge_amount = diff * eff_factor
            soc = min(ess_capacity, soc + charge_amount)
            grid_with_ess = 0.0
        else:         # 전력 부족 발생 -> ESS 방전 후 부족분 외부 구매
            needed = abs(diff)
            discharge_possible = soc * eff_factor
            
            if discharge_possible >= needed:
                soc -= (needed / eff_factor)
                grid_with_ess = 0.0
            else:
                remaining_need = needed - discharge_possible
                soc = 0.0
                grid_with_ess = remaining_need
                
        soc_history.append(round(soc, 2))
        grid_buy_with_ess.append(round(grid_with_ess, 2))
        
    return soc_history, grid_buy_no_ess, grid_buy_with_ess

# -------------------------------------------------------------------
# 4. Streamlit UI 구성
# -------------------------------------------------------------------
st.title("☀️ 태양광 발전 및 ESS 전력 수급 시뮬레이터")
st.markdown("기상청 **공공데이터 API** 일사량 데이터를 기반으로 가정용 ESS 도입에 따른 **외부 전력 구매 절감 효과**를 정량 분석합니다.")

# 사이드바: 조건 설정
st.sidebar.header("⚙️ 시뮬레이션 환경 설정")

# 조회 날짜 선택 (기본값: 어제 날짜)
yesterday = datetime.now() - timedelta(days=1)
selected_date = st.sidebar.date_input("조회 날짜 선택", yesterday).strftime("%Y%m%d")

# 태양광 패널 사양
st.sidebar.subheader("1. 태양광 패널 설정")
panel_area = st.sidebar.slider("패널 면적 (m²)", 5, 50, 20)
panel_efficiency = st.sidebar.slider("패널 변환 효율 (%)", 10, 25, 18)

# ESS 사양
st.sidebar.subheader("2. ESS(배터리) 설정")
ess_cap = st.sidebar.slider("ESS 저장 용량 (kWh)", 0, 30, 10)
ess_eff = st.sidebar.slider("ESS 충·방전 효율 (%)", 50, 100, 90)

# --- 데이터 수집 및 가공 ---
raw_radiation, is_api_success = fetch_solar_radiation_data(selected_date)

# API 성공 여부 배지 표시
if is_api_success:
    st.success(f"✅ 기상청 공공데이터 API 연동 성공 (조회일: {selected_date})")
else:
    st.warning("⚠️ API 연동 시도 후 백업 데이터로 전환되었습니다.")

# 일사량 -> 태양광 발전량 변환 공식 (kWh)
# 발전량 = 일사량(MJ/m² 또는 W/m² 연산) * 면적 * 효율
generation_data = [round(r * panel_area * (panel_efficiency / 100.0), 2) for r in raw_radiation]
consumption_data = HOURLY_CONSUMPTION_MODEL

# 시뮬레이션 실행
soc_list, buy_no_ess, buy_with_ess = run_ess_simulation(
    generation_data, consumption_data, ess_cap, ess_eff
)

# --- 결과 요약 메트릭 ---
total_gen = sum(generation_data)
total_con = sum(consumption_data)
total_buy_no_ess = sum(buy_no_ess)
total_buy_with_ess = sum(buy_with_ess)
saved_energy = total_buy_no_ess - total_buy_with_ess
save_ratio = (saved_energy / total_buy_no_ess * 100) if total_buy_no_ess > 0 else 0.0

st.markdown("---")
col1, col2, col3, col4 = st.columns(4)
col1.metric("총 태양광 발전량", f"{total_gen:.2f} kWh")
col2.metric("총 전력 소비량", f"{total_con:.2f} kWh")
col3.metric("ESS 도입 후 외부 구매량", f"{total_buy_with_ess:.2f} kWh")
col4.metric("외부 전력 절감률", f"{save_ratio:.1f} %", delta=f"-{saved_energy:.2f} kWh")

# --- 시각화 그래프 ---
st.markdown("---")
st.subheader("📊 24시간 전력 수급 및 ESS 충·방전 추이")

# Matplotlib 한글 폰트 및 스타일 설정
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

hours = list(range(24))

# Line Chart: 발전량, 소비량, ESS 잔량
ax1.plot(hours, generation_data, label='Solar Gen (kWh)', color='orange', linewidth=2, marker='o')
ax1.plot(hours, consumption_data, label='Home Con (kWh)', color='red', linestyle='--', linewidth=2)
ax1.plot(hours, soc_list, label='ESS SoC (kWh)', color='green', linewidth=2, linestyle=':')
ax1.set_ylabel('Energy (kWh)')
ax1.set_title('Hourly Power Flow & ESS Storage State (SoC)')
ax1.legend()
ax1.grid(True, alpha=0.3)

# Bar Chart: ESS 미사용 vs 사용 시 외부 전력 구매량 비교
width = 0.35
ax2.bar([h - width/2 for h in hours], buy_no_ess, width, label='Grid Buy (Without ESS)', color='gray', alpha=0.6)
ax2.bar([h + width/2 for h in hours], buy_with_ess, width, label='Grid Buy (With ESS)', color='blue', alpha=0.7)
ax2.set_xlabel('Hour of Day (00:00 ~ 23:00)')
ax2.set_ylabel('Grid Buy (kWh)')
ax2.set_title('Comparison of External Power Dependency')
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()
st.pyplot(fig)

# --- 상세 데이터 테이블 ---
with st.expander("📄 시간대별 상세 수치 데이터 보기"):
    df = pd.DataFrame({
        '시간(시)': hours,
        '일사량': raw_radiation,
        '발전량(kWh)': generation_data,
        '소비량(kWh)': consumption_data,
        'ESS잔량(kWh)': soc_list,
        '구매량_ESS미사용(kWh)': buy_no_ess,
        '구매량_ESS사용(kWh)': buy_with_ess
    })
    st.dataframe(df, use_container_width=True)
