import streamlit as st
import pandas as pd
import os
from datetime import datetime
import time
import json
import re
import shutil

# 导入安全 Token 和二维码生成库
try:
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
    import qrcode
    import io
    TOKEN_AVAILABLE = True
except ImportError:
    TOKEN_AVAILABLE = False
    
# Token 加密密钥和签名器定义
SECRET_KEY = os.environ.get("STREAMLIT_SECRET_KEY", "your_insecure_default_secret_key_12345")
def get_serializer(key):
    return URLSafeTimedSerializer(key)


# --- 1. 配置和数据文件定义 & 常量 ---

ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'
CONFIG_FILE = 'config.json'

LOGIN_PAGE = "系统用户登录"
ATHLETE_LOGIN_PAGE = "选手登录"
ATHLETE_WELCOME_PAGE = "选手欢迎页"
CHECKPOINTS = ['START', 'MID', 'FINISH'] # 定义检查点类型

# Session State 变量管理
if 'current_qr' not in st.session_state:
    st.session_state.current_qr = {'token': None, 'generated_at': 0, 'expiry': 0, 'checkpoint': CHECKPOINTS[0]}
if 'show_manual_scan_info' not in st.session_state:
    st.session_state.show_manual_scan_info = False
if 'scan_status' not in st.session_state:
    st.session_state.scan_status = None
if 'scan_result_info' not in st.session_state:
    st.session_state.scan_result_info = ""

# 初始化其他 Session State
for key in ['logged_in', 'athlete_logged_in']:
    if key not in st.session_state:
        st.session_state[key] = False
if 'page_selection' not in st.session_state:
    st.session_state.page_selection = "选手登记"


# --- 2. 辅助函数：配置与权限 ---

DEFAULT_CONFIG = {
    "system_title": "梅州市第三人民医院赛事管理系统",
    "registration_title": "梅州市第三人民医院选手资料登记",
    "athlete_welcome_title": "恭喜您报名成功！",
    "athlete_welcome_message": "感谢您积极参加本单位的赛事活动，祝您能够取得好成绩。",
    "athlete_sign_in_message": "请点击下方按钮，使用手机自带的扫码功能扫描管理员提供的二维码进行计时登记。", 
    "QR_CODE_BASE_URL": "http://127.0.0.1:8501", 
    "QR_CODE_EXPIRY_SECONDS": 90,
    "users": {
        "admin": {"password": "123", "role": "SuperAdmin"},
        "leader01": {"password": "leader_pass", "role": "Leader"},
        "referee01": {"password": "referee_pass", "role": "Referee"}
    }
}

def load_config():
    if not os.path.exists(CONFIG_FILE) or os.path.getsize(CONFIG_FILE) == 0:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return {**DEFAULT_CONFIG, **config}
    except Exception:
        return DEFAULT_CONFIG

def save_config(config_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

def check_permission(required_roles):
    if not st.session_state.get('logged_in'):
        return False
    return st.session_state.user_role in required_roles


# --- 3. 数据加载与保存 (含备份机制) ---

def load_athletes_data():
    default_cols = ['athlete_id', 'department', 'name', 'gender', 'phone', 'username', 'password']
    if not os.path.exists(ATHLETES_FILE) or os.path.getsize(ATHLETES_FILE) == 0:
        df = pd.DataFrame(columns=default_cols)
        df.to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig')
        return df
    return pd.read_csv(ATHLETES_FILE, dtype={'athlete_id': str, 'username': str, 'password': str})

def load_records_data():
    if not os.path.exists(RECORDS_FILE) or os.path.getsize(RECORDS_FILE) == 0:
        df = pd.DataFrame(columns=['athlete_id', 'checkpoint_type', 'timestamp'])
        df.to_csv(RECORDS_FILE, index=False, encoding='utf-8-sig')
        return df
    return pd.read_csv(RECORDS_FILE, parse_dates=['timestamp'], dtype={'athlete_id': str})

def save_athlete_data(df):
    if os.path.exists(ATHLETES_FILE):
        shutil.copy(ATHLETES_FILE, ATHLETES_FILE + ".bak")
    df.to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig')

def save_records_data(df):
    if os.path.exists(RECORDS_FILE):
        shutil.copy(RECORDS_FILE, RECORDS_FILE + ".bak")
    df.to_csv(RECORDS_FILE, index=False, encoding='utf-8-sig')


# --- 4. 核心计算 ---

def calculate_net_time(df_records):
    if df_records.empty: return pd.DataFrame()
    df_records['timestamp'] = pd.to_datetime(df_records['timestamp'], errors='coerce')
    df_records.dropna(subset=['timestamp'], inplace=True)
    timing_pivot = df_records.groupby(['athlete_id', 'checkpoint_type'])['timestamp'].min().unstack()
    if 'START' not in timing_pivot or 'FINISH' not in timing_pivot: return pd.DataFrame()
    
    df_results = timing_pivot.dropna(subset=['START', 'FINISH']).copy()
    df_results = df_results[df_results['FINISH'] > df_results['START']]
    df_results['total_time_sec'] = (df_results['FINISH'] - df_results['START']).dt.total_seconds()
    
    if 'MID' in df_results.columns:
        valid_mid = (df_results['MID'] > df_results['START']) & (df_results['MID'] < df_results['FINISH'])
        df_results.loc[valid_mid, 'segment1_sec'] = (df_results['MID'] - df_results['START']).dt.total_seconds()
        df_results.loc[valid_mid, 'segment2_sec'] = (df_results['FINISH'] - df_results['MID']).dt.total_seconds()
    
    return df_results.reset_index()

def format_time(seconds):
    if pd.isna(seconds) or seconds < 0: return 'N/A'
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds % 60:06.3f}"


