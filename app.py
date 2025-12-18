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

# --- 2. 辅助函数 ---
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
        data = json.load(f)
        return {**DEFAULT_CONFIG, **data}

def save_config(config_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

def check_permission(required_roles):
    return st.session_state.get('logged_in') and st.session_state.user_role in required_roles

def load_athletes_data():
    cols = ['athlete_id', 'department', 'name', 'gender', 'phone', 'username', 'password']
    if not os.path.exists(ATHLETES_FILE):
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(ATHLETES_FILE, dtype={'athlete_id': str, 'username': str, 'password': str})
    for col in cols:
        if col not in df.columns: df[col] = ""
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

# --- 3. 页面功能 ---

def display_user_management(config):
    st.subheader("👥 账号权限管理")
    st.info("角色说明：SuperAdmin(全权限), Leader(看排名), Referee(计时/数据管理)")
    
    # 账号列表编辑 - 修复：增加角色下拉选择
    user_data = [{"用户名": u, "角色": d['role'], "密码": d['password']} for u, d in config['users'].items()]
    df_users = pd.DataFrame(user_data)
    
    edited_df = st.data_editor(
        df_users, 
        num_rows="dynamic", 
        use_container_width=True,
        column_config={
            "角色": st.column_config.SelectboxColumn(
                "角色权限",
                help="选择账号的权限级别",
                options=["SuperAdmin", "Leader", "Referee"],
                required=True,
            )
        }
    )
    
    if st.button("💾 保存账号更改"):
        new_users = {str(row['用户名']): {"password": str(row['密码']), "role": row['角色']} for _, row in edited_df.iterrows() if row['用户名']}
        if not any(v['role'] == 'SuperAdmin' for v in new_users.values()):
            st.error("操作失败：必须保留至少一个 SuperAdmin 账号！")
        else:
            config['users'] = new_users
            save_config(config)
            st.success("账号权限配置已成功保存！")
            st.rerun()

def display_registration_form(config):
    st.header(f"👤 {config['registration_title']}")
    with st.form("reg_form", clear_on_submit=True):
        dept = st.text_input("单位/部门")
        name = st.text_input("姓名")
        # 修复：重新加入性别选择
        gender = st.selectbox("性别", ["男", "女", "其他"])
        phone = st.text_input("手机号")
        if st.form_submit_button("提交报名"):
            if not dept or not name or not phone:
                st.error("请填写完整信息"); return
            df = load_athletes_data()
            if phone in df['phone'].values: st.error("该手机号已注册"); return
            new_id = str(int(df['athlete_id'].astype(int).max() + 1)) if not df.empty else "1001"
            new_row = pd.DataFrame([{'athlete_id': new_id, 'department': dept, 'name': name, 'gender': gender, 'phone': phone, 'username': name, 'password': phone}])
            save_csv_safe(pd.concat([df, new_row], ignore_index=True), ATHLETES_FILE)
            st.success(f"报名成功！您的比赛编号为: {new_id}")

def display_athlete_welcome_page(config):
    if not st.session_state.athlete_logged_in: return
    df_ath = load_athletes_data()
    user = df_ath[df_ath['username'] == st.session_state.athlete_username].iloc[0]
    
    # URL Token 计时触发
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
                st.toast("⚠️ 此检查点您已完成签到", icon="🚨")
            time.sleep(1); st.rerun()
        except: st.error("二维码无效或已过期，请扫描最新的二维码。")

    st.header(f"🎉 {config['athlete_welcome_title']}")
    st.info(f"选手：{user['name']} (编号：{user['athlete_id']})")
    
    # 进度显示卡片
    rec = load_records_data()
    done = rec[rec['athlete_id'] == user['athlete_id']]['checkpoint_type'].tolist()
    st.write("🏁 **赛程进度：**")
    cols = st.columns(len(CHECKPOINTS))
    for i, cp in enumerate(CHECKPOINTS):
        status = "✅" if cp in done else "⚪"
        cols[i].metric(label=cp, value=status)

    st.markdown("---")
    st.write(config['athlete_welcome_message'])
    
    if st.button("▶️ 开启扫码计时", type="primary"):
        st.session_state.show_manual_scan_info = True
        st.rerun()

    if st.session_state.show_manual_scan_info:
        st.warning(f"📱 {config['athlete_sign_in_message']}")
    
    st.markdown("---")
    st.info(f"📢 **重要公告：**\n\n{config['athlete_notice']}")

# --- 4. 主流程控制 ---

def main_app():
    config = load_config()
    st.sidebar.title(f"🏁 {config['system_title']}")
    
    # 导航逻辑与权限控制
    pages = ["选手登记"]
    if st.session_state.athlete_logged_in:
        pages = [ATHLETE_WELCOME_PAGE]
        if st.sidebar.button("退出选手账号"): st.session_state.athlete_logged_in = False; st.rerun()
    elif st.session_state.logged_in:
        role = st.session_state.user_role
        pages += ["个人中心"]
        if role in ["SuperAdmin", "Referee"]: pages += ["计时扫码", "数据管理"]
        # 修复：只有超管和领导能看排名结果
        if role in ["SuperAdmin", "Leader"]: pages += ["排名结果"]
        if role == "SuperAdmin": pages += ["归档与重置"]
        if st.sidebar.button("退出管理账号"): st.session_state.logged_in = False; st.rerun()
    else:
        pages += [ATHLETE_LOGIN_PAGE, LOGIN_PAGE]

    # 路由
    if st.session_state.page_selection not in pages: st.session_state.page_selection = pages[0]
    page = st.sidebar.radio("功能模块", pages, index=pages.index(st.session_state.page_selection))
    st.session_state.page_selection = page

    if page == "选手登记": display_registration_form(config)
    elif page == ATHLETE_LOGIN_PAGE:
        with st.form("a_log"):
            u = st.text_input("选手姓名")
            p = st.text_input("手机号", type="password")
            if st.form_submit_button("登录"):
                df = load_athletes_data()
                if not df[(df['username'] == u) & (df['password'] == p)].empty:
                    st.session_state.athlete_logged_in, st.session_state.athlete_username, st.session_state.page_selection = True, u, ATHLETE_WELCOME_PAGE
                    st.rerun()
                else: st.error("验证失败")
    elif page == ATHLETE_WELCOME_PAGE: display_athlete_welcome_page(config)
    elif page == LOGIN_PAGE:
        with st.form("m_log"):
            u = st.text_input("用户名")
            p = st.text_input("密码", type="password")
            if st.form_submit_button("管理登录"):
                if u in config['users'] and config['users'][u]['password'] == p:
                    st.session_state.logged_in, st.session_state.username, st.session_state.user_role = True, u, config['users'][u]['role']
                    st.session_state.page_selection = "个人中心"
                    st.rerun()
                else: st.error("用户名或密码不正确")
    elif page == "个人中心":
        st.subheader("🔑 修改个人密码")
        new_p = st.text_input("新密码", type="password")
        if st.button("更新密码"):
            if new_p:
                config['users'][st.session_state.username]['password'] = new_p
                save_config(config); st.success("密码已成功修改！")
            else: st.error("密码不能为空")
    elif page == "计时扫码":
        st.header("⏱️ 二维码计时终端")
        cp = st.selectbox("选择当前检查点", CHECKPOINTS)
        qr_state = st.session_state.current_qr
        now = time.time()
        if qr_state['checkpoint'] != cp or (now - qr_state['generated_at'] > config['QR_CODE_EXPIRY_SECONDS']):
            token = get_serializer(SECRET_KEY).dumps({'cp': cp}, salt='checkpoint-timing')
            st.session_state.current_qr = {'token': token, 'generated_at': now, 'url': f"{config['QR_CODE_BASE_URL']}?token={token}", 'checkpoint': cp}
            st.rerun()
        qr_img = qrcode.make(st.session_state.current_qr['url'])
        buf = io.BytesIO(); qr_img.save(buf, format="PNG")
        st.image(buf.getvalue(), caption=f"请显示此二维码供选手扫描 ({cp})", width=300)
        st.write(f"二维码刷新倒计时: {int(config['QR_CODE_EXPIRY_SECONDS'] - (now - qr_state['generated_at']))} 秒")
        time.sleep(1); st.rerun()
    elif page == "排名结果":
        st.header("🏆 赛事成绩实时排名")
        df_rec = load_records_data()
        if df_rec.empty: st.warning("暂无比赛记录"); return
        df_res = calculate_net_time(df_rec)
        if df_res.empty: st.warning("尚无选手完成 START 和 FINISH 记录"); return
        df_final = df_res.merge(load_athletes_data(), on='athlete_id', how='left').sort_values('total_time_sec')
        df_final['排名'] = range(1, len(df_final)+1)
        df_final['总用时'] = df_final['total_time_sec'].apply(format_time)
        st.dataframe(df_final[['排名', 'name', 'department', '总用时']], use_container_width=True, hide_index=True)
    elif page == "数据管理":
        tab1, tab2 = st.tabs(["选手及记录维护", "系统与权限配置"])
        with tab1:
            st.subheader("选手资料编辑")
            df_ath = load_athletes_data()
            new_ath = st.data_editor(df_ath, num_rows="dynamic", use_container_width=True)
            if st.button("同步选手更改"): save_csv_safe(new_ath, ATHLETES_FILE); st.success("数据已同步")
        with tab2:
            st.subheader("自定义标题与公告")
            config['system_title'] = st.text_input("系统全局标题", config['system_title'])
            config['QR_CODE_BASE_URL'] = st.text_input("公网部署URL", config['QR_CODE_BASE_URL'])
            config['athlete_notice'] = st.text_area("选手端公告栏文字", config['athlete_notice'])
            if st.button("应用系统配置"): save_config(config); st.success("系统配置已生效")
            if st.session_state.user_role == "SuperAdmin":
                st.markdown("---")
                display_user_management(config)
    elif page == "归档与重置":
        st.header("🚀 赛季数据归档")
        st.warning("归档操作将清空当前的选手和计时记录文件，并创建备份。请谨慎操作！")
        if st.button("执行归档重置", type="primary"):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            for f in [ATHLETES_FILE, RECORDS_FILE]:
                if os.path.exists(f): os.rename(f, f"ARCHIVE_{ts}_{f}")
            st.success("数据已归档，新比赛环境已就绪"); time.sleep(1); st.rerun()

if __name__ == '__main__':
    st.set_page_config(page_title="登山比赛管理系统", page_icon="🏃", layout="wide")
    main_app()
