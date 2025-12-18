import streamlit as st
import pandas as pd
import os
from datetime import datetime
import time
import json
import re

# 导入安全 Token 和二维码生成库
try:
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
    import qrcode
    import io
    TOKEN_AVAILABLE = True
except ImportError:
    TOKEN_AVAILABLE = False
    
# Token 加密密钥和签名器定义
SECRET_KEY = os.environ.get("STREAMLIT_SECRET_KEY", "mzsypashan_secure_key_2024")
def get_serializer(key):
    return URLSafeTimedSerializer(key)


# --- 1. 配置和数据文件定义 & 常量 ---

ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'
CONFIG_FILE = 'config.json'

LOGIN_PAGE = "系统用户登录"
ATHLETE_LOGIN_PAGE = "选手登录"
ATHLETE_WELCOME_PAGE = "选手欢迎页"
CHECKPOINTS = ['START', 'MID', 'FINISH'] 

# Session State 初始化
if 'current_qr' not in st.session_state:
    st.session_state.current_qr = {'token': None, 'generated_at': 0, 'expiry': 0, 'checkpoint': CHECKPOINTS[0]}
if 'show_manual_scan_info' not in st.session_state:
    st.session_state.show_manual_scan_info = False
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'athlete_logged_in' not in st.session_state:
    st.session_state.athlete_logged_in = False
if 'username' not in st.session_state:
    st.session_state.username = None
if 'user_role' not in st.session_state:
    st.session_state.user_role = None
if 'athlete_username' not in st.session_state:
    st.session_state.athlete_username = None
if 'page_selection' not in st.session_state:
    st.session_state.page_selection = "选手登记"


# --- 2. 辅助函数：配置文件的加载与保存 ---

# 您可以在此处直接修改初始密码
DEFAULT_CONFIG = {
    "system_title": "梅州市第三人民医院赛事管理系统",
    "registration_title": "梅州市第三人民医院选手资料登记",
    "athlete_welcome_title": "恭喜您报名成功！",
    "athlete_welcome_message": "感谢您积极参加本单位的赛事活动，祝您能够取得好成绩。",
    "athlete_sign_in_message": "请点击下方按钮，使用手机自带的扫码功能扫描管理员提供的二维码进行计时登记。", 
    "QR_CODE_BASE_URL": "http://127.0.0.1:8501", 
    "QR_CODE_EXPIRY_SECONDS": 90,
    "users": {
        "admin": {"password": "admin_password_123", "role": "SuperAdmin"},
        "leader01": {"password": "leader_pass", "role": "Leader"},
        "referee01": {"password": "referee_pass", "role": "Referee"}
    }
}

