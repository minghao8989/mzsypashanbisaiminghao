import streamlit as st
import pandas as pd
import os
from datetime import datetime
import time
import json
import re

# --- 兼容 query_params 的辅助函数 ---
def get_query_params():
    """安全获取查询参数，兼容新旧 Streamlit 版本"""
    try:
        # Streamlit >= 1.30
        return dict(st.query_params)
    except AttributeError:
        # Streamlit < 1.30
        return st.experimental_get_query_params()

def set_query_params(params_dict):
    """安全设置查询参数，兼容新旧 Streamlit 版本"""
    try:
        # Streamlit >= 1.30
        st.query_params.clear()
        for k, v in params_dict.items():
            st.query_params[k] = v
    except AttributeError:
        # Streamlit < 1.30
        st.experimental_set_query_params(**params_dict)

def clear_query_param(key):
    """清除某个查询参数"""
    params = get_query_params()
    if key in params:
        del params[key]
        set_query_params(params)

# --- 导入安全 Token 和二维码生成库 ---
try:
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
    import qrcode
    import io
    # 尝试生成一个实例来确认库是否可用
    try:
        URLSafeTimedSerializer(os.environ.get("STREAMLIT_SECRET_KEY", "test_key"))
        TOKEN_AVAILABLE = True
    except:
        TOKEN_AVAILABLE = False
except ImportError:
    # 如果库未安装，禁用二维码功能
    TOKEN_AVAILABLE = False
    
# Token 加密密钥和签名器定义
SECRET_KEY = os.environ.get("STREAMLIT_SECRET_KEY", "your_insecure_default_secret_key_12345")

# 【修复点】确保 Serializer 实例只在可用时创建
def get_serializer(key):
    if not TOKEN_AVAILABLE:
        return None
    return URLSafeTimedSerializer(key)


# --- 1. 配置和数据文件定义 & 常量 ---

ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'
CONFIG_FILE = 'config.json'

LOGIN_PAGE = "系统用户登录"
ATHLETE_LOGIN_PAGE = "选手登录"
ATHLETE_WELCOME_PAGE = "选手欢迎页"
CHECKPOINTS = ['START', 'MID', 'FINISH'] 

# 初始化 Session State
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
    
if 'login_username_input' not in st.session_state:
    st.session_state.login_username_input = ""
if 'login_password_input' not in st.session_state:
    st.session_state.login_password_input = ""

# QR 码状态管理
if 'current_qr' not in st.session_state:
    st.session_state.current_qr = {'token': None, 'generated_at': 0, 'expiry': 0, 'checkpoint': CHECKPOINTS[0]}
if 'scan_status' not in st.session_state:
    st.session_state.scan_status = None 
if 'scan_result_info' not in st.session_state:
    st.session_state.scan_result_info = ""


# --- 2. 辅助函数：配置文件的加载与保存 & 权限检查 ---

DEFAULT_CONFIG = {
    "system_title": "梅州市第三人民医院赛事管理系统",
    "registration_title": "梅州市第三人民医院选手资料登记",
    "athlete_welcome_title": "恭喜您报名成功！",
    "athlete_welcome_message": "感谢您积极参加本单位的赛事活动，祝您能够取得好成绩。",
    "athlete_sign_in_message": "请使用手机扫描管理员提供的限时二维码进行计时签到。",
    "QR_CODE_BASE_URL": "http://127.0.0.1:8501", 
    "QR_CODE_EXPIRY_SECONDS": 90, 
    "users": {
        "admin": {"password": "admin_password_123", "role": "SuperAdmin"},
        "leader01": {"password": "leader_pass", "role": "Leader"},
        "referee01": {"password": "referee_pass", "role": "Referee"}
    }
}

def load_config():
    """加载配置数据，如果文件不存在或出错，则创建默认配置"""
    if not os.path.exists(CONFIG_FILE) or os.path.getsize(CONFIG_FILE) == 0:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return {**DEFAULT_CONFIG, **config, 
                    'users': {**DEFAULT_CONFIG.get('users', {}), **config.get('users', {})}}
    except Exception:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

