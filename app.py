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

# --- 1. 配置与初始化 ---
ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'
CONFIG_FILE = 'config.json'
CHECKPOINTS = ['START', 'MID', 'FINISH']
ATHLETE_WELCOME_PAGE = "选手欢迎页"
ATHLETE_LOGIN_PAGE = "选手登录"
LOGIN_PAGE = "系统用户登录"

# 初始化 Session State
state_defaults = {
    'logged_in': False,
    'athlete_logged_in': False,
    'username': None,
    'user_role': None,
    'athlete_username': None,
    'page_selection': "选手登记",
    'current_qr': {'token': None, 'generated_at': 0, 'expiry': 0, 'checkpoint': CHECKPOINTS[0]},
    'show_manual_scan_info': False
}
for key, val in state_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# --- 2. 核心辅助函数 ---
def load_config():
    default = {
        "system_title": "梅州市第三人民医院赛事管理系统",
        "registration_title": "选手资料登记",
        "athlete_welcome_title": "恭喜您报名成功！",
        "athlete_welcome_message": "感谢您参加本次赛事，祝取得好成绩。",
        "athlete_sign_in_message": "请使用手机扫码登记。",
        "athlete_notice": "【安全提醒】登山过程请注意安全。", 
        "QR_CODE_BASE_URL": "http://127.0.0.1:8501", 
        "QR_CODE_EXPIRY_SECONDS": 90,
        "users": {"admin": {"password": "123", "role": "SuperAdmin"}}
    }
    if not os.path.exists(CONFIG_FILE):
        save_config(default)
        return default
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return {**default, **json.load(f)}

