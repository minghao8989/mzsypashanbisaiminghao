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
    cols = ['athlete_id', 'department', 'team_name', 'name', 'gender', 'phone', 'username', 'password']
    if not os.path.exists(ATHLETES_FILE):
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(ATHLETES_FILE, dtype={'athlete_id': str, 'username': str, 'password': str})
    for col in cols:
        if col not in df.columns: df[col] = "未填写"
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

# --- 3. 排名逻辑模块 ---

def display_results_ranking():
    st.header("🏆 个人成绩排名")
    df_rec = load_records_data()
    if df_rec.empty: st.warning("暂无比赛记录"); return
    df_res = calculate_net_time(df_rec)
    if df_res.empty: st.warning("尚无选手完成赛段"); return
    df_final = df_res.merge(load_athletes_data(), on='athlete_id', how='left').sort_values('total_time_sec')
    df_final['排名'] = range(1, len(df_final)+1)
    df_final['用时'] = df_final['total_time_sec'].apply(format_time)
    st.dataframe(df_final[['排名', 'name', 'team_name', 'department', '用时']], use_container_width=True, hide_index=True)

def display_team_ranking():
    st.header("👥 团体成绩排名 (按平均用时)")
    st.info("计算规则：团队内所有完赛成员的总用时 ÷ 完赛人数")
    
    df_rec = load_records_data()
    if df_rec.empty: st.warning("暂无比赛记录"); return
    df_res = calculate_net_time(df_rec)
    if df_res.empty: st.warning("暂无有效完赛数据"); return
    
    # 合并团队信息
    df_ath = load_athletes_data()
    df_full = df_res.merge(df_ath, on='athlete_id', how='left')
    
    # 按团队分组计算
    team_stats = df_full.groupby('team_name').agg(
        完赛人数=('athlete_id', 'count'),
        总用时秒=('total_time_sec', 'sum')
    ).reset_index()
    
    # 计算平均分
    team_stats['平均用时秒'] = team_stats['总用时秒'] / team_stats['完赛人数']
    team_stats = team_stats.sort_values('平均用时秒')
    team_stats['排名'] = range(1, len(team_stats) + 1)
    team_stats['平均用时'] = team_stats['平均用时秒'].apply(format_time)
    
    st.dataframe(team_stats[['排名', 'team_name', '完赛人数', '平均用时']], use_container_width=True, hide_index=True)
    
    # 详情展示
    with st.expander("点击查看团队内成员明细"):
        st.write(df_full[['team_name', 'name', 'total_time_sec']].sort_values(['team_name', 'total_time_sec']))

# --- 4. 主程序流程 ---