def save_config(config_data):
    """保存配置数据到 JSON 文件"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

def check_permission(required_roles):
    """检查当前登录用户是否具有所需权限"""
    if 'logged_in' not in st.session_state or not st.session_state.logged_in:
        return False
    
    current_role = st.session_state.user_role
    return current_role in required_roles


# --- 3. 辅助函数：文件加载与保存 (保持不变) ---

def load_athletes_data():
    """加载选手资料文件，新增 'username' 和 'password' 列。"""
    default_cols = ['athlete_id', 'department', 'name', 'gender', 'phone', 'username', 'password']
    
    if not os.path.exists(ATHLETES_FILE) or os.path.getsize(ATHLETES_FILE) == 0:
        df = pd.DataFrame(columns=default_cols)
        df.to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig')
        return df
    
    try:
        df = pd.read_csv(ATHLETES_FILE, dtype={'athlete_id': str, 'username': str, 'password': str})
        for col in default_cols:
            if col not in df.columns:
                df[col] = ''
        return df
    except Exception:
        return pd.DataFrame(columns=default_cols)


def load_records_data():
    """加载计时记录文件，如果不存在或为空，则创建包含表头的空文件"""
    if not os.path.exists(RECORDS_FILE) or os.path.getsize(RECORDS_FILE) == 0:
        df = pd.DataFrame(columns=['athlete_id', 'checkpoint_type', 'timestamp'])
        df.to_csv(RECORDS_FILE, index=False, encoding='utf-8-sig')
        return df
        
    try:
        return pd.read_csv(RECORDS_FILE, parse_dates=['timestamp'], dtype={'athlete_id': str})
    except Exception:
        return pd.DataFrame(columns=['athlete_id', 'checkpoint_type', 'timestamp'])

def save_athlete_data(df):
    """保存选手数据到 CSV (使用 utf-8-sig 编码防乱码)"""
    df.to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig')

def save_records_data(df):
    """保存计时数据到 CSV (使用 utf-8-sig 编码防乱码)"""
    df.to_csv(RECORDS_FILE, index=False, encoding='utf-8-sig')

# --- 4. 核心计算与格式化函数 (保持不变) ---

def calculate_net_time(df_records):
    """根据扫码记录计算每位选手的总用时和分段用时。"""
    if df_records.empty:
        return pd.DataFrame()

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
    """格式化秒数到 MM:SS.mmm"""
    if pd.isna(seconds) or seconds is None or seconds < 0:
        return 'N/A'
    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    return f"{minutes:02d}:{remaining_seconds:06.3f}"


# --- 5. 页面函数：选手登记 (保持不变) ---

def display_registration_form(config):
    """选手资料登记页面"""
    st.header(f"👤 {config['registration_title']}")
    
    # 只有未登录或裁判/管理员才能登记
    if not st.session_state.logged_in and not st.session_state.athlete_logged_in:
        pass # 公众可访问
    elif st.session_state.logged_in and check_permission(["SuperAdmin", "Referee"]):
        pass # 管理员可访问
    else:
        st.error("您没有权限进行选手登记操作。")
        return

    st.info("请准确填写以下信息。**您的姓名为账号，手机号为密码。**")
    
    # 使用 clear_on_submit=True 自动清理表单输入，并移除 key 属性以避免 Session State 冲突
    with st.form("registration_form", clear_on_submit=True): 
        
        # 不使用 key 属性
        department = st.text_input("单位/部门").strip()
        name = st.text_input("姓名 (将作为登录账号)").strip()
        gender = st.selectbox("性别", ["男", "女", "其他"])
        phone = st.text_input("手机号 (将作为登录密码，且用于唯一标识)").strip()
        
        submitted = st.form_submit_button("提交报名")

        if submitted:
            if not all([department, name, gender, phone]):
                st.error("请填写所有必填信息。")
                return

            df_athletes = load_athletes_data()
            
            # 检查手机号是否重复注册
            if phone in df_athletes['phone'].values:
                st.error(f"该手机号 ({phone}) 已注册，请勿重复提交。")
                return
            
            # 检查姓名是否重复 (作为账号)
            if name in df_athletes['username'].values:
                st.error(f"该姓名 **{name}** 已被注册为账号。请使用您的全名，如果仍重复，请联系裁判修改。")
                return

            # 生成 ID (逻辑不变)
            if df_athletes.empty:
                new_id = 1001
            else:
                numeric_ids = pd.to_numeric(df_athletes['athlete_id'], errors='coerce').dropna()
                new_id = int(numeric_ids.max()) + 1 if not numeric_ids.empty else 1001
            
            new_id_str = str(new_id)
            
            # --- 生成账号和密码 ---
            new_username = name
            new_password = phone 

            new_athlete = pd.DataFrame([{
                'athlete_id': new_id_str,
                'department': department,
                'name': name,
                'gender': gender,
                'phone': phone,
                'username': new_username,
                'password': new_password
            }])

            df_athletes = pd.concat([df_athletes, new_athlete], ignore_index=True)
            save_athlete_data(df_athletes)

            st.success(f"""
                🎉 报名成功!
                - 比赛编号：**{new_id_str}**
                - 计时账号 (姓名)：**{new_username}**
                - 计时密码 (手机号)：**{new_password}**
                请前往 **选手登录** 页面使用此信息登录，查看您的信息。
            """)
            
            time.sleep(1)
            st.experimental_rerun()


# --- 5.5 新增：选手欢迎页面 (基于安全 Token 和 QR 码) ---

def generate_timing_token(checkpoint_type, expiry_seconds):
    """为指定检查点生成一个限时的安全 Token"""
    if not TOKEN_AVAILABLE:
        raise RuntimeError("Libraries required for token generation are missing.")
    
    s = get_serializer(SECRET_KEY)
    if s is None:
        raise RuntimeError("Serializer could not be initialized.")
        
    data = {'cp': checkpoint_type}
    return s.dumps(data, salt='checkpoint-timing', max_age=expiry_seconds)

def generate_qr_code_image(url):
    """生成包含 URL 的 QR 码图像，并返回字节流"""
    if not TOKEN_AVAILABLE:
        return None
        
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=4,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def handle_timing_record(athlete_id, checkpoint_type):
    """处理计时登记的核心逻辑"""
    
    df_records = load_records_data()
    df_athletes = load_athletes_data()
    
    current_athlete = df_athletes[df_athletes['athlete_id'] == athlete_id].iloc[0]
    name = current_athlete['name']

    # 1. 检查是否重复扫码
    existing_records = df_records[
        (df_records['athlete_id'] == athlete_id) &
        (df_records['checkpoint_type'] == checkpoint_type)
    ]

    if not existing_records.empty:
        st.session_state.scan_result_info = f"选手 **{name}** 已在 **{checkpoint_type}** 签到成功！"
        st.session_state.scan_status = 'DUPLICATE'
        return

    # 2. 提交新记录
    current_time = datetime.now()
    
    new_record = pd.DataFrame({
        'athlete_id': [athlete_id],
        'checkpoint_type': [checkpoint_type],
        'timestamp': [current_time]
    })
    
    df_records = pd.concat([df_records, new_record], ignore_index=True)
    save_records_data(df_records)

    st.session_state.scan_result_info = f"恭喜 **{name}** (编号: {athlete_id})！**{checkpoint_type}** 签到成功！记录时间：**{current_time.strftime('%H:%M:%S.%f')[:-3]}**"
    st.session_state.scan_status = 'SUCCESS'
    
    # 3. 页面刷新以显示最终结果
    time.sleep(1)
    st.experimental_rerun()


def display_athlete_welcome_page(config):
    """选手登录成功后显示的欢迎页面，包含扫码计时功能"""
    if not st.session_state.athlete_logged_in:
        st.error("请先登录选手账号。")
        return
        
    df_athletes = load_athletes_data()
    current_athlete_df = df_athletes[df_athletes['username'] == st.session_state.athlete_username]

    if current_athlete_df.empty:
        st.error("错误：未找到该选手信息。请联系管理员。")
        return
        
    current_athlete = current_athlete_df.iloc[0]
    athlete_id = current_athlete['athlete_id']

    # ----------------------------------------------------
    # 【核心逻辑】检查 URL 中的 Token 参数，执行计时
    # ----------------------------------------------------
    query_params = get_query_params()
    token_param = query_params.get('token', [None])[0] if isinstance(query_params.get('token'), list) else query_params.get('token')

    if token_param:
        # 清除 URL 参数，防止重复记录
        clear_query_param('token')
        
        if not TOKEN_AVAILABLE:
            st.error("🚨 计时失败：服务器缺少安全库 (itsdangerous/qrcode)，请联系管理员解决。")
            st.session_state.scan_status = 'ERROR'
            st.experimental_rerun()
            return
        
        s = get_serializer(SECRET_KEY)
        
        try:
            # 尝试解密 Token，同时验证签名和过期时间
            expiry = config.get('QR_CODE_EXPIRY_SECONDS', 90)
            data = s.loads(token_param, salt='checkpoint-timing', max_age=expiry)
            checkpoint_type = data['cp']
            
            # 执行计时
            handle_timing_record(athlete_id, checkpoint_type)
            return # 计时成功或重复，handle_timing_record 内部会 rerun
            
        except SignatureExpired:
            st.session_state.scan_result_info = "签到失败：二维码已过期，请让管理员重新生成！"
            st.session_state.scan_status = 'ERROR'
            st.experimental_rerun()
            return
        except BadTimeSignature:
            st.session_state.scan_result_info = "签到失败：Token 无效或被篡改，请确认扫描了正确的二维码。"
            st.session_state.scan_status = 'ERROR'
            st.experimental_rerun()
            return
        except Exception as e:
            st.session_state.scan_result_info = f"签到失败：Token 解析错误或发生未知错误。({e})"
            st.session_state.scan_status = 'ERROR'
            st.experimental_rerun()
            return

    # ----------------------------------------------------
    # 欢迎页渲染
    # ----------------------------------------------------
    st.header(f"🎉 {config['athlete_welcome_title']}")
    
    # 自定义消息显示
    st.markdown(f"""
        <div style="padding: 15px; border-radius: 5px; background-color: #f0f2f6; border-left: 5px solid #00c0f2;">
            <p style="font-size: 1.1em; margin: 0;">{config['athlete_welcome_message']}</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # --- 扫码状态显示 ---
    if st.session_state.scan_status == 'SUCCESS':
        st.success(st.session_state.scan_result_info)
    elif st.session_state.scan_status == 'DUPLICATE':
        st.warning(st.session_state.scan_result_info)
    elif st.session_state.scan_status == 'ERROR':
        st.error(st.session_state.scan_result_info)
    
    # 清理状态，等待下一次扫码
    st.session_state.scan_status = None
    st.session_state.scan_result_info = ""

    st.subheader("您的签到凭证")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("您的比赛编号", athlete_id)
    with col2:
        st.metric("签到账号 (姓名)", current_athlete['username'])
        
    st.info(config['athlete_sign_in_message'])
    
    st.markdown("---")
    if not TOKEN_AVAILABLE:
         st.error("⚠️ **计时功能不可用：** 服务器缺少安全库，请联系管理员安装 (`itsdangerous`, `qrcode`)。")
    else:
         st.warning("⚠️ 扫描管理员提供的二维码即可完成计时。")


