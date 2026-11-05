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

# 한전 표준 가정 소비 패턴 비율 (합계 1.0)
CONSUMPTION_RATIO = [
    0.021, 0.018, 0.014, 0.014, 0.014, 0.018, 
    0.028, 0.057, 0.064, 0.035, 0.028, 0.028,  
    0.028, 0.032, 0.028, 0.035, 0.043, 0.057,  
    0.085, 0.099, 0.092, 0.078, 0.050, 0.028   
]

# -------------------------------------------------------------------
# 2. 공공데이터 API 연동 (기상청 일사량 수집 및 단위 교정)
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
            # MJ/m2 단위를 float 변환
            rad_list = [float(item.get('icsr', 0) or 0) for item in items]
            if len(rad_list) == 24:
                return rad_list, True
    except Exception:
        pass
    
    # 백업 표준 일사량 데이터 (MJ/m2 단위)
    return [0, 0, 0, 0, 0, 0, 0.2, 0.8, 1.5, 2.2, 2.7, 2.9, 2.8, 2.4, 1.8, 1.1, 0.4, 0.1, 0, 0, 0, 0, 0, 0], False

# -------------------------------------------------------------------
# 3. ESS 시뮬레이션 알고리즘 (2일 연속 연산으로 새벽 이월 반영)
# -------------------------------------------------------------------
def run_ess_sim(generation, consumption, capacity, efficiency, initial_soc=0.0):
    eff = efficiency / 100.0
    
    # 48시간(2일치) 연속 시뮬레이션으로 안정화된 잔량 산출
    gen_48 = generation * 2
    con_48 = consumption * 2
    
    soc = initial_soc
    soc_history_48 = []
    grid_no_ess_48 = []
    grid_with_ess_48 = []
    
    for gen, con in zip(gen_48, con_48):
        grid_no_ess_48.append(max(0.0, con - gen))
        
        diff = gen - con
        if diff > 0:
            charge = diff * eff
            soc = min(capacity, soc + charge)
            grid_with_ess_48.append(0.0)
        else:
            need = abs(diff)
            discharge_limit = soc * eff
            if discharge_limit >= need:
                soc -= (need / eff)
                grid_with_ess_48.append(0.0)
            else:
                rem = need - discharge_limit
                soc = 0.0
                grid_with_ess_48.append(rem)
                
        soc_history_48.append(round(soc, 2))
        
    # 두 번째 24시간(정상 이월 상태) 데이터 추출
    return soc_history_48[24:], grid_no_ess_48[24:], grid_with_ess_48[24:]

# -------------------------------------------------------------------
# 4. Streamlit 화면 구성
# -------------------------------------------------------------------
st.title("☀️ 가정용 태양광-ESS 에너지 효율 시뮬레이터")
st.markdown("기상청 **실시간 일사량 API 데이터**를 활용해, 배터리(ESS) 설치 후 **우리 집 외부 전력 구매량이 얼마나 줄어드는지** 한눈에 비교해보세요.")

st.sidebar.header("⚙️ 시뮬레이션 조건 설정")
yesterday = datetime.now() - timedelta(days=1)
selected_date = st.sidebar.date_input("조회 날짜 선택", yesterday).strftime("%Y%m%d")

st.sidebar.subheader("1. 소비량 및 패널 사양")
daily_con_input = st.sidebar.slider("하루 총 소비량 (kWh)", 5.0, 30.0, 14.0, 0.5)
panel_area = st.sidebar.slider("패널 면적 (m²)", 5, 50, 20)
panel_eff = st.sidebar.slider("패널 변환 효율 (%)", 10, 25, 18)

st.sidebar.subheader("2. ESS 배터리 사양")
ess_cap = st.sidebar.slider("배터리 용량 (kWh)", 0, 30, 10)
ess_eff = st.sidebar.slider("충·방전 효율 (%)", 50, 100, 90)

# 데이터 수집 및 연산
raw_rad, is_api = fetch_solar_data(selected_date)

# [수정] MJ/m2 -> kWh/m2 변환 (1 MJ = 0.27778 kWh)
gen_data = [round((r * 0.27778) * panel_area * (panel_eff / 100.0), 2) for r in raw_rad]
con_data = [round(daily_con_input * ratio, 2) for ratio in CONSUMPTION_RATIO]

soc_list, buy_no_ess, buy_with_ess = run_ess_sim(gen_data, con_data, ess_cap, ess_eff)

total_gen = sum(gen_data)
total_con = sum(con_data)
total_buy_no = sum(buy_no_ess)
total_buy_with = sum(buy_with_ess)
saved_kwh = total_buy_no - total_buy_with
save_percent = (saved_kwh / total_buy_no * 100) if total_buy_no > 0 else 0.0

if is_api:
    st.caption(f"🌐 기상청 공공데이터 API 연동 완료 (조회일자: {selected_date})")