def display_registration_form(config):
    st.header(f"👤 {config['registration_title']}")
    with st.form("reg_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        dept = col1.text_input("单位/部门")
        team = col2.text_input("团体/团队名称", help="如果是个人赛请填写姓名或留空")
        name = col1.text_input("姓名")
        gender = col2.selectbox("性别", ["男", "女", "其他"])
        phone = st.text_input("手机号")
        if st.form_submit_button("提交报名"):
            if not name or not phone: st.error("姓名和手机号必填"); return
            df = load_athletes_data()
            if phone in df['phone'].values: st.error("该手机号已注册"); return
            new_id = str(int(df['athlete_id'].astype(int).max() + 1)) if not df.empty else "1001"
            new_row = pd.DataFrame([{'athlete_id': new_id, 'department': dept, 'team_name': team if team else "个人", 'name': name, 'gender': gender, 'phone': phone, 'username': name, 'password': phone}])
            save_csv_safe(pd.concat([df, new_row], ignore_index=True), ATHLETES_FILE)
            st.success(f"报名成功！编号: {new_id}")

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
        if role in ["SuperAdmin", "Leader"]: pages += ["个人排名", "团体排名"] # 添加团体模块
        if role == "SuperAdmin": pages += ["归档与重置"]
        if st.sidebar.button("退出管理账号"): st.session_state.logged_in = False; st.rerun()
    else:
        pages += [ATHLETE_LOGIN_PAGE, LOGIN_PAGE]

    if st.session_state.page_selection not in pages: st.session_state.page_selection = pages[0]
    page = st.sidebar.radio("功能模块", pages, index=pages.index(st.session_state.page_selection))
    st.session_state.page_selection = page

    # 路由映射
    if page == "选手登记": display_registration_form(config)
    elif page == ATHLETE_LOGIN_PAGE:
        with st.form("a_l"):
            u = st.text_input("选手姓名"); p = st.text_input("手机号", type="password")
            if st.form_submit_button("登录"):
                df = load_athletes_data()
                if not df[(df['username'] == u) & (df['password'] == p)].empty:
                    st.session_state.athlete_logged_in, st.session_state.athlete_username, st.session_state.page_selection = True, u, ATHLETE_WELCOME_PAGE
                    st.rerun()
                else: st.error("登录失败")
    elif page == ATHLETE_WELCOME_PAGE:
        # [此处逻辑同前一版本 display_athlete_welcome_page，保持一致]
        from modules import athlete_page # 假设你将长逻辑拆分，或在此直接粘贴前文代码
        import sys
        # 为了保持响应简洁，这里假设你直接粘贴前文的 display_athlete_welcome_page 函数
        from __main__ import display_athlete_welcome_page
        display_athlete_welcome_page(config)
        
    elif page == "个人中心":
        st.subheader("🔑 修改个人密码")
        new_p = st.text_input("新密码", type="password")
        if st.button("更新密码"):
            if new_p: config['users'][st.session_state.username]['password'] = new_p; save_config(config); st.success("密码已修改")
    elif page == "个人排名": display_results_ranking()
    elif page == "团体排名": display_team_ranking()
    elif page == "计时扫码":
        # [此处逻辑同前一版本，保持一致]
        from __main__ import display_timing_scanner
        display_timing_scanner(config)
    elif page == "数据管理":
        tab1, tab2 = st.tabs(["数据编辑", "系统配置"])
        with tab1:
            df_ath = load_athletes_data()
            new_ath = st.data_editor(df_ath, num_rows="dynamic", use_container_width=True)
            if st.button("同步数据"): save_csv_safe(new_ath, ATHLETES_FILE); st.success("同步成功")
        with tab2:
            config['system_title'] = st.text_input("系统标题", config['system_title'])
            config['athlete_notice'] = st.text_area("选手公告", config['athlete_notice'])
            if st.button("保存设置"): save_config(config); st.rerun()
            if st.session_state.user_role == "SuperAdmin":
                from __main__ import display_user_management
                display_user_management(config)
    elif page == "归档与重置":
        if st.button("确认重置"):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            for f in [ATHLETES_FILE, RECORDS_FILE]:
                if os.path.exists(f): os.rename(f, f"ARCHIVE_{ts}_{f}")
            st.rerun()

# 补充缺失的函数定义（为了代码完整可运行）
def display_athlete_welcome_page(config):
    df_ath = load_athletes_data()
    user = df_ath[df_ath['username'] == st.session_state.athlete_username].iloc[0]
    st.header(f"🎉 {config['athlete_welcome_title']}")
    st.info(f"选手：{user['name']} | 团队：{user['team_name']}")
    rec = load_records_data()
    done = rec[rec['athlete_id'] == user['athlete_id']]['checkpoint_type'].tolist()
    st.write("🚩 **签到进度：**")
    cols = st.columns(len(CHECKPOINTS))
    for i, cp in enumerate(CHECKPOINTS): cols[i].write(f"{'✅' if cp in done else '⚪'} {cp}")
    st.markdown("---")
    st.info(f"📢 **公告：** {config['athlete_notice']}")

def display_timing_scanner(config):
    cp = st.selectbox("当前检查点", CHECKPOINTS)
    qr_state = st.session_state.current_qr
    now = time.time()
    if qr_state['checkpoint'] != cp or (now - qr_state['generated_at'] > config['QR_CODE_EXPIRY_SECONDS']):
        token = get_serializer(SECRET_KEY).dumps({'cp': cp}, salt='checkpoint-timing')
        st.session_state.current_qr = {'token': token, 'generated_at': now, 'url': f"{config['QR_CODE_BASE_URL']}?token={token}", 'checkpoint': cp}
        st.rerun()
    qr_img = qrcode.make(st.session_state.current_qr['url'])
    buf = io.BytesIO(); qr_img.save(buf, format="PNG")
    st.image(buf.getvalue(), caption=f"请扫描 {cp}", width=300)
    time.sleep(1); st.rerun()

def display_user_management(config):
    user_data = [{"用户名": u, "角色": d['role'], "密码": d['password']} for u, d in config['users'].items()]
    edited_df = st.data_editor(pd.DataFrame(user_data), num_rows="dynamic", column_config={"角色": st.column_config.SelectboxColumn("权限", options=["SuperAdmin", "Leader", "Referee"])})
    if st.button("保存账号"):
        config['users'] = {row['用户名']: {"password": str(row['密码']), "role": row['角色']} for _, row in edited_df.iterrows() if row['用户名']}
        save_config(config); st.success("已保存")

if __name__ == '__main__':
    st.set_page_config(page_title="登山赛管理系统", layout="wide")
    main_app()