# --- 6. 页面函数：计时扫码 (管理员生成限时二维码) ---

def generate_new_admin_qr(config, selected_checkpoint):
    """为管理员生成新的限时二维码并存储在 Session State"""
    if not TOKEN_AVAILABLE:
         st.session_state.current_qr = {'token': None, 'generated_at': 0, 'expiry': 0, 'checkpoint': selected_checkpoint}
         return

    expiry_seconds = config.get('QR_CODE_EXPIRY_SECONDS', 90)
    
    try:
        # 生成 Token
        token = generate_timing_token(selected_checkpoint, expiry_seconds)
    except RuntimeError as e:
        st.session_state.current_qr = {'token': None, 'generated_at': 0, 'expiry': 0, 'checkpoint': selected_checkpoint}
        st.error(f"生成 Token 失败: {e}")
        return

    # Token URL: 选手扫描后，手机打开这个链接，应用会捕获 token 参数
    base_url = config.get('QR_CODE_BASE_URL', DEFAULT_CONFIG['QR_CODE_BASE_URL']).rstrip('/')
    token_url = f"{base_url}?page={ATHLETE_WELCOME_PAGE}&token={token}"
    
    st.session_state.current_qr = {
        'token': token,
        'generated_at': time.time(),
        'expiry': expiry_seconds,
        'url': token_url,
        'checkpoint': selected_checkpoint,
    }