def save_config(config_data):
    """保存配置数据到 JSON 文件"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

def load_config():
    """加载配置，并强制将代码中的 DEFAULT_CONFIG 密码同步到文件"""
    if not os.path.exists(CONFIG_FILE) or os.path.getsize(CONFIG_FILE) == 0:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            file_config = json.load(f)
            
            # --- 【核心修复：强制密码同步】 ---
            # 无论 json 文件里存了什么，都以代码里写的 DEFAULT_CONFIG 里的用户和密码为准
            if "users" in DEFAULT_CONFIG:
                file_config["users"] = DEFAULT_CONFIG["users"]
            
            # 合并其他可能在后台修改过的配置项（如标题、URL等）
            merged_config = {**DEFAULT_CONFIG, **file_config}
            
            # 修正后保存回文件，确保下次加载一致
            save_config(merged_config)
            return merged_config
    except Exception:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

def check_permission(required_roles):
    if 'logged_in' not in st.session_state or not st.session_state.logged_in:
        return False
    return st.session_state.user_role in required_roles


# --- 3. 辅助函数：文件加载与保存 ---

def load_athletes_data():
    default_cols = ['athlete_id', 'department', 'name', 'gender', 'phone', 'username', 'password']
    if not os.path.exists(ATHLETES_FILE) or os.path.getsize(ATHLETES_FILE) == 0:
        df = pd.DataFrame(columns=default_cols)
        df.to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig')
        return df
    try:
        df = pd.read_csv(ATHLETES_FILE, dtype={'athlete_id': str, 'username': str, 'password': str})
        for col in default_cols:
            if col not in df.columns: df[col] = ''
        return df
    except Exception:
        return pd.DataFrame(columns=default_cols)

def load_records_data():
    if not os.path.exists(RECORDS_FILE) or os.path.getsize(RECORDS_FILE) == 0:
        df = pd.DataFrame(columns=['athlete_id', 'checkpoint_type', 'timestamp'])
        df.to_csv(RECORDS_FILE, index=False, encoding='utf-8-sig')
        return df
    try:
        return pd.read_csv(RECORDS_FILE, parse_dates=['timestamp'], dtype={'athlete_id': str})
    except Exception:
        return pd.DataFrame(columns=['athlete_id', 'checkpoint_type', 'timestamp'])

def save_athlete_data(df):
    df.to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig')

def save_records_data(df):
    df.to_csv(RECORDS_FILE, index=False, encoding='utf-8-sig')


# --- 4. 计时逻辑 ---

def calculate_net_time(df_records):
    if df_records.empty: return pd.DataFrame()
    df_records['timestamp'] = pd.to_datetime(df_records['timestamp'], errors='coerce')
    df_records['athlete_id'] = df_records['athlete_id'].astype(str)
    df_records.dropna(subset=['timestamp'], inplace=True)
    timing_pivot = df_records.groupby(['athlete_id', 'checkpoint_type'])['timestamp'].min().reset_index()
    timing_pivot = timing_pivot.pivot_table(index='athlete_id', columns='checkpoint_type', values='timestamp', aggfunc='first')
    df_results = timing_pivot.dropna(subset=['START', 'FINISH']).copy()
    df_results = df_results[df_results['FINISH'] > df_results['START']]
    df_results['total_time_sec'] = (df_results['FINISH'] - df_results['START']).dt.total_seconds()
    df_results['segment1_sec'] = None
    df_results['segment2_sec'] = None
    valid_mid = df_results['MID'].notna()
    valid_mid = valid_mid & (df_results['MID'] > df_results['START']) & (df_results['MID'] < df_results['FINISH'])
    df_results.loc[valid_mid, 'segment1_sec'] = (df_results['MID'] - df_results['START']).dt.total_seconds()
    df_results.loc[valid_mid, 'segment2_sec'] = (df_results['FINISH'] - df_results['MID']).dt.total_seconds()
    return df_results.reset_index()

def format_time(seconds):
    if pd.isna(seconds) or seconds is None or seconds < 0: return 'N/A'
    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    return f"{minutes:02d}:{remaining_seconds:06.3f}"


# --- 5. 页面函数：选手登记 ---

def display_registration_form(config):
    st.header(f"👤 {config['registration_title']}")
    if not st.session_state.logged_in and not st.session_state.athlete_logged_in:
        pass 
    elif st.session_state.logged_in and check_permission(["SuperAdmin", "Referee"]):
        pass
    else:
        st.error("您没有权限进行选手登记操作。")
        return

    st.info("请准确填写以下信息。**您的姓名为账号，手机号为密码。**")
    with st.form("registration_form", clear_on_submit=True): 
        department = st.text_input("单位/部门").strip()
        name = st.text_input("姓名 (将作为登录账号)").strip()
        gender = st.selectbox("性别", ["男", "女", "其他"])
        phone = st.text_input("手机号 (将作为登录密码)").strip()
        submitted = st.form_submit_button("提交报名")

        if submitted:
            if not all([department, name, gender, phone]):
                st.error("请填写所有必填信息。")
                return
            df_athletes = load_athletes_data()
            if phone in df_athletes['phone'].values:
                st.error(f"该手机号 ({phone}) 已注册，请勿重复提交。")
                return
            if name in df_athletes['username'].values:
                st.error(f"该姓名 **{name}** 已被注册。")
                return
            new_id = 1001 if df_athletes.empty else int(pd.to_numeric(df_athletes['athlete_id'], errors='coerce').max()) + 1
            new_athlete = pd.DataFrame([{
                'athlete_id': str(new_id), 'department': department, 'name': name,
                'gender': gender, 'phone': phone, 'username': name, 'password': phone
            }])
            df_athletes = pd.concat([df_athletes, new_athlete], ignore_index=True)
            save_athlete_data(df_athletes)
            st.success(f"报名成功! 编号: {new_id}. 请前往选手登录页面。")
            time.sleep(1)
            st.experimental_rerun()


# --- 6. 二维码与 Token 逻辑 ---

def generate_timing_token(checkpoint_type, expiry_seconds):
    s = get_serializer(SECRET_KEY)
    return s.dumps({'cp': checkpoint_type}, salt='checkpoint-timing', max_age=expiry_seconds)

def generate_qr_code_image(url):
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=4, border=4)
    qr.add_data(url); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO(); img.save(buf, format="PNG")
    return buf.getvalue()

def handle_timing_record(athlete_id, checkpoint_type):
    df_records = load_records_data()
    df_athletes = load_athletes_data()
    current_athlete = df_athletes[df_athletes['athlete_id'] == athlete_id].iloc[0]
    name = current_athlete['name']
    existing = df_records[(df_records['athlete_id'] == athlete_id) & (df_records['checkpoint_type'] == checkpoint_type)]
    if not existing.empty:
        st.session_state.scan_result_info = f"选手 **{name}** 已在 **{checkpoint_type}** 签到！"
        st.session_state.scan_status = 'DUPLICATE'
        return
    new_rec = pd.DataFrame({'athlete_id': [athlete_id], 'checkpoint_type': [checkpoint_type], 'timestamp': [datetime.now()]})
    save_records_data(pd.concat([load_records_data(), new_rec], ignore_index=True))
    st.session_state.scan_result_info = f"恭喜 **{name}**！**{checkpoint_type}** 签到成功！"
    st.session_state.scan_status = 'SUCCESS'
    time.sleep(1); st.experimental_rerun()

def display_athlete_welcome_page(config):
    if not st.session_state.athlete_logged_in:
        st.error("请先登录。")
        return
    
    # 捕获 Token 参数
    token_param = st.query_params.get('token')
    if token_param:
        st.query_params.clear()
        try:
            s = get_serializer(SECRET_KEY)
            data = s.loads(token_param, salt='checkpoint-timing', max_age=config['QR_CODE_EXPIRY_SECONDS'])
            df_athletes = load_athletes_data()
            curr = df_athletes[df_athletes['username'] == st.session_state.athlete_username].iloc[0]
            handle_timing_record(curr['athlete_id'], data['cp'])
            return
        except Exception:
            st.error("二维码无效或已过期。")

    st.header(f"🎉 {config['athlete_welcome_title']}")
    st.info(config['athlete_welcome_message'])
    
    df_athletes = load_athletes_data()
    curr = df_athletes[df_athletes['username'] == st.session_state.athlete_username].iloc[0]
    
    col1, col2 = st.columns(2)
    col1.metric("比赛编号", curr['athlete_id'])
    col2.metric("姓名", curr['username'])

    st.subheader("⏱️ 计时签到")
    if st.button("▶️ 打开摄像头扫码登记", type="primary"):
        st.session_state.show_manual_scan_info = True
        st.experimental_rerun()

    if st.session_state.show_manual_scan_info:
        st.warning("📱 请使用手机自带扫码功能（微信/相机）扫描管理员提供的二维码，系统将自动计时。")
        if st.button("知道了"):
            st.session_state.show_manual_scan_info = False
            st.experimental_rerun()


# --- 7. 管理员计时器 ---

def display_timing_scanner(config):
    if not check_permission(["SuperAdmin", "Referee"]):
        st.error("无权限。"); return
    st.header("⏱️ 检查点限时二维码")
    cp = st.selectbox("选择检查点", CHECKPOINTS, key='admin_cp_sel')
    
    # 自动更新二维码逻辑
    now = time.time()
    qr = st.session_state.current_qr
    if (now - qr['generated_at']) > config['QR_CODE_EXPIRY_SECONDS'] or qr['checkpoint'] != cp:
        token = generate_timing_token(cp, config['QR_CODE_EXPIRY_SECONDS'])
        st.session_state.current_qr = {
            'token': token, 'generated_at': now, 'expiry': config['QR_CODE_EXPIRY_SECONDS'],
            'url': f"{config['QR_CODE_BASE_URL']}?token={token}", 'checkpoint': cp
        }
        st.experimental_rerun()

    qr = st.session_state.current_qr
    rem = int(qr['expiry'] - (now - qr['generated_at']))
    
    st.success(f"✅ {qr['checkpoint']} 二维码已生成")
    c1, c2 = st.columns([1, 2])
    c1.image(generate_qr_code_image(qr['url']), width=250)
    c2.metric("剩余有效时间", f"{rem} 秒")
    if c2.button("🔄 手动刷新"):
        st.session_state.current_qr['generated_at'] = 0
        st.experimental_rerun()

    if rem > 0:
        time.sleep(1); st.experimental_rerun()


# --- 8. 排名与数据管理 ---

def display_results_ranking():
    if not check_permission(["SuperAdmin", "Leader"]): return
    st.header("🏆 比赛成绩排名")
    df_calc = calculate_net_time(load_records_data())
    if df_calc.empty: st.warning("暂无完赛记录"); return
    df_final = df_calc.merge(load_athletes_data(), on='athlete_id', how='left').sort_values('total_time_sec')
    df_final['排名'] = range(1, len(df_final) + 1)
    df_final['总用时'] = df_final['total_time_sec'].apply(format_time)
    st.dataframe(df_final[['排名', 'name', 'department', 'athlete_id', '总用时']], hide_index=True)

def display_admin_data_management(config):
    if not check_permission(["SuperAdmin", "Referee"]): return
    st.header("🔑 系统配置")
    with st.form("sys_config"):
        new_title = st.text_input("系统标题", config['system_title'])
        new_url = st.text_input("基本URL (非常重要)", config['QR_CODE_BASE_URL'])
        new_exp = st.number_input("二维码有效期(秒)", value=config['QR_CODE_EXPIRY_SECONDS'])
        if st.form_submit_button("保存配置"):
            config.update({"system_title": new_title, "QR_CODE_BASE_URL": new_url, "QR_CODE_EXPIRY_SECONDS": new_exp})
            save_config(config)
            st.success("配置已更新。")

# --- 9. 登录逻辑 ---

def set_login_success(config, u, p):
    if u in config['users'] and config['users'][u]['password'] == p:
        st.session_state.logged_in = True
        st.session_state.username = u
        st.session_state.user_role = config['users'][u]['role']
        st.session_state.page_selection = "计时扫码" if st.session_state.user_role != "Leader" else "排名结果"
        return True
    return False

def main_app():
    config = load_config()
    st.sidebar.title(f"🏁 {config['system_title']}")
    
    # 导航逻辑
    if st.session_state.athlete_logged_in:
        pages = [ATHLETE_WELCOME_PAGE]
        if st.sidebar.button("退出选手账号"):
            st.session_state.athlete_logged_in = False
            st.experimental_rerun()
    elif st.session_state.logged_in:
        role = st.session_state.user_role
        pages = ["选手登记"]
        if role in ["SuperAdmin", "Referee"]: pages.append("计时扫码")
        if role in ["SuperAdmin", "Leader"]: pages.append("排名结果")
        if role in ["SuperAdmin"]: pages.append("数据管理")
        if st.sidebar.button("退出管理账号"):
            st.session_state.logged_in = False
            st.experimental_rerun()
    else:
        pages = ["选手登记", ATHLETE_LOGIN_PAGE, LOGIN_PAGE]

    page = st.sidebar.radio("选择功能模块", pages, key='page_selection')

    if page == "选手登记": display_registration_form(config)
    elif page == ATHLETE_LOGIN_PAGE:
        st.header("🏃 选手登录")
        with st.form("ath_login"):
            u = st.text_input("姓名"); p = st.text_input("手机号", type="password")
            if st.form_submit_button("登录"):
                df = load_athletes_data()
                if not df[(df['username']==u) & (df['password']==p)].empty:
                    st.session_state.athlete_logged_in = True
                    st.session_state.athlete_username = u
                    st.experimental_rerun()
                else: st.error("账号或密码错误")
    elif page == LOGIN_PAGE:
        st.header("🔑 管理员登录")
        with st.form("adm_login"):
            u = st.text_input("用户名"); p = st.text_input("密码", type="password")
            if st.form_submit_button("登录"):
                if set_login_success(config, u, p): st.experimental_rerun()
                else: st.error("登录失败")
    elif page == ATHLETE_WELCOME_PAGE: display_athlete_welcome_page(config)
    elif page == "计时扫码": display_timing_scanner(config)
    elif page == "排名结果": display_results_ranking()
    elif page == "数据管理": display_admin_data_management(config)

if __name__ == '__main__':
    st.set_page_config(page_title="赛事管理系统", page_icon="🏃", layout="wide")
    main_app()


