import streamlit as st
import pandas as pd
import os
from datetime import datetime
import time
import json
import io
import shutil

# 导入安全 Token 和二维码生成库
try:
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
    import qrcode
    TOKEN_AVAILABLE = True
except ImportError:
    TOKEN_AVAILABLE = False
    
# Token 加密密钥
SECRET_KEY = os.environ.get("STREAMLIT_SECRET_KEY", "your_insecure_default_secret_key_12345")
def get_serializer(key):
    return URLSafeTimedSerializer(key)

# --- 1. 常量与配置 ---
ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'
CONFIG_FILE = 'config.json'

LOGIN_PAGE = "系统用户登录"
ATHLETE_LOGIN_PAGE = "选手登录"
ATHLETE_WELCOME_PAGE = "选手欢迎页"
CHECKPOINTS = ['START', 'MID', 'FINISH']

# 初始化 Session State
state_defaults = {
    'logged_in': False,
    'athlete_logged_in': False,
    'username': None,
    'user_role': None,
    'athlete_username': None,
    'page_selection': "选手登记",
    'scan_status': None,
    'scan_result_info': "",
    'current_qr': {'token': None, 'generated_at': 0, 'expiry': 0, 'checkpoint': CHECKPOINTS[0]},
    'show_manual_scan_info': False
}
for key, val in state_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# --- 2. 配置与权限函数 ---
DEFAULT_CONFIG = {
    "system_title": "梅州市第三人民医院赛事管理系统",
    "registration_title": "选手资料登记",
    "athlete_welcome_title": "恭喜您报名成功！",
    "athlete_welcome_message": "感谢您参加本次赛事，祝取得好成绩。",
    "athlete_sign_in_message": "请使用手机扫码登记。",
    "athlete_notice": "【安全提醒】登山过程请注意人身安全，如有不适请联系工作人员。", 
    "QR_CODE_BASE_URL": "http://127.0.0.1:8501", 
    "QR_CODE_EXPIRY_SECONDS": 90,
    "users": {
        "admin": {"password": "123", "role": "SuperAdmin"},
    }
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return {**DEFAULT_CONFIG, **json.load(f)}

def save_config(config_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

def check_permission(required_roles):
    return st.session_state.get('logged_in') and st.session_state.user_role in required_roles

# --- 3. 数据处理函数 ---
def load_athletes_data():
    cols = ['athlete_id', 'department', 'name', 'gender', 'phone', 'username', 'password']
    if not os.path.exists(ATHLETES_FILE):
        return pd.DataFrame(columns=cols)
    return pd.read_csv(ATHLETES_FILE, dtype={'athlete_id': str, 'username': str, 'password': str})

def save_csv_safe(df, filename):
    if os.path.exists(filename):
        shutil.copy(filename, filename + ".bak")
    df.to_csv(filename, index=False, encoding='utf-8-sig')

def load_records_data():
    if not os.path.exists(RECORDS_FILE):
        return pd.DataFrame(columns=['athlete_id', 'checkpoint_type', 'timestamp'])
    return pd.read_csv(RECORDS_FILE, parse_dates=['timestamp'], dtype={'athlete_id': str})

def calculate_net_time(df_records):
    if df_records.empty: return pd.DataFrame()
    df_records['timestamp'] = pd.to_datetime(df_records['timestamp'], errors='coerce')
    pivot = df_records.groupby(['athlete_id', 'checkpoint_type'])['timestamp'].min().unstack()
    if 'START' not in pivot or 'FINISH' not in pivot: return pd.DataFrame()
    df = pivot.dropna(subset=['START', 'FINISH']).copy()
    df['total_time_sec'] = (df['FINISH'] - df['START']).dt.total_seconds()
    return df[df['total_time_sec'] > 0].reset_index()

def format_time(seconds):
    if pd.isna(seconds): return 'N/A'
    return f"{int(seconds//60):02d}:{seconds%60:06.3f}"

# --- 4. 管理员功能：权限与个人中心 ---
def display_personal_center(config):
    st.subheader("👤 个人中心 - 修改密码")
    new_pwd = st.text_input("设置新密码", type="password")
    if st.button("确认修改密码"):
        if new_pwd:
            config['users'][st.session_state.username]['password'] = new_pwd
            save_config(config)
            st.success("密码修改成功！下一次登录生效。")
        else:
            st.error("密码不能为空")

def display_user_management(config):
    st.subheader("👥 账号权限管理 (仅限超级管理员)")
    
    # 账号列表编辑
    user_data = [{"用户名": u, "角色": d['role'], "密码": d['password']} for u, d in config['users'].items()]
    df_users = pd.DataFrame(user_data)
    edited_df = st.data_editor(df_users, num_rows="dynamic", use_container_width=True)
    
    if st.button("💾 保存账号更改"):
        new_users = {row['用户名']: {"password": str(row['密码']), "role": row['角色']} for _, row in edited_df.iterrows()}
        if not any(v['role'] == 'SuperAdmin' for v in new_users.values()):
            st.error("必须保留至少一个 SuperAdmin！")
        else:
            config['users'] = new_users
            save_config(config)
            st.success("账号信息已更新")
            st.rerun()

# --- 5. 选手功能 ---
def display_registration_form(config):
    st.header(f"👤 {config['registration_title']}")
    with st.form("reg_form", clear_on_submit=True):
        dept = st.text_input("单位/部门")
        name = st.text_input("姓名")
        phone = st.text_input("手机号")
        if st.form_submit_button("提交报名"):
            df = load_athletes_data()
            if phone in df['phone'].values: st.error("该手机已注册"); return
            new_id = str(int(df['athlete_id'].astype(int).max() + 1)) if not df.empty else "1001"
            new_row = pd.DataFrame([{'athlete_id': new_id, 'department': dept, 'name': name, 'gender': '未指定', 'phone': phone, 'username': name, 'password': phone}])
            save_csv_safe(pd.concat([df, new_row], ignore_index=True), ATHLETES_FILE)
            st.success(f"报名成功！编号: {new_id}。请前往选手登录。")

def display_athlete_welcome_page(config):
    if not st.session_state.athlete_logged_in: return
    df_ath = load_athletes_data()
    user = df_ath[df_ath['username'] == st.session_state.athlete_username].iloc[0]
    
    # Token 计时逻辑
    token = st.query_params.get('token')
    if token:
        st.query_params.clear()
        try:
            data = get_serializer(SECRET_KEY).loads(token, salt='checkpoint-timing', max_age=config['QR_CODE_EXPIRY_SECONDS'])
            cp = data['cp']
            df_rec = load_records_data()
            if df_rec[(df_rec['athlete_id'] == user['athlete_id']) & (df_rec['checkpoint_type'] == cp)].empty:
                new_rec = pd.DataFrame([{'athlete_id': user['athlete_id'], 'checkpoint_type': cp, 'timestamp': datetime.now()}])
                save_csv_safe(pd.concat([df_rec, new_rec], ignore_index=True), RECORDS_FILE)
                st.toast(f"✅ {cp} 签到成功！", icon="🎉")
            else:
                st.toast("⚠️ 请勿重复签到", icon="🚨")
            time.sleep(1); st.rerun()
        except: st.error("二维码无效或已过期")

    st.header(f"🎉 {config['athlete_welcome_title']}")
    st.info(f"选手：{user['name']} | 编号：{user['athlete_id']}")
    
    # 进度显示
    rec = load_records_data()
    done = rec[rec['athlete_id'] == user['athlete_id']]['checkpoint_type'].tolist()
    cols = st.columns(len(CHECKPOINTS))
    for i, cp in enumerate(CHECKPOINTS):
        cols[i].write(f"{'✅' if cp in done else '⚪'} {cp}")

    st.markdown("---")
    st.write(config['athlete_welcome_message'])
    
    if st.button("▶️ 打开摄像头扫码计时", type="primary"):
        st.session_state.show_manual_scan_info = True
        st.rerun()

    if st.session_state.show_manual_scan_info:
        st.warning(f"📱 {config['athlete_sign_in_message']}")
    
    # 显示页脚自定义公告
    st.info(f"📢 **赛事公告：**\n\n{config['athlete_notice']}")

# --- 6. 核心页面路由 ---
def main_app():
    config = load_config()
    st.sidebar.title(f"🏁 {config['system_title']}")
    
    pages = ["选手登记"]
    if st.session_state.athlete_logged_in:
        pages = [ATHLETE_WELCOME_PAGE]
        if st.sidebar.button("退出选手账号"): st.session_state.athlete_logged_in = False; st.rerun()
    elif st.session_state.logged_in:
        role = st.session_state.user_role
        pages += ["个人中心"]
        if role in ["SuperAdmin", "Referee"]: pages += ["计时扫码", "数据管理"]
        if role in ["SuperAdmin", "Leader"]: pages += ["排名结果"]
        if role == "SuperAdmin": pages += ["归档与重置"]
        if st.sidebar.button("退出管理账号"): st.session_state.logged_in = False; st.rerun()
    else:
        pages += [ATHLETE_LOGIN_PAGE, LOGIN_PAGE]

    page = st.sidebar.radio("功能模块", pages, index=pages.index(st.session_state.page_selection) if st.session_state.page_selection in pages else 0)
    st.session_state.page_selection = page

    # --- 页面内容映射 ---
    if page == "选手登记": display_registration_form(config)
    elif page == ATHLETE_LOGIN_PAGE:
        with st.form("a_l"):
            u = st.text_input("姓名")
            p = st.text_input("手机号", type="password")
            if st.form_submit_button("选手登录"):
                df = load_athletes_data()
                if not df[(df['username'] == u) & (df['password'] == p)].empty:
                    st.session_state.athlete_logged_in, st.session_state.athlete_username, st.session_state.page_selection = True, u, ATHLETE_WELCOME_PAGE
                    st.rerun()
                else: st.error("账号密码错误")
    elif page == ATHLETE_WELCOME_PAGE: display_athlete_welcome_page(config)
    elif page == LOGIN_PAGE:
        with st.form("m_l"):
            u = st.text_input("用户名")
            p = st.text_input("密码", type="password")
            if st.form_submit_button("管理登录"):
                if u in config['users'] and config['users'][u]['password'] == p:
                    st.session_state.logged_in, st.session_state.username, st.session_state.user_role = True, u, config['users'][u]['role']
                    st.session_state.page_selection = "个人中心"
                    st.rerun()
                else: st.error("认证失败")
    elif page == "个人中心": display_personal_center(config)
    elif page == "计时扫码":
        if check_permission(["SuperAdmin", "Referee"]):
            st.header("⏱️ 二维码终端")
            cp = st.selectbox("当前检查点", CHECKPOINTS)
            qr_state = st.session_state.current_qr
            now = time.time()
            if qr_state['checkpoint'] != cp or (now - qr_state['generated_at'] > config['QR_CODE_EXPIRY_SECONDS']):
                token = get_serializer(SECRET_KEY).dumps({'cp': cp}, salt='checkpoint-timing')
                st.session_state.current_qr = {'token': token, 'generated_at': now, 'expiry': config['QR_CODE_EXPIRY_SECONDS'], 'url': f"{config['QR_CODE_BASE_URL']}?token={token}", 'checkpoint': cp}
                st.rerun()
            qr_img = qrcode.make(st.session_state.current_qr['url'])
            buf = io.BytesIO()
            qr_img.save(buf, format="PNG")
            st.image(buf.getvalue(), caption=f"请扫描 {cp}", width=300)
            st.write(f"有效期剩余: {int(config['QR_CODE_EXPIRY_SECONDS'] - (now - qr_state['generated_at']))} 秒")
            time.sleep(1); st.rerun()
    elif page == "排名结果":
        st.header("🏆 成绩排名")
        df_final = calculate_net_time(load_records_data()).merge(load_athletes_data(), on='athlete_id', how='left').sort_values('total_time_sec')
        df_final['排名'] = range(1, len(df_final)+1)
        df_final['总用时'] = df_final['total_time_sec'].apply(format_time)
        st.dataframe(df_final[['排名', 'name', 'department', '总用时']], use_container_width=True)
    elif page == "数据管理":
        tab1, tab2 = st.tabs(["数据表编辑", "系统配置管理"])
        with tab1:
            df_ath = load_athletes_data()
            new_ath = st.data_editor(df_ath, num_rows="dynamic")
            if st.button("更新选手数据"): save_csv_safe(new_ath, ATHLETES_FILE); st.success("已更新")
        with tab2:
            st.subheader("系统标题与公告配置")
            config['system_title'] = st.text_input("系统标题", config['system_title'])
            config['QR_CODE_BASE_URL'] = st.text_input("APP公网链接", config['QR_CODE_BASE_URL'])
            config['athlete_notice'] = st.text_area("选手端页脚公告/声明", config['athlete_notice'])
            if st.button("保存系统配置"): save_config(config); st.success("配置已更新")
            if st.session_state.user_role == "SuperAdmin":
                display_user_management(config)
    elif page == "归档与重置":
        display_archive_reset()

def display_archive_reset():
    if not check_permission(["SuperAdmin"]): return
    st.header("⚠️ 危险操作")
    if st.button("归档并清空本场比赛数据"):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        for f in [ATHLETES_FILE, RECORDS_FILE]:
            if os.path.exists(f): os.rename(f, f"ARCHIVE_{ts}_{f}")
        st.success("数据已归档，系统已重置"); time.sleep(1); st.rerun()

if __name__ == '__main__':
    st.set_page_config(page_title="赛事管理系统", layout="wide")
    main_app()