def display_timing_scanner(config):
    """
    管理员生成限时二维码的界面。
    """
    
    if not check_permission(["SuperAdmin", "Referee"]):
        st.error("您没有权限访问计时扫码终端。")
        return
        
    if not TOKEN_AVAILABLE:
        st.error("🚨 **计时功能不可用：** 请联系管理员在服务器上安装必要的 Python 库 (`itsdangerous`, `qrcode`)。")
        return

    st.header(f"⏱️ 比赛检查点限时二维码生成")
    st.subheader("请选择检查点，生成限时二维码供选手扫描。")
    
    # 1. 选择要生成二维码的检查点
    selected_checkpoint = st.sidebar.selectbox("选择要生成的检查点二维码", CHECKPOINTS, key='admin_qr_checkpoint_select')
    
    # 2. 检查二维码状态
    current_qr_admin = st.session_state.current_qr
    current_time = time.time()
    
    is_mismatch = current_qr_admin['checkpoint'] != selected_checkpoint
    is_expired = (current_time - current_qr_admin['generated_at']) > current_qr_admin['expiry']

    if is_expired or current_qr_admin['token'] is None or is_mismatch:
        # 重新生成 Token
        generate_new_admin_qr(config, selected_checkpoint)
        # 仅在需要时重新运行
        if st.session_state.current_qr['token'] is not None:
             st.experimental_rerun()
        return

    # 3. 显示当前二维码和倒计时
    qr_data = st.session_state.current_qr
    expiry_seconds = qr_data['expiry']
    remaining_time = expiry_seconds - (current_time - qr_data['generated_at'])
    
    st.markdown("---")
    st.success(f"✅ **{qr_data['checkpoint']} 检查点** 限时二维码已生成！")

    qr_col, info_col = st.columns([1, 2])
    
    with qr_col:
        # 显示二维码图片
        qr_image_bytes = generate_qr_code_image(qr_data['url'])
        st.image(qr_image_bytes, 
                 caption=f"请显示此二维码 ({qr_data['checkpoint']})", 
                 width=250)
        
    with info_col:
        st.metric("二维码剩余有效时间", f"{int(remaining_time)} 秒")
        
        if remaining_time <= 10:
             st.warning("二维码即将过期，请尽快通知选手扫描！")
        
        # 强制刷新按钮 (如果需要立即更换或续期)
        if st.button("🔄 立即重新生成/续期二维码"):
            # 简单地触发重新生成逻辑
            st.session_state.current_qr['generated_at'] = 0 
            st.experimental_rerun()
            return
        
        st.markdown("---")
        st.markdown(f"**Token URL (Base URL):**")
        st.code(config.get('QR_CODE_BASE_URL', DEFAULT_CONFIG['QR_CODE_BASE_URL']))
        st.warning("请确保上述 Base URL 是您的 Streamlit 应用的公网地址，否则选手无法扫码跳转。")


    # 倒计时逻辑：当剩余时间小于 1 秒时，强制刷新页面以生成新的二维码
    if remaining_time <= 1:
        st.experimental_rerun()

    # 自动刷新：为了显示倒计时，使用 time.sleep 暂停并重新运行
    time.sleep(1)
    st.experimental_rerun()