# --- 5. 选手功能：登记与欢迎页 (含进度卡片) ---

def display_registration_form(config):
    st.header(f"👤 {config['registration_title']}")
    with st.form("registration_form", clear_on_submit=True):
        dept = st.text_input("单位/部门").strip()
        name = st.text_input("姓名 (登录账号)").strip()
        gender = st.selectbox("性别", ["男", "女", "其他"])
        phone = st.text_input("手机号 (登录密码)").strip()
        if st.form_submit_button("提交报名"):
            if not all([dept, name, phone]):
                st.error("请完善信息"); return
            df = load_athletes_data()
            if phone in df['phone'].values:
                st.error("手机号已注册"); return
            new_id = str(int(df['athlete_id'].astype(int).max() + 1)) if not df.empty else "1001"
            new_row = pd.DataFrame([{'athlete_id': new_id, 'department': dept, 'name': name, 'gender': gender, 'phone': phone, 'username': name, 'password': phone}])
            save_athlete_data(pd.concat([df, new_row], ignore_index=True))
            st.success(f"报名成功！编号：{new_id}")
            time.sleep(1); st.rerun()

def display_athlete_progress(athlete_id):
    """【新增】展示选手的签到进度卡片"""
    df_records = load_records_data()
    user_records = df_records[df_records['athlete_id'] == athlete_id]['checkpoint_type'].tolist()
    st.write("🚩 **您的赛程进度：**")
    cols = st.columns(len(CHECKPOINTS))
    for i, cp in enumerate(CHECKPOINTS):
        with cols[i]:
            if cp in user_records:
                st.success(f"● {cp} (已达)")
            else:
                st.info(f"○ {cp} (未达)")

def handle_timing_record(athlete_id, checkpoint_type):
    """【优化】处理计时登记，增加 Toast 提示"""
    df_records = load_records_data()
    df_athletes = load_athletes_data()
    name = df_athletes[df_athletes['athlete_id'] == athlete_id].iloc[0]['name']
    
    if not df_records[(df_records['athlete_id'] == athlete_id) & (df_records['checkpoint_type'] == checkpoint_type)].empty:
        st.toast(f"⚠️ {name}，已经在 {checkpoint_type} 签过到了", icon="🚨")
        st.session_state.scan_result_info = f"选手 {name} 已在 {checkpoint_type} 签到过。"
        st.session_state.scan_status = 'DUPLICATE'
    else:
        now = datetime.now()
        new_rec = pd.DataFrame([{'athlete_id': athlete_id, 'checkpoint_type': checkpoint_type, 'timestamp': now}])
        save_records_data(pd.concat([df_records, new_rec], ignore_index=True))
        st.toast(f"✅ {checkpoint_type} 签到成功！", icon="🎉")
        st.session_state.scan_result_info = f"恭喜 {name}！{checkpoint_type} 签到成功！时间：{now.strftime('%H:%M:%S')}"
        st.session_state.scan_status = 'SUCCESS'
    
    time.sleep(1.5)
    st.rerun()

