import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import platform
from datetime import datetime, timedelta

# -------------------------------------------------------------------
# 0. 한글 폰트 설정 (OS별 자동 대응하여 그래프 깨짐 방지)
# -------------------------------------------------------------------
system_name = platform.system()
if system_name == "Windows":
    plt.rc('font', family='Malgun Gothic')
elif system_name == "Darwin": # macOS
    plt.rc('font', family='AppleGothic')
else: # Linux/Streamlit Cloud
    plt.rc('font', family='NanumGothic')

plt.rc('axes', unicode_minus=False) # 마이너스 기호 깨짐 방지

# -------------------------------------------------------------------
# 1. 페이지 설정 및 API 키
# -------------------------------------------------------------------
st.set_page_config(
    page_title="스마트 태양광-ESS 에너지 시뮬레이터",
    page_icon="☀️",
    layout="wide"
)

API_KEY = "bef4e395ec061a6a0aa3e92a38af699d2fe16f3921787d2fc1b57d5bda732639"

# 한전 표준 가정 소비 패턴 비율 (24시간 합계 1.0)
CONSUMPTION_RATIO = [
    0.021, 0.018, 0.014, 0.014, 0.014, 0.018, 
    0.028, 0.057, 0.064, 0.035, 0.028, 0.028,  
    0.028, 0.032, 0.028, 0.035, 0.043, 0.057,  
    0.085, 0.099, 0.092, 0.078, 0.050, 0.028   
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
    
    # 백업 표준 일사량 데이터 (MJ/m2 단위)
    return [0, 0, 0, 0, 0, 0, 0.2, 0.8, 1.5, 2.2, 2.7, 2.9, 2.8, 2.4, 1.8, 1.1, 0.4, 0.1, 0, 0, 0, 0, 0, 0], False

# -------------------------------------------------------------------
# 3. 정밀 ESS 시뮬레이션 알고리즘 (출력 제한 및 연속 연산)
# -------------------------------------------------------------------
def run_ess_sim(generation, consumption, capacity, efficiency, max_power=3.0):
    eff = efficiency / 100.0
    
    gen_48 = generation * 2
    con_48 = consumption * 2
    
    soc = 0.0
    soc_history_48 = []
    grid_no_ess_48 = []
    grid_with_ess_48 = []
    loss_48 = []
    surplus_48 = []
    
    for gen, con in zip(gen_48, con_48):
        # ESS 미사용 시 외부 구매량
        grid_no_ess_48.append(max(0.0, con - gen))
        
        diff = gen - con
        loss = 0.0
        surplus = 0.0
        
        if diff > 0: # 잉여 전력 발생 -> 충전
            # 최대 충전 출력 제한 적용
            charge_possible = min(diff, max_power)
            surplus = diff - charge_possible # 충전 속도 초과분은 버려짐/송전
            
            actual_charge = charge_possible * eff
            loss += charge_possible * (1.0 - eff) # 충전 손실
            
            if soc + actual_charge > capacity:
                overflow = (soc + actual_charge) - capacity
                surplus += overflow / eff
                soc = capacity
            else:
                soc += actual_charge
                
            grid_with_ess_48.append(0.0)
            
        else: # 전력 부족 발생 -> 방전
            need = abs(diff)
            # 최대 방전 출력 제한 적용
            discharge_possible = min(need, max_power)
            
            available_from_soc = soc * eff
            
            if available_from_soc >= discharge_possible:
                soc -= (discharge_possible / eff)
                loss += discharge_possible * (1.0 - eff) # 방전 손실
                rem_need = need - discharge_possible
                grid_with_ess_48.append(rem_need)
            else:
                actual_supplied = available_from_soc
                loss += (soc) * (1.0 - eff)
                soc = 0.0
                rem_need = need - actual_supplied
                grid_with_ess_48.append(rem_need)
                
        soc_history_48.append(round(soc, 2))
        loss_48.append(round(loss, 2))
        surplus_48.append(round(surplus, 2))
        
    return soc_history_48[24:], grid_no_ess_48[24:], grid_with_ess_48[24:], loss_48[24:], surplus_48[24:]

# -------------------------------------------------------------------
# 4. Streamlit 화면 구성
# -------------------------------------------------------------------
st.title("☀️ 스마트 태양광-ESS 에너지 효율 시뮬레이터")
st.markdown("기상청 **실시간 일사량 API 데이터**와 **공학적 ESS 충·방전 제약 조건**을 반영한 정밀 에너지 수급 분석 도구입니다.")

# 사이드바 설정
st.sidebar.header("⚙️ 시뮬레이션 조건 설정")

weather_condition = st.sidebar.radio("날씨 시나리오 선택", ["일반 (기상청 실측 데이터)", "흐린 날 (일사량 70% 감소)"])

yesterday = datetime.now() - timedelta(days=1)
selected_date = st.sidebar.date_input("조회 날짜 선택", yesterday).strftime("%Y%m%d")

st.sidebar.subheader("1. 태양광 패널 및 소비 사양")
daily_con_input = st.sidebar.slider("하루 총 소비량 (kWh)", 5.0, 30.0, 14.0, 0.5)
panel_area = st.sidebar.slider("패널 면적 (m²)", 5, 50, 20)
panel_eff = st.sidebar.slider("패널 변환 효율 (%)", 10, 25, 18)
pr_ratio = st.sidebar.slider("시스템 손실 계수 (PR)", 0.60, 0.95, 0.80, 0.05, help="인버터, 온도, 먼지 등에 의한 성능 계수 (보통 0.75~0.85)")

st.sidebar.subheader("2. ESS 배터리 사양")
ess_cap = st.sidebar.slider("배터리 용량 (kWh)", 0, 30, 10)
ess_eff = st.sidebar.slider("충·방전 효율 (%)", 50, 100, 90)
max_power = st.sidebar.slider("최대 충·방전 출력 제한 (kW)", 1.0, 10.0, 3.0, 0.5, help="실제 가정용 ESS의 출력 속도 제한")

st.sidebar.subheader("3. 경제성 분석 설정")
electricity_cost = st.sidebar.number_input("전기요금 단가 (원/kWh)", value=200, step=10)
ess_install_cost = st.sidebar.number_input("ESS 설치비 (만원)", value=500, step=50)

# 데이터 수집 및 연산
raw_rad, is_api = fetch_solar_data(selected_date)

# 날씨 시나리오 반영
if weather_condition == "흐린 날 (일사량 70% 감소)":
    raw_rad = [r * 0.3 for r in raw_rad]

# [수정] MJ/m2 -> kWh/m2 변환 (1 MJ = 0.27778 kWh) 및 PR 손실 계수 반영
gen_data = [round((r * 0.27778) * panel_area * (panel_eff / 100.0) * pr_ratio, 2) for r in raw_rad]
con_data = [round(daily_con_input * ratio, 2) for ratio in CONSUMPTION_RATIO]

soc_list, buy_no_ess, buy_with_ess, loss_list, surplus_list = run_ess_sim(
    gen_data, con_data, ess_cap, ess_eff, max_power
)

total_gen = sum(gen_data)
total_con = sum(con_data)
total_buy_no = sum(buy_no_ess)
total_buy_with = sum(buy_with_ess)
total_loss = sum(loss_list)
total_surplus = sum(surplus_list)

saved_kwh = total_buy_no - total_buy_with

# 지표 명확화: 에너지 자급률 vs 외부 전력 구매 절감률
self_sufficiency_rate = ((total_con - total_buy_with) / total_con * 100) if total_con > 0 else 0.0
buy_reduction_rate = (saved_kwh / total_buy_no * 100) if total_buy_no > 0 else 0.0

if is_api:
    st.caption(f"🌐 기상청 공공데이터 API 연동 완료 (조회일자: {selected_date} / 시나리오: {weather_condition})")

# --- 1. 주요 정량 지표 메트릭 카드 ---
st.markdown("---")
m1, m2, m3, m4 = st.columns(4)
m1.metric("하루 태양광 발전량", f"{total_gen:.1f} kWh")
m2.metric("가정 총 전력 소비량", f"{total_con:.1f} kWh")
m3.metric("에너지 자급률", f"{self_sufficiency_rate:.1f} %", help="(총소비량 - 외부구매량) / 총소비량")
m4.metric("외부 전력 구매 절감률", f"{buy_reduction_rate:.1f} %", f"-{saved_kwh:.1f} kWh 절감")

# 손실 및 잉여 서브 메트릭
s1, s2, s3 = st.columns(3)
s1.caption(f"⚡ **충·방전 변환 손실량**: {total_loss:.2f} kWh (효율 {ess_eff}% 적용 시 손실된 에너지)")
s2.caption(f"🔋 **미충전 잉여 전력량**: {total_surplus:.2f} kWh (배터리 용량/출력 초과분)")
s3.caption(f"🔌 **ESS 적용 후 외부 구매량**: {total_buy_with:.1f} kWh (기존 {total_buy_no:.1f} kWh)")

# --- 2. 동적 분석 의견 문구 ---
st.markdown("---")
if ess_cap == 0:
    dynamic_summary = "현재 ESS 용량이 0kWh로 설정되어 배터리에 의한 시프트 절감 효과가 발생하지 않는 상태입니다."
elif weather_condition == "흐린 날 (일사량 70% 감소)":
    dynamic_summary = f"본 조건의 하루 기준, 흐린 날씨로 인해 낮 동안의 발전량이 부족하여 ESS 충전량이 제한되었습니다. 이로 인해 저녁 피크 시간대 외부 구매 절감률이 {buy_reduction_rate:.1f}%에 그치는 ESS의 공학적 한계가 관찰됩니다."
else:
    dynamic_summary = f"본 조건의 하루 기준, ESS 충·방전 출력 제한({max_power}kW) 및 효율 손실({ess_eff}%)을 반영한 결과, 하루 동안 총 {saved_kwh:.1f}kWh의 외부 전력 구매를 절감하여 구매 절감률 {buy_reduction_rate:.1f}%를 기록하였습니다."

st.info(f"💡 **실시간 분석 요약 (단일 일자 조건)**: {dynamic_summary}")

# --- 3. 시각화 탭 ---
st.markdown("---")
st.subheader("📊 에너지 수급 분석 시각화")

tab1, tab2, tab3, tab4 = st.tabs([
    "💡 외부 전력 구매량 절감 비교", 
    "🔋 24시간 발전·소비·배터리 잔량 추이",
    "📈 ESS 용량 변화에 따른 구매량 곡선",
    "💰 경제성 분석 및 투자 회수 시뮬레이션"
])

hours = list(range(24))

with tab1:
    st.markdown("##### 📌 **ESS 도입 시 시간대별 외부 전력 구매량 절감 효과**")
    fig1, ax1 = plt.subplots(figsize=(10, 4.2))
    
    width = 0.35
    ax1.bar([h - width/2 for h in hours], buy_no_ess, width, label='ESS 미사용 (기존 구매량)', color='#FF6B6B', alpha=0.8)
    ax1.bar([h + width/2 for h in hours], buy_with_ess, width, label='ESS 사용 (최적화 구매량)', color='#4D96FF', alpha=0.9)
    
    ax1.set_xlabel('시간 (00시 ~ 23시)')
    ax1.set_ylabel('외부 전력 구매량 (kWh)')
    ax1.set_xticks(hours)
    # [수정] 범례가 19시 막대를 가리지 않도록 좌측 상단 배치
    ax1.legend(loc='upper left')
    ax1.grid(True, axis='y', linestyle='--', alpha=0.5)
    st.pyplot(fig1)

with tab2:
    st.markdown("##### 📌 **시간대별 태양광 발전량, 가정 소비량, ESS 충전 상태(SoC)**")
    fig2, ax2 = plt.subplots(figsize=(10, 4.2))
    
    ax2.plot(hours, gen_data, label='태양광 발전량 (kWh)', color='#FF9F29', linewidth=2, marker='o')
    ax2.plot(hours, con_data, label='가정 소비량 (kWh)', color='#E03B8B', linestyle='--', linewidth=2)
    ax2.plot(hours, soc_list, label='ESS 배터리 잔량 (kWh)', color='#6BCB77', linewidth=2.5)
    
    ax2.set_xlabel('시간 (00시 ~ 23시)')
    ax2.set_ylabel('에너지 (kWh)')
    ax2.set_xticks(hours)
    ax2.legend(loc='upper left')
    ax2.grid(True, linestyle='--', alpha=0.5)
    st.pyplot(fig2)

with tab3:
    st.markdown("##### 📌 **배터리 용량(0~30 kWh) 변화에 따른 하루 외부 전력 구매량 절감 곡선**")
    
    cap_range = list(range(0, 31, 1))
    buy_trend = []
    for cap_test in cap_range:
        _, _, b_with, _, _ = run_ess_sim(gen_data, con_data, cap_test, ess_eff, max_power)
        buy_trend.append(sum(b_with))
        
    fig3, ax3 = plt.subplots(figsize=(10, 4.2))
    ax3.plot(cap_range, buy_trend, color='#4D96FF', linewidth=2.5, marker='s', label='용량별 총 외부 구매량')
    ax3.axvline(x=ess_cap, color='#FF6B6B', linestyle='--', label=f'현재 설정 용량 ({ess_cap} kWh)')
    
    ax3.set_xlabel('ESS 용량 (kWh)')
    ax3.set_ylabel('하루 총 외부 전력 구매량 (kWh)')
    ax3.legend(loc='upper right')
    ax3.grid(True, linestyle='--', alpha=0.5)
    st.pyplot(fig3)

with tab4:
    st.markdown("##### 📌 **전기요금 단가 기반 경제성 및 투자 회수 기간 추정**")
    
    daily_saving_won = saved_kwh * electricity_cost
    monthly_saving_won = daily_saving_won * 30
    yearly_saving_won = daily_saving_won * 365
    
    payback_years = (ess_install_cost * 10000) / yearly_saving_won if yearly_saving_won > 0 else float('inf')
    
    ec1, ec2, ec3 = st.columns(3)
    ec1.metric("하루 예상 절감 금액", f"{daily_saving_won:,.0f} 원")
    ec2.metric("월간 예상 절감 금액", f"{monthly_saving_won:,.0f} 원")
    if payback_years != float('inf'):
        ec3.metric("투자금 회수 예상 기간", f"{payback_years:.1f} 년", f"설치비 {ess_install_cost}만원 기준")
    else:
        ec3.metric("투자금 회수 예상 기간", "회수 불가", "절감액 없음")
        
    st.caption("※ 단일 일자 절감액을 365일 단순 확신한 추정치이며, 계절별 일사량 변동에 따라 차이가 발생할 수 있습니다.")

# --- 4. 상세 데이터 및 한계 섹션 ---
st.markdown("---")
with st.expander("📄 시간대별 정량 데이터 수치 확인하기"):
    df = pd.DataFrame({
        '시간(시)': hours,
        '발전량(kWh)': gen_data,
        '소비량(kWh)': con_data,
        'ESS 잔량(kWh)': soc_list,
        '손실량(kWh)': loss_list,
        '잉여량(kWh)': surplus_list,
        '외부구매(ESS 미사용)': buy_no_ess,
        '외부구매(ESS 사용)': buy_with_ess
    })
    st.dataframe(df, use_container_width=True)

with st.expander("📌 **시뮬레이터 한계점 및 시뮬레이션 전제 조건 (보고서용)**"):
    st.markdown("""
    1. **출력 및 효율 제한**: 실제 가정용 ESS의 충·방전 출력 속도 제한(기본 3.0 kW) 및 충·방전 변환 손실(기본 10%)을 연산 모델에 반영함.
    2. **시스템 손실 계수(PR)**: 태양광 패널의 인버터 효율, 온도 상승에 따른 출력 저하, 먼지 손실 등을 종합하여 PR 계수(기본 0.80)를 적용함.
    3. **소비 패턴 고정**: 본 시뮬레이션은 한국전력 표준 가정 24시간 소비 패턴 비율을 적용하였으므로, 개별 가구의 특수한 전력 사용 패턴과는 차이가 있을 수 있음.
    4. **배터리 열화 무시**: 시간 경과에 따른 ESS 배터리 잔존 수명(SOH) 감소 및 성능 열화는 본 단일 일자 시뮬레이션 모델에서 고려하지 않음.
    """)