# --- 7. 页面函数：排名结果 (保持不变) ---

def display_results_ranking():
    """结果统计与排名页面"""
    
    if not check_permission(["SuperAdmin", "Leader"]):
        st.error("您没有权限访问排名结果。")
        return

    st.header("🏆 比赛成绩与排名")

    df_records = load_records_data()
    df_athletes = load_athletes_data()
    
    df_calculated = calculate_net_time(df_records)

    if df_calculated.empty:
        st.warning("暂无完整的完赛记录。")
        return

    df_final = df_calculated.merge(df_athletes, on='athlete_id', how='left')

    df_final = df_final.sort_values(by='total_time_sec', ascending=True).reset_index(drop=True)
    df_final['排名'] = df_final.index + 1
    
    df_final['总用时'] = df_final['total_time_sec'].apply(format_time)
    df_final['第一段'] = df_final['segment1_sec'].apply(format_time)
    df_final['第二段'] = df_final['segment2_sec'].apply(format_time)

    total_finishers = len(df_final)
    st.success(f"🎉 当前共有 **{total_finishers}** 位选手完成比赛并计入排名。")
    
    display_cols = ['排名', 'name', 'department', 'athlete_id', '总用时', '第一段', '第二段']
    
    df_display = df_final[display_cols].rename(columns={
        'name': '姓名',
        'department': '单位/部门',
        'athlete_id': '编号'
    })
    
    st.dataframe(df_display, hide_index=True, use_container_width=True)

    csv_data = df_display.to_csv(encoding='utf-8-sig', index=False)
    st.download_button(
        label="💾 下载完整的排名数据 (.csv)",
        data=csv_data,
        file_name="race_ranking_results.csv",
        mime="text/csv"
    )