def display_athlete_welcome_page(config):
    if not st.session_state.get('athlete_logged_in'): return
    df_athletes = load_athletes_data()
    athlete = df_athletes[df_athletes['username'] == st.session_state.athlete_username].iloc[0]
    athlete_id = athlete['athlete_id']

    # 处理 Token
    token = st.query_params.get('token')
    if token:
        st.query_params.clear()
        try:
            s = get_serializer(SECRET_KEY)
            data = s.loads(token, salt='checkpoint-timing', max_age=config['QR_CODE_EXPIRY_SECONDS'])
            handle_timing_record(athlete_id, data['cp'])
            return
        except Exception as e:
            st.error("Token 无效或已过期")

    st.header(f"🎉 {config['athlete_welcome_title']}")
    st.info(f"选手：{athlete['name']} (编号: {athlete_id})")
    
    # 调用进度显示
    display_athlete_progress(athlete_id)
    
    st.markdown("---")
    if st.session_state.scan_status:
        if st.session_state.scan_status == 'SUCCESS': st.success(st.session_state.scan_result_info)
        else: st.warning(st.session_state.scan_result_info)
        st.session_state.scan_status = None

    if st.button("▶️ 打开摄像头扫码登记", type="primary"):
        st.session_state.show_manual_scan_info = True
        st.rerun()

    if st.session_state.show_manual_scan_info:
        st.warning("📱 请使用手机自带扫码应用扫描管理员二维码，扫描后将自动跳转回此页面记录成绩。")
        if st.button("关闭提示"): 
            st.session_state.show_manual_scan_info = False
            st.rerun()


# --- 6. 管理员功能：扫码、排名、配置 ---

def generate_timing_token(checkpoint, expiry):
    return get_serializer(SECRET_KEY).dumps({'cp': checkpoint}, salt='checkpoint-timing')

def generate_qr_code_image(url):
    qr = qrcode.make(url)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    return buf.getvalue()

def display_timing_scanner(config):
    if not check_permission(["SuperAdmin", "Referee"]): return
    st.header("⏱️ 检查点二维码生成")
    cp = st.selectbox("选择检查点", CHECKPOINTS)
    
    qr_state = st.session_state.current_qr
    now = time.time()
    
    if qr_state['token'] is None or qr_state['checkpoint'] != cp or (now - qr_state['generated_at'] > qr_state['expiry']):
        expiry = config['QR_CODE_EXPIRY_SECONDS']
        token = generate_timing_token(cp, expiry)
        st.session_state.current_qr = {
            'token': token, 'generated_at': now, 'expiry': expiry,
            'url': f"{config['QR_CODE_BASE_URL']}?token={token}", 'checkpoint': cp
        }
        st.rerun()

    rem = int(qr_state['expiry'] - (now - qr_state['generated_at']))
    c1, c2 = st.columns([1, 2])
    c1.image(generate_qr_code_image(qr_state['url']), caption=f"请选手扫描 ({cp})", width=250)
    c2.metric("有效时间剩余", f"{rem} 秒")
    if st.button("🔄 手动刷新二维码"):
        st.session_state.current_qr['generated_at'] = 0
        st.rerun()
    
    time.sleep(1)
    st.rerun()

def display_results_ranking():
    if not check_permission(["SuperAdmin", "Leader"]): return
    st.header("🏆 比赛成绩排名")
    df_res = calculate_net_time(load_records_data())
    if df_res.empty: st.warning("暂无完赛数据"); return
    
    df_final = df_res.merge(load_athletes_data(), on='athlete_id', how='left').sort_values('total_time_sec')
    df_final['排名'] = range(1, len(df_final) + 1)
    for col in ['total_time_sec', 'segment1_sec', 'segment2_sec']:
        if col in df_final.columns: df_final[col.replace('_sec', '')] = df_final[col].apply(format_time)
        
    st.dataframe(df_final[['排名', 'name', 'department', 'total_time', 'segment1', 'segment2']], use_container_width=True)

