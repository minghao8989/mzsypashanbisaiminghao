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
    
# Token 加密密钥定义
SECRET_KEY = os.environ.get("STREAMLIT_SECRET_KEY", "mzsypashan_secure_key_2024")
def get_serializer(key):
    return URLSafeTimedSerializer(key)


# --- 1. 配置和数据文件定义 ---

ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'
CONFIG_FILE = 'config.json'

LOGIN_PAGE = "系统用户登录"
ATHLETE_LOGIN_PAGE = "选手登录"
ATHLETE_WELCOME_PAGE = "选手欢迎页"
CHECKPOINTS = ['START', 'MID', 'FINISH'] 

# 初始化 Session State 基础键值，防止引用报错
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
if 'current_qr' not in st.session_state:
    st.session_state.current_qr = {'token': None, 'generated_at': 0, 'expiry': 0, 'checkpoint': CHECKPOINTS[0]}
if 'show_manual_scan_info' not in st.session_state:
    st.session_state.show_manual_scan_info = False


# --- 2. 配置加载逻辑 (强制同步密码) ---

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

def save_config(config_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

def load_config():
    """加载配置并强制同步代码中的密码到文件"""
    if not os.path.exists(CONFIG_FILE) or os.path.getsize(CONFIG_FILE) == 0:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            file_config = json.load(f)
            # 核心：确保 admin 密码与 DEFAULT_CONFIG 同步
            file_config["users"] = DEFAULT_CONFIG["users"]
            merged = {**DEFAULT_CONFIG, **file_config}
            save_config(merged)
            return merged
    except Exception:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

def check_permission(required_roles):
    return st.session_state.logged_in and st.session_state.user_role in required_roles


# --- 3. 数据操作函数 ---

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

def save_records_data(df):
    df.to_csv(RECORDS_FILE, index=False, encoding='utf-8-sig')


# --- 4. 计时与二维码逻辑 ---

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
    existing = df_records[(df_records['athlete_id'] == athlete_id) & (df_records['checkpoint_type'] == checkpoint_type)]
    if not existing.empty:
        st.warning(f"选手 {current_athlete['name']} 已在 {checkpoint_type} 签到！")
        return
    new_rec = pd.DataFrame({'athlete_id': [athlete_id], 'checkpoint_type': [checkpoint_type], 'timestamp': [datetime.now()]})
    save_records_data(pd.concat([df_records, new_rec], ignore_index=True))
    st.success(f"恭喜 {current_athlete['name']}！{checkpoint_type} 签到成功！")
    time.sleep(1); st.rerun()

def display_athlete_welcome_page(config):
    if not st.session_state.athlete_logged_in: return
    # 捕获扫码后跳转携带的 Token
    token_param = st.query_params.get('token')
    if token_param:
        st.query_params.clear()
        try:
            s = get_serializer(SECRET_KEY)
            data = s.loads(token_param, salt='checkpoint-timing', max_age=config['QR_CODE_EXPIRY_SECONDS'])
            df = load_athletes_data()
            curr = df[df['username'] == st.session_state.athlete_username].iloc[0]
            handle_timing_record(curr['athlete_id'], data['cp'])
            return
        except Exception: st.error("二维码无效或已过期。")

    st.header(f"🎉 {config['athlete_welcome_title']}")
    st.info(config['athlete_welcome_message'])
    df = load_athletes_data()
    curr = df[df['username'] == st.session_state.athlete_username].iloc[0]
    c1, c2 = st.columns(2)
    c1.metric("比赛编号", curr['athlete_id'])
    c2.metric("姓名", curr['username'])
    if st.button("▶️ 打开摄像头扫码登记", type="primary"):
        st.session_state.show_manual_scan_info = True
    if st.session_state.show_manual_scan_info:
        st.warning("📱 请使用手机自带扫码应用扫描管理员提供的二维码。")
        if st.button("知道了"): st.session_state.show_manual_scan_info = False; st.rerun()


# --- 5. 管理员计时器 ---

def display_timing_scanner(config):
    if not check_permission(["SuperAdmin", "Referee"]): return
    st.header("⏱️ 检查点限时二维码")
    cp = st.selectbox("选择检查点", CHECKPOINTS, key='admin_cp_sel')
    now = time.time()
    qr = st.session_state.current_qr
    # 如果过期或切换了检查点，刷新二维码
    if (now - qr['generated_at']) > config['QR_CODE_EXPIRY_SECONDS'] or qr['checkpoint'] != cp:
        token = generate_timing_token(cp, config['QR_CODE_EXPIRY_SECONDS'])
        st.session_state.current_qr = {
            'token': token, 'generated_at': now, 'expiry': config['QR_CODE_EXPIRY_SECONDS'],
            'url': f"{config['QR_CODE_BASE_URL']}?token={token}", 'checkpoint': cp
        }
        st.rerun()
    rem = int(qr['expiry'] - (now - qr['generated_at']))
    st.success(f"✅ {qr['checkpoint']} 二维码已生成")
    c1, c2 = st.columns([1, 2])
    c1.image(generate_qr_code_image(qr['url']), width=250)
    c2.metric("剩余有效时间", f"{max(0, rem)} 秒")
    if c2.button("🔄 手动刷新"): st.session_state.current_qr['generated_at'] = 0; st.rerun()
    if rem > 0: time.sleep(1); st.rerun()


# --- 6. 主应用入口 ---

def main_app():
    config = load_config()
    st.sidebar.title(f"🏁 {config['system_title']}")
    
    # 定义可访问页面列表
    if st.session_state.athlete_logged_in:
        pages = [ATHLETE_WELCOME_PAGE]
        if st.sidebar.button("退出选手账号"):
            st.session_state.athlete_logged_in = False
            st.session_state.athlete_username = None
            st.session_state.page_selection = "选手登记"
            st.rerun()
    elif st.session_state.logged_in:
        role = st.session_state.user_role
        pages = ["选手登记"]
        if role in ["SuperAdmin", "Referee"]: pages.append("计时扫码")
        if role in ["SuperAdmin", "Leader"]: pages.append("排名结果")
        if role == "SuperAdmin": pages.append("数据管理")
        if st.sidebar.button("退出管理账号"):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.page_selection = "选手登记"
            st.rerun()
    else:
        pages = ["选手登记", ATHLETE_LOGIN_PAGE, LOGIN_PAGE]

    # 处理非法页面重定向
    if st.session_state.page_selection not in pages:
        st.session_state.page_selection = pages[0]
    
    # 侧边栏导航渲染
    page = st.sidebar.radio("功能模块", pages, key='nav_radio', index=pages.index(st.session_state.page_selection))
    st.session_state.page_selection = page

    # --- 页面内容路由 ---
    if page == "选手登记":
        st.header(f"👤 {config['registration_title']}")
        with st.form("reg_form", clear_on_submit=True):
            dept = st.text_input("部门"); name = st.text_input("姓名"); phone = st.text_input("手机号")
            if st.form_submit_button("提交报名"):
                if not (dept and name and phone): st.error("请完整填写"); return
                df = load_athletes_data()
                if phone in df['phone'].values: st.error("该手机号已存在")
                else:
                    new_id = 1001 if df.empty else int(pd.to_numeric(df['athlete_id'], errors='coerce').max()) + 1
                    new_rec = {'athlete_id':str(new_id),'department':dept,'name':name,'phone':phone,'username':name,'password':phone}
                    pd.concat([df, pd.DataFrame([new_rec])]).to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig')
                    st.success(f"报名成功! 编号: {new_id}"); time.sleep(1); st.rerun()
                    
    elif page == ATHLETE_LOGIN_PAGE:
        st.header("🏃 选手登录")
        with st.form("ath_login"):
            u = st.text_input("账号(姓名)"); p = st.text_input("密码(手机号)", type="password")
            if st.form_submit_button("选手登录"):
                df = load_athletes_data()
                if not df[(df['username']==u) & (df['password']==p)].empty:
                    st.session_state.athlete_logged_in = True
                    st.session_state.athlete_username = u
                    st.session_state.page_selection = ATHLETE_WELCOME_PAGE
                    st.rerun()
                else: st.error("姓名或手机号错误")
                
    elif page == LOGIN_PAGE:
        st.header("🔑 管理员登录")
        with st.form("adm_login"):
            u = st.text_input("用户名"); p = st.text_input("密码", type="password")
            if st.form_submit_button("管理员登录"):
                if u in config['users'] and config['users'][u]['password'] == p:
                    st.session_state.logged_in = True
                    st.session_state.username = u
                    st.session_state.user_role = config['users'][u]['role']
                    st.session_state.page_selection = "计时扫码" if st.session_state.user_role != "Leader" else "排名结果"
                    st.rerun()
                else: st.error("认证失败")
                
    elif page == ATHLETE_WELCOME_PAGE: display_athlete_welcome_page(config)
    elif page == "计时扫码": display_timing_scanner(config)
    elif page == "排名结果":
        st.header("🏆 比赛成绩实时排名")
        df_calc = calculate_net_time(load_records_data())
        if not df_calc.empty:
            df_final = df_calc.merge(load_athletes_data(), on='athlete_id').sort_values('total_time_sec')
            df_final['排名'] = range(1, len(df_final)+1)
            df_final['总用时'] = df_final['total_time_sec'].apply(format_time)
            st.dataframe(df_final[['排名', 'name', 'department', '总用时']], hide_index=True)
        else: st.warning("暂无完赛记录")
    elif page == "数据管理":
        st.header("🔑 系统高级配置")
        with st.form("sys_config"):
            new_title = st.text_input("系统标题", config['system_title'])
            new_url = st.text_input("基本URL (非常重要)", config['QR_CODE_BASE_URL'])
            new_exp = st.number_input("二维码刷新频率(秒)", value=config['QR_CODE_EXPIRY_SECONDS'])
            if st.form_submit_button("保存配置"):
                config.update({"system_title": new_title, "QR_CODE_BASE_URL": new_url, "QR_CODE_EXPIRY_SECONDS": int(new_exp)})
                save_config(config); st.success("配置已保存"); st.rerun()

if __name__ == '__main__':
    st.set_page_config(page_title="梅州市三院赛事系统", page_icon="🏃", layout="wide")
    main_app()