# --- 8. 页面函数：管理员数据管理 ---

def save_config_callback():
    """保存系统标题、欢迎页和扫码提示配置"""
    
    # 检查 URL 和有效期配置（如果它们在 Session State 中）
    is_qr_config_present = 'new_base_url' in st.session_state and 'new_qr_expiry' in st.session_state

    new_config_updates = {
        "system_title": st.session_state.new_sys_title if 'new_sys_title' in st.session_state else load_config().get('system_title'),
        "registration_title": st.session_state.new_reg_title if 'new_reg_title' in st.session_state else load_config().get('registration_title'),
        "athlete_welcome_title": st.session_state.new_welcome_title if 'new_welcome_title' in st.session_state else load_config().get('athlete_welcome_title'),
        "athlete_welcome_message": st.session_state.new_welcome_message if 'new_welcome_message' in st.session_state else load_config().get('athlete_welcome_message'),
        "athlete_sign_in_message": st.session_state.new_sign_in_message if 'new_sign_in_message' in st.session_state else load_config().get('athlete_sign_in_message'),
    }

    if is_qr_config_present:
        try:
            new_expiry = int(st.session_state.new_qr_expiry)
            if new_expiry <= 0:
                 st.error("二维码有效期必须是大于 0 的整数！")
                 return
        except ValueError:
            st.error("二维码有效期必须是有效的整数！")
            return
        
        new_config_updates['QR_CODE_BASE_URL'] = st.session_state.new_base_url
        new_config_updates['QR_CODE_EXPIRY_SECONDS'] = new_expiry
        
        # 强制让 Token 失效，以便下次访问时生成新 Token
        st.session_state.current_qr['generated_at'] = 0
        
        
    current_config = load_config()
    current_config.update(new_config_updates)
    save_config(current_config)


def display_user_management(config):
    """超级管理员独有：用户和权限管理页面"""
    
    if not check_permission(["SuperAdmin"]):
        st.error("您没有权限访问用户管理页面。")
        return

    st.subheader("👥 用户和权限管理")
    
    show_passwords = st.checkbox("🔑 显示所有用户密码", key="show_passwords_toggle")
    
    # 1. 显示现有用户（集成密码更改功能）
    st.markdown("##### 现有系统用户列表 (可直接修改密码和角色)")
    
    user_list = []
    for user, data in config['users'].items():
        user_list.append({
            "用户名": user,
            "角色": data['role'],
            "密码": data['password'] if show_passwords else "********"
        })
        
    df_users = pd.DataFrame(user_list)
    
    edited_df = st.data_editor(
        df_users,
        key="edit_users_data",
        num_rows="disabled",
        column_config={
            "用户名": st.column_config.Column("用户名", disabled=True),
            "角色": st.column_config.SelectboxColumn(
                "角色", options=["SuperAdmin", "Leader", "Referee"]
            ),
            "密码": st.column_config.Column(
                "密码",
                help="点击单元格可直接修改密码。请勿使用空密码。",
                disabled=not show_passwords 
            )
        },
        use_container_width=True
    )
    
    # 2. 保存修改
    if st.button("💾 确认修改并保存用户数据"):
        try:
            new_users_config = {}
            for _, row in edited_df.iterrows():
                username = row['用户名']
                new_password = row['密码']
                new_role = row['角色']
                
                if new_password == "********":
                    if username in config['users']:
                         new_password = config['users'][username]['password']
                    else:
                        st.error(f"用户 {username} 配置错误，无法获取原始密码。")
                        return

                if not new_password:
                    st.error(f"用户 {username} 的密码不能为空，请修正！")
                    return
                
                new_users_config[username] = {"password": new_password, "role": new_role}

            if not any(data['role'] == 'SuperAdmin' for data in new_users_config.values()):
                st.error("保存失败：系统中必须至少保留一个 'SuperAdmin' 角色！")
                return

            config['users'] = new_users_config
            save_config(config)
            st.success("✅ 用户资料修改已成功保存！")
            time.sleep(1)
            st.experimental_rerun()
            
        except Exception as e:
            st.error(f"保存失败：{e}")
            
    st.markdown("---")

    # 3. 添加/删除用户
    st.markdown("##### 添加/删除用户")

    user_action = st.radio("操作", ["添加/更新", "删除用户"], key="user_action")

    if user_action == "添加/更新":
        with st.form("add_user_form", clear_on_submit=True):
            new_username = st.text_input("用户名 (唯一)", key="new_user_name").strip().lower()
            new_password = st.text_input("密码", type="password", key="new_user_password")
            new_role = st.selectbox("角色", ["SuperAdmin", "Leader", "Referee"], key="new_user_role", index=2)
            
            submitted = st.form_submit_button("添加/更新用户")
            
            if submitted:
                if not new_username or not new_password:
                    st.error("用户名和密码不能为空。")
                else:
                    config['users'][new_username] = {"password": new_password, "role": new_role}
                    save_config(config)
                    st.success(f"用户 **{new_username}** ({new_role}) 已成功添加/更新。")
                    st.experimental_rerun()
    
    elif user_action == "删除用户":
        deletable_users = [u for u in config['users'].keys() if u != st.session_state.username]
        
        if not deletable_users:
            st.warning("系统中没有其他用户可供删除。")
            return
            
        user_to_delete = st.selectbox("选择要删除的用户", options=deletable_users, key="user_to_delete")
        
        if st.button(f"🔴 确认删除用户 {user_to_delete}", type="secondary"):
            if user_to_delete in config['users']:
                del config['users'][user_to_delete]
                save_config(config)
                st.success(f"用户 **{user_to_delete}** 已成功删除。")
                st.experimental_rerun()
                