# 메트릭 카드
st.markdown("---")
m1, m2, m3, m4 = st.columns(4)
m1.metric("하루 태양광 발전량", f"{total_gen:.1f} kWh")
m2.metric("가정 총 전력 소비량", f"{total_con:.1f} kWh")
m3.metric("ESS 사용 후 외부 구매량", f"{total_buy_with:.1f} kWh", f"-{saved_kwh:.1f} kWh 절감")
m4.metric("에너지 자급 절감률", f"{save_percent:.1f} %")

# 동적 분석 요약 문구
st.markdown("---")
if ess_cap == 0:
    dynamic_summary = "현재 ESS 용량이 0kWh로 설정되어 배터리 절감 효과가 없습니다."
elif save_percent > 70:
    dynamic_summary = f"현재 {ess_cap}kWh 용량과 {ess_eff}% 효율 설정 시, 외부 전력 의존도가 매우 낮아져 거의 완전한 에너지 자급률({save_percent:.1f}%)을 달성할 수 있습니다."
elif save_percent > 30:
    dynamic_summary = f"현재 {ess_cap}kWh 배터리로 낮 동안 모은 잉여 전력을 저녁/새벽 피크 시간에 활용하여 총 {saved_kwh:.1f}kWh({save_percent:.1f}%)의 외부 구매량을 절감하고 있습니다."
else:
    dynamic_summary = f"배터리 용량({ess_cap}kWh) 대비 발전량이 적거나 소비량이 많아 절감률이 {save_percent:.1f}%에 머물고 있습니다. 패널 면적이나 용량을 조절해 보세요."

st.info(f"💡 **실시간 ESS 역할 분석 의견**: {dynamic_summary}")

# 시각화 탭
st.markdown("---")
st.subheader("📊 에너지 수급 및 용량별 비교 시각화")

tab1, tab2, tab3 = st.tabs([
    "💡 ESS 사용 전/후 외부 전력 구매 비교", 
    "🔋 24시간 발전·소비·배터리 잔량 추이",
    "📈 ESS 용량 변화에 따른 전력 구매량 곡선"
])

hours = list(range(24))

with tab1:
    st.markdown("##### 📌 **ESS 도입 시 시간대별 외부 전력 구매량 절감 효과 (이월 잔량 반영)**")
    fig1, ax1 = plt.subplots(figsize=(10, 4.2))
    
    width = 0.35
    ax1.bar([h - width/2 for h in hours], buy_no_ess, width, label='Without ESS (Baseline)', color='#FF6B6B', alpha=0.8)
    ax1.bar([h + width/2 for h in hours], buy_with_ess, width, label='With ESS (Optimized)', color='#4D96FF', alpha=0.9)
    
    ax1.set_xlabel('Hour of Day (00:00 ~ 23:00)')
    ax1.set_ylabel('Grid Power Purchased (kWh)')
    ax1.set_xticks(hours)
    ax1.legend(loc='upper right')
    ax1.grid(True, axis='y', linestyle='--', alpha=0.5)
    st.pyplot(fig1)

with tab2:
    st.markdown("##### 📌 **시간대별 태양광 발전량, 가정 소비량, ESS 충전 상태(SoC)**")
    fig2, ax2 = plt.subplots(figsize=(10, 4.2))
    
    ax2.plot(hours, gen_data, label='Solar Generation (kWh)', color='#FF9F29', linewidth=2, marker='o')
    ax2.plot(hours, con_data, label='Home Consumption (kWh)', color='#E03B8B', linestyle='--', linewidth=2)
    ax2.plot(hours, soc_list, label='ESS Storage SoC (kWh)', color='#6BCB77', linewidth=2.5)
    
    ax2.set_xlabel('Hour of Day (00:00 ~ 23:00)')
    ax2.set_ylabel('Energy (kWh)')
    ax2.set_xticks(hours)
    ax2.legend(loc='upper right')
    ax2.grid(True, linestyle='--', alpha=0.5)
    st.pyplot(fig2)

with tab3:
    st.markdown("##### 📌 **배터리 용량(0~30 kWh) 변화에 따른 하루 외부 전력 구매량 절감 곡선**")
    
    # 0 ~ 30kWh까지 용량별 구매량 변화 시뮬레이션
    cap_range = list(range(0, 31, 1))
    buy_trend = []
    for cap_test in cap_range:
        _, _, b_with = run_ess_sim(gen_data, con_data, cap_test, ess_eff)
        buy_trend.append(sum(b_with))
        
    fig3, ax3 = plt.subplots(figsize=(10, 4.2))
    ax3.plot(cap_range, buy_trend, color='#4D96FF', linewidth=2.5, marker='s', label='Grid Buy vs ESS Capacity')
    ax3.axvline(x=ess_cap, color='#FF6B6B', linestyle='--', label=f'Current Cap ({ess_cap} kWh)')
    
    ax3.set_xlabel('ESS Capacity (kWh)')
    ax3.set_ylabel('Total Daily Grid Buy (kWh)')
    ax3.legend(loc='upper right')
    ax3.grid(True, linestyle='--', alpha=0.5)
    st.pyplot(fig3)

# 상세 수치 표
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