def save_config(config_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

def load_athletes_data():
    cols = ['athlete_id', 'department', 'team_name', 'name', 'gender', 'phone', 'username', 'password']
    if not os.path.exists(ATHLETES_FILE):
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(ATHLETES_FILE, dtype={'athlete_id': str, 'username': str, 'password': str})
    for col in cols:
        if col not in df.columns: df[col] = "无"
    return df

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

# --- 3. 核心页面逻辑 ---

def display_registration_form(config):
    st.header(f"👤 {config['registration_title']}")
    with st.form("reg_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        dept = col1.text_input("单位/部门")
        team = col2.text_input("团队名称", value="无")
        name = col1.text_input("姓名")
        gender = col2.selectbox("性别", ["男", "女", "其他"])
        phone = st.text_input("手机号")
        if st.form_submit_button("提交报名"):
            if not name or not phone: st.error("必填项不能为空"); return
            df = load_athletes_data()
            if phone in df['phone'].values: st.error("手机号已存在"); return
            new_id = str(int(df['athlete_id'].astype(int).max() + 1)) if not df.empty else "1001"
            new_row = pd.DataFrame([{'athlete_id': new_id, 'department': dept, 'team_name': team if team else "无", 
                                     'name': name, 'gender': gender, 'phone': phone, 'username': name, 'password': phone}])
            save_csv_safe(pd.concat([df, new_row], ignore_index=True), ATHLETES_FILE)
            st.success(f"登记成功！编号: {new_id}")

def display_athlete_welcome_page(config):
    df_ath = load_athletes_data()
    user = df_ath[df_ath['username'] == st.session_state.athlete_username].iloc[0]
    
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
            time.sleep(1); st.rerun()
        except: st.error("二维码无效或过期")

    st.header(f"🎉 {config['athlete_welcome_title']}")
    st.info(f"选手：{user['name']} | 团队：{user['team_name']}")
    rec = load_records_data(); done = rec[rec['athlete_id'] == user['athlete_id']]['checkpoint_type'].tolist()
    cols = st.columns(len(CHECKPOINTS))
    for i, cp in enumerate(CHECKPOINTS): cols[i].metric(cp, "✅" if cp in done else "⚪")
    st.markdown("---")
    if st.button("▶️ 开启扫码计时", type="primary"): st.session_state.show_manual_scan_info = True
    if st.session_state.show_manual_scan_info: st.warning(config['athlete_sign_in_message'])
    st.info(f"📢 **赛事公告：**\n\n{config['athlete_notice']}")

def display_team_ranking():
    st.header("👥 团体成绩排名")
    df_full = calculate_net_time(load_records_data()).merge(load_athletes_data(), on='athlete_id', how='left')
    df_teams = df_full[df_full['team_name'] != "无"]
    if df_teams.empty: st.info("暂无团体完赛记录"); return
    team_stats = df_teams.groupby('team_name').agg(完赛人数=('athlete_id', 'count'), 总用时秒=('total_time_sec', 'sum')).reset_index()
    team_stats['平均用时秒'] = team_stats['总用时秒'] / team_stats['完赛人数']
    team_stats = team_stats.sort_values('平均用时秒').reset_index(drop=True)
    team_stats['排名'] = team_stats.index + 1
    team_stats['平均用时'] = team_stats['平均用时秒'].apply(format_time)
    st.dataframe(team_stats[['排名', 'team_name', '完赛人数', '平均用时']], use_container_width=True, hide_index=True)

# --- 4. 主程序 ---

def main_app():
    config = load_config()
    st.sidebar.title(f"🏁 {config['system_title']}")
    
    pages = ["选手登记"]
    if st.session_state.athlete_logged_in:
        pages = [ATHLETE_WELCOME_PAGE]
    elif st.session_state.logged_in:
        role = st.session_state.user_role
        pages += ["个人中心"]
        if role in ["SuperAdmin", "Referee"]: pages += ["计时扫码", "数据管理"]
        if role in ["SuperAdmin", "Leader"]: pages += ["个人排名", "团体排名"]
        if role == "SuperAdmin": pages += ["归档与重置"]
    else:
        pages += [ATHLETE_LOGIN_PAGE, LOGIN_PAGE]

    page = st.sidebar.radio("模块", pages, index=pages.index(st.session_state.page_selection) if st.session_state.page_selection in pages else 0)
    st.session_state.page_selection = page

    if page == "选手登记": display_registration_form(config)
    elif page == ATHLETE_LOGIN_PAGE:
        with st.form("a_l"):
            u = st.text_input("姓名"); p = st.text_input("手机号", type="password")
            if st.form_submit_button("选手登录"):
                df = load_athletes_data()
                if not df[(df['username'] == u) & (df['password'] == p)].empty:
                    st.session_state.athlete_logged_in, st.session_state.athlete_username = True, u
                    st.rerun()
    elif page == ATHLETE_WELCOME_PAGE: display_athlete_welcome_page(config)
    elif page == LOGIN_PAGE:
        with st.form("m_l"):
            u = st.text_input("账号"); p = st.text_input("密码", type="password")
            if st.form_submit_button("管理登录"):
                if u in config['users'] and config['users'][u]['password'] == p:
                    st.session_state.logged_in, st.session_state.username, st.session_state.user_role = True, u, config['users'][u]['role']
                    st.rerun()
    elif page == "个人排名":
        st.header("🏆 个人排名")
        df_res = calculate_net_time(load_records_data()).merge(load_athletes_data(), on='athlete_id', how='left').sort_values('total_time_sec')
        df_res['排名'] = range(1, len(df_res)+1); df_res['用时'] = df_res['total_time_sec'].apply(format_time)
        st.dataframe(df_res[['排名', 'name', 'team_name', '用时']], use_container_width=True, hide_index=True)
    elif page == "团体排名": display_team_ranking()
    elif page == "计时扫码":
        cp = st.selectbox("检查点", CHECKPOINTS); now = time.time(); qr_state = st.session_state.current_qr
        if qr_state['checkpoint'] != cp or (now - qr_state['generated_at'] > config['QR_CODE_EXPIRY_SECONDS']):
            token = get_serializer(SECRET_KEY).dumps({'cp': cp}, salt='checkpoint-timing')
            st.session_state.current_qr = {'token': token, 'generated_at': now, 'url': f"{config['QR_CODE_BASE_URL']}?token={token}", 'checkpoint': cp}
            st.rerun()
        st.image(io.BytesIO(qrcode.make(st.session_state.current_qr['url']).tobytes() if False else qrcode.make(st.session_state.current_qr['url']).save(buf:=io.BytesIO(), format="PNG") or buf.getvalue()), caption=f"请扫描 {cp}", width=300)
        st.write(f"刷新倒计时: {int(config['QR_CODE_EXPIRY_SECONDS'] - (now - qr_state['generated_at']))} 秒")
        time.sleep(1); st.rerun()
    elif page == "数据管理":
        t1, t2 = st.tabs(["数据", "配置"])
        with t1:
            df = load_athletes_data(); edited = st.data_editor(df, num_rows="dynamic")
            if st.button("同步数据"): save_csv_safe(edited, ATHLETES_FILE); st.success("已更新")
        with t2:
            config['system_title'] = st.text_input("标题", config['system_title'])
            config['athlete_notice'] = st.text_area("公告", config['athlete_notice'])
            if st.button("保存设置"): save_config(config); st.rerun()
            if st.session_state.user_role == "SuperAdmin":
                user_data = [{"用户名": u, "角色": d['role'], "密码": d['password']} for u, d in config['users'].items()]
                ed = st.data_editor(pd.DataFrame(user_data), num_rows="dynamic", column_config={"角色": st.column_config.SelectboxColumn("权限", options=["SuperAdmin", "Leader", "Referee"])})
                if st.button("保存账号"): config['users'] = {row['用户名']: {"password": str(row['密码']), "role": row['角色']} for _, row in ed.iterrows() if row['用户名']}; save_config(config); st.rerun()
    elif page == "个人中心":
        new_p = st.text_input("新密码", type="password")
        if st.button("修改"): config['users'][st.session_state.username]['password'] = new_p; save_config(config); st.success("成功")
    elif page == "归档与重置":
        if st.button("执行重置", type="primary"):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            for f in [ATHLETES_FILE, RECORDS_FILE]:
                if os.path.exists(f): os.rename(f, f"ARCHIVE_{ts}_{f}")
            st.rerun()

    if st.sidebar.button("退出登录"):
        st.session_state.athlete_logged_in = False
        st.session_state.logged_in = False
        st.rerun()

    # --- 右下角版权信息 ---
    st.markdown(
        """
        <style>
        .footer {
            position: fixed;
            left: 0;
            bottom: 0;
            width: 100%;
            background-color: rgba(255, 255, 255, 0.8);
            color: #888888;
            text-align: right;
            padding-right: 20px;
            padding-bottom: 5px;
            font-size: 12px;
            z-index: 100;
        }
        </style>
        <div class="footer">
            版权归设备科张明豪制作
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == '__main__':
    st.set_page_config(page_title="登山赛管理系统", layout="wide")
    main_app()