def display_admin_data_management(config):
    """管理员数据查看和编辑页面"""
    
    if not check_permission(["SuperAdmin", "Referee"]):
        st.error("您没有权限访问数据管理页面。")
        return
        
    st.header("🔑 数据管理")
    
    management_options = ["数据表 (选手/记录)"]
    if check_permission(["SuperAdmin"]):
        management_options.append("系统配置 (标题/用户/欢迎页)")

    data_select = st.sidebar.radio(
        "选择要管理的项目",
        management_options
    )

    if data_select == "数据表 (选手/记录)":
        st.warning("在此处修改数据需谨慎，任何更改都将直接保存到 CSV 文件中！")
        
        data_table_options = ["选手资料 (athletes)"]
        if check_permission(["SuperAdmin"]):
            data_table_options.append("计时记录 (records)")
            
        data_table_select = st.radio(
            "选择要管理的数据表",
            data_table_options
        )
        
        if data_table_select == "选手资料 (athletes)":
            st.subheader("📝 选手资料编辑")
            df_athletes = load_athletes_data()
            
            display_cols = ['athlete_id', 'department', 'name', 'gender', 'phone', 'username']
            df_display = df_athletes[display_cols].copy()
            
            edited_df_display = st.data_editor(
                df_display,
                num_rows="dynamic",
                column_config={
                    "athlete_id": st.column_config.Column("选手编号", help="必须唯一且不能重复", disabled=False),
                    "username": st.column_config.Column("账号(姓名)", help="由姓名自动生成", disabled=True),
                },
                key="edit_athletes_data",
                use_container_width=True
            )

            if st.button("💾 确认修改并保存选手数据"):
                original_df = load_athletes_data()
                
                merged_df = original_df[['athlete_id', 'password', 'username']].merge(
                    edited_df_display, 
                    on='athlete_id', 
                    how='right', 
                    suffixes=('_orig', '')
                )
                
                merged_df['username'] = merged_df['name'] 
                merged_df['password'] = merged_df['phone']
                
                try:
                    merged_df['athlete_id'] = merged_df['athlete_id'].astype(str).str.strip()
                    
                    if merged_df['athlete_id'].duplicated().any():
                        st.error("保存失败：'athlete_id' 列中存在重复编号！请修正后保存。")
                    elif merged_df['athlete_id'].str.contains(r'[^\d]').any():
                        st.error("保存失败：'athlete_id' 必须是纯数字编号。")
                    elif merged_df['athlete_id'].isin(['', 'nan', 'NaN']).any():
                         st.error("保存失败：'athlete_id' 不能为空。")
                    else:
                        final_save_df = merged_df[['athlete_id', 'department', 'name', 'gender', 'phone', 'username', 'password']]
                        save_athlete_data(final_save_df)
                        st.success("✅ 选手资料修改已成功保存！(