def display_admin_data_management(config):
    if not check_permission(["SuperAdmin", "Referee"]): return
    st.header("⚙️ 系统管理")
    tab1, tab2 = st.tabs(["数据编辑", "系统配置"])
    with tab1:
        st.subheader("选手数据 (athletes.csv)")
        df_ath = load_athletes_data()
        edited = st.data_editor(df_ath, num_rows="dynamic", use_container_width=True)
        if st.button("保存选手修改"):
            save_athlete_data(edited); st.success("已保存")
    with tab2:
        if check_permission(["SuperAdmin"]):
            new_title = st.text_input("系统标题", config['system_title'])
            new_url = st.text_input("APP 基础 URL", config['QR_CODE_BASE_URL'])
            if st.button("保存配置"):
                config.update({"system_title": new_title, "QR_CODE_BASE_URL": new_url})
                save_config(config); st.rerun()

def display_archive_reset():
    if not check_permission(["SuperAdmin"]): return
    st.header("🗄️ 归档与重置")
    if st.button("🚀 归档当前比赛并清空数据", type="primary"):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if os.path.exists(ATHLETES_FILE): os.rename(ATHLETES_FILE, f"ARCHIVE_ATHLETES_{ts}.csv")
        if os.path.exists(RECORDS_FILE): os.rename(RECORDS_FILE, f"ARCHIVE_RECORDS_{ts}.csv")
        st.success("归档成功！"); time.sleep(1); st.rerun()


# --- 7. 登录与主入口 ---

def set_login_success(config):
    u, p = st.session_state.login_username_input.lower(), st.session_state.login_password_input
    if u in config['users'] and config['users'][u]['password'] == p:
        st.session_state.logged_in, st.session_state.username, st.session_state.user_role = True, u, config['users'][u]['role']
        st.session_state.page_selection = "计时扫码" if st.session_state.user_role != "Leader" else "排名结果"

def set_athlete_login_success():
    u, p = st.session_state.athlete_login_username_input, st.session_state.athlete_login_password_input
    df = load_athletes_data()
    if not df[(df['username'] == u) & (df['password'] == p)].empty:
        st.session_state.athlete_logged_in, st.session_state.athlete_username = True, u
        st.session_state.page_selection = ATHLETE_WELCOME_PAGE

def main_app():
    config = load_config()
    st.sidebar.title(f"🏁 {config['system_title']}")
    
    pages = ["选手登记"]
    if st.session_state.get('athlete_logged_in'):
        pages = [ATHLETE_WELCOME_PAGE]
        if st.sidebar.button("退出选手账号"): 
            st.session_state.athlete_logged_in = False; st.rerun()
    elif st.session_state.get('logged_in'):
        role = st.session_state.user_role
        if role in ["SuperAdmin", "Referee"]: pages += ["计时扫码", "数据管理"]
        if role in ["SuperAdmin", "Leader"]: pages += ["排名结果"]
        if role == "SuperAdmin": pages += ["归档与重置"]
        if st.sidebar.button("退出管理账号"): 
            st.session_state.logged_in = False; st.rerun()
    else:
        pages += [ATHLETE_LOGIN_PAGE, LOGIN_PAGE]

    page = st.sidebar.radio("功能模块", pages, index=pages.index(st.session_state.page_selection) if st.session_state.page_selection in pages else 0)
    st.session_state.page_selection = page

    if page == "选手登记": display_registration_form(config)
    elif page == ATHLETE_LOGIN_PAGE: 
        with st.form("a_login"):
            st.text_input("姓名", key="athlete_login_username_input")
            st.text_input("手机号", type="password", key="athlete_login_password_input")
            if st.form_submit_button("登录", on_click=set_athlete_login_success): pass
    elif page == ATHLETE_WELCOME_PAGE: display_athlete_welcome_page(config)
    elif page == LOGIN_PAGE:
        with st.form("m_login"):
            st.text_input("用户名", key="login_username_input")
            st.text_input("密码", type="password", key="login_password_input")
            if st.form_submit_button("登录", on_click=lambda: set_login_success(config)): pass
    elif page == "计时扫码": display_timing_scanner(config)
    elif page == "排名结果": display_results_ranking()
    elif page == "数据管理": display_admin_data_management(config)
    elif page == "归档与重置": display_archive_reset()

if __name__ == '__main__':
    st.set_page_config(page_title="登山比赛管理系统", page_icon="🏃", layout="wide")
    main_app()
