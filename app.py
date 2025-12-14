import streamlit as st
import pandas as pd
import os
from datetime import datetime
import time
import json
import re

# --- 1. 配置和数据文件定义 & 常量 ---

ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'
CONFIG_FILE = 'config.json'

LOGIN_PAGE = "系统用户登录"
ATHLETE_LOGIN_PAGE = "选手登录"
ATHLETE_WELCOME_PAGE = "选手欢迎页"

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


# --- 2. 辅助函数：配置文件的加载与保存 & 权限检查 ---

DEFAULT_CONFIG = {
    "system_title": "梅州市第三人民医院赛事管理系统",
    "registration_title": "梅州市第三人民医院选手资料登记",
    "athlete_welcome_title": "恭喜您报名成功！",
    "athlete_welcome_message": "感谢您积极参加本单位的赛事活动，祝您能够取得好成绩。",
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


# --- 3. 辅助函数：文件加载与保存 ---

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

# --- 4. 核心计算与格式化函数 (保持一致) ---

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


# --- 5. 页面函数：选手登记 (Public/Referee Access) ---

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
    
    # 【核心修复】使用 clear_on_submit=True 自动清理表单输入，并移除 key 属性以避免 Session State 冲突
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
            
            st.experimental_rerun()


# --- 5.5 新增：选手欢迎页面 ---
def display_athlete_welcome_page(config):
    """选手登录成功后显示的欢迎页面"""
    if not st.session_state.athlete_logged_in:
        st.error("请先登录选手账号。")
        return
        
    st.header(f"🎉 {config['athlete_welcome_title']}")
    
    # 自定义消息显示
    st.markdown(f"""
        <div style="padding: 15px; border-radius: 5px; background-color: #f0f2f6; border-left: 5px solid #00c0f2;">
            <p style="font-size: 1.1em; margin: 0;">{config['athlete_welcome_message']}</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    st.subheader("您的签到凭证")
    
    # 查找当前登录选手的信息
    df_athletes = load_athletes_data()
    current_athlete = df_athletes[df_athletes['username'] == st.session_state.athlete_username]
    
    if current_athlete.empty:
        st.error("错误：未找到该选手信息。请联系管理员。")
        return
        
    current_athlete = current_athlete.iloc[0]
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("您的比赛编号", current_athlete['athlete_id'])
    with col2:
        st.metric("签到账号 (姓名)", current_athlete['username'])
        
    st.info("请前往**计时扫码**终端，使用您的姓名和手机号进行比赛签到。")


# --- 6. 页面函数：计时扫码 (Referee/SuperAdmin Access) ---

def display_timing_scanner(config):
    """
    计时扫码页面改为使用选手的账号(姓名)和密码(手机号)进行签到验证。
    """
    
    if not check_permission(["SuperAdmin", "Referee"]):
        st.error("您没有权限访问计时扫码终端。")
        return

    checkpoint_type = st.sidebar.selectbox(
        "选择检查点类型",
        ['START (起点)', 'MID (中途)', 'FINISH (终点)'],
        key='checkpoint_select'
    ).split(' ')[0].upper()

    st.header(f"⏱️ {config['system_title'].replace('赛事管理系统', '').strip()} {checkpoint_type} 计时签到")
    st.subheader(f"当前检查点: {checkpoint_type}")
    st.info("选手请使用 **姓名** 作为账号，**手机号** 作为密码进行签到。")

    with st.form("timing_form", clear_on_submit=True):
        athlete_username = st.text_input("账号 (姓名)", key="scan_username").strip()
        athlete_password = st.text_input("密码 (手机号)", type="password", key="scan_password").strip()
        
        submitted = st.form_submit_button(f"提交 {checkpoint_type} 签到")

        if submitted:
            if not athlete_username or not athlete_password:
                st.error("请输入完整的账号和密码。")
                return

            df_athletes = load_athletes_data()
            
            # 1. 验证账号和密码
            verified_athlete = df_athletes[
                (df_athletes['username'] == athlete_username) & 
                (df_athletes['password'] == athlete_password)
            ]
            
            if verified_athlete.empty:
                st.error(f"账号或密码错误，请检查您的姓名和手机号是否正确。")
                return
            
            # 2. 获取选手信息
            athlete_id = verified_athlete['athlete_id'].iloc[0]
            name = verified_athlete['name'].iloc[0]

            # 3. 检查是否重复扫码
            df_records = load_records_data()
            existing_records = df_records[
                (df_records['athlete_id'] == athlete_id) &
                (df_records['checkpoint_type'] == checkpoint_type)
            ]

            if not existing_records.empty:
                st.warning(f"选手 **{name}** 已在 {checkpoint_type} 签到成功，请勿重复操作！")
                return
            
            # 4. 提交新记录
            current_time = datetime.now()
            
            new_record = pd.DataFrame({
                'athlete_id': [athlete_id],
                'checkpoint_type': [checkpoint_type],
                'timestamp': [current_time]
            })
            
            df_records = pd.concat([df_records, new_record], ignore_index=True)
            save_records_data(df_records)

            success_message = f"恭喜 **{name}** (编号: {athlete_id})！{checkpoint_type} 签到成功！记录时间：**{current_time.strftime('%H:%M:%S.%f')[:-3]}**"
            st.success(success_message)
            
            st.experimental_rerun()


# --- 7. 页面函数：排名结果 (Leader/SuperAdmin Access) ---

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

# --- 8. 页面函数：管理员数据管理 (Referee/SuperAdmin Access) ---

def save_config_callback():
    """将表单数据保存到 config.json 文件"""
    new_config = {
        "system_title": st.session_state.new_sys_title,
        "registration_title": st.session_state.new_reg_title,
        "athlete_welcome_title": st.session_state.new_welcome_title,
        "athlete_welcome_message": st.session_state.new_welcome_message,
    }
    current_config = load_config()
    current_config.update(new_config)
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
                        st.success("✅ 选手资料修改已成功保存！(注意：姓名/手机号修改会同步更新账号/密码)")
                        time.sleep(1)
                        st.experimental_rerun()
                except Exception as e:
                    st.error(f"保存失败：{e}")


        elif data_table_select == "计时记录 (records)":
            st.subheader("⏱️ 计时记录编辑")
            df_records = load_records_data()
            
            st.info("提示：请谨慎修改时间戳。格式应为 YYYY-MM-DD HH:MM:SS.SSSSSS")
            
            edited_df = st.data_editor(
                df_records,
                num_rows="dynamic",
                column_config={
                    "checkpoint_type": st.column_config.Column("检查点类型", help="必须是 START, MID, FINISH 之一"),
                },
                key="edit_records_data",
                use_container_width=True
            )
            
            if st.button("💾 确认修改并保存计时记录"):
                try:
                    edited_df['timestamp'] = pd.to_datetime(edited_df['timestamp'], errors='raise')
                    
                    if not edited_df['checkpoint_type'].isin(['START', 'MID', 'FINISH']).all():
                        st.error("保存失败：'checkpoint_type' 列包含无效值，必须是 START, MID, FINISH 之一。")
                        return
                        
                    save_records_data(edited_df)
                    st.success("✅ 计时记录修改已成功保存！")
                    time.sleep(1)
                    st.experimental_rerun()
                except ValueError:
                    st.error("保存失败：'timestamp' 列的日期时间格式不正确，请确保格式正确（如 YYYY-MM-DD HH:MM:SS.SSSSSS）。")
                except Exception as e:
                    st.error(f"保存失败：{e}")

    # --- 系统配置修改页面 ---
    elif data_select == "系统配置 (标题/用户/欢迎页)":
        
        config_option = st.radio("选择配置项", ["修改系统标题", "用户权限管理", "选手欢迎页配置"])

        if config_option == "修改系统标题":
            st.subheader("⚙️ 系统标题与登记页配置修改")
            st.info("修改以下配置项后，点击保存，系统将自动重新加载以应用新标题。")

            with st.form("config_form"):
                st.text_input(
                    "系统主标题 (侧边栏顶部和计时页面)",
                    value=config['system_title'],
                    key="new_sys_title"
                )
                
                st.text_input(
                    "选手登记页面标题",
                    value=config['registration_title'],
                    key="new_reg_title"
                )

                if st.form_submit_button("✅ 保存并应用配置", on_click=save_config_callback):
                    st.success("配置已保存！系统正在重新加载...")
                    time.sleep(1)
                    st.experimental_rerun()
        
        elif config_option == "选手欢迎页配置":
            st.subheader("📝 选手登录成功后提示信息配置")
            st.info("配置选手使用账号密码登录成功后，在‘选手欢迎页’中显示的标题和说明文字。")
            
            with st.form("welcome_config_form"):
                st.text_input(
                    "欢迎页标题 (第一栏)",
                    value=config['athlete_welcome_title'],
                    key="new_welcome_title"
                )
                st.text_area(
                    "欢迎页说明文字 (第二栏)",
                    value=config['athlete_welcome_message'],
                    key="new_welcome_message"
                )
                
                if st.form_submit_button("✅ 保存欢迎页配置", on_click=save_config_callback):
                    st.success("欢迎页配置已保存！")
                    time.sleep(1)
                    st.experimental_rerun()


        elif config_option == "用户权限管理":
            display_user_management(config)


# --- 9. 页面函数：归档与重置 (SuperAdmin Access) ---

def archive_and_reset_race_data():
    """将当前数据归档，并清空活动文件以便开始新的比赛。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    athletes_archived = False
    records_archived = False

    if os.path.exists(ATHLETES_FILE) and os.path.getsize(ATHLETES_FILE) > 0:
        new_archive_name = f"ARCHIVE_ATHLETES_{timestamp}.csv"
        os.rename(ATHLETES_FILE, new_archive_name)
        athletes_archived = True
    
    if os.path.exists(RECORDS_FILE) and os.path.getsize(RECORDS_FILE) > 0:
        new_archive_name = f"ARCHIVE_RECORDS_{timestamp}.csv"
        os.rename(RECORDS_FILE, new_archive_name)
        records_archived = True

    # 重新创建空文件
    load_athletes_data()
    load_records_data()
    
    return athletes_archived or records_archived

def get_archived_files():
    """查找所有已归档的历史数据文件。"""
    files = os.listdir('.')
    archived = [f for f in files if f.startswith('ARCHIVE_')]
    athletes_archives = sorted([f for f in archived if f.startswith('ARCHIVE_ATHLETES_')], reverse=True)
    return athletes_archives


def display_archive_reset():
    """比赛数据归档与重置页面"""
    
    if not check_permission(["SuperAdmin"]):
        st.error("您没有权限访问归档与重置功能。")
        return

    st.header("🗄️ 比赛归档与重置 (重要操作)")
    
    st.subheader("⚠️ 1. 结束当前比赛并归档数据")
    st.warning("此操作将把当前的选手和计时数据归档，并清空当前比赛记录！请确保当前比赛已结束。")
    
    if st.button("🚀 归档并重置系统", type="primary"):
        with st.spinner("正在归档数据..."):
            if archive_and_reset_race_data():
                st.success(f"✅ 数据归档成功！新比赛已准备就绪。")
                st.info("归档文件已创建，请在下方的历史记录中查看。")
                time.sleep(1)
                st.experimental_rerun()
            else:
                st.error("归档失败或当前数据为空。")

    st.markdown("---")

    st.subheader("📜 2. 历史比赛数据查询")
    athletes_archives = get_archived_files()
    
    if not athletes_archives:
        st.info("暂无历史比赛归档数据。")
        return

    display_names = [f"文件: {f}" for f in athletes_archives]
    selected_display_name = st.selectbox(
        "选择要查询的选手归档文件 (日期/时间最新在前)",
        options=display_names,
        key="archive_athlete_file"
    )
    selected_athlete_file = athletes_archives[display_names.index(selected_display_name)]
    selected_record_file = selected_athlete_file.replace("ATHLETES", "RECORDS")
    
    try:
        if not os.path.exists(selected_record_file):
             st.warning(f"警告：找不到对应的计时记录文件: {selected_record_file}。将仅显示选手列表。")
             df_history_athletes = pd.read_csv(selected_athlete_file, dtype={'athlete_id': str})
             st.subheader(f"👥 历史选手列表 ({len(df_history_athletes)} 人)")
             st.dataframe(df_history_athletes, hide_index=True)
             return

        df_history_athletes = pd.read_csv(selected_athlete_file, dtype={'athlete_id': str})
        df_history_records = pd.read_csv(selected_record_file, parse_dates=['timestamp'], dtype={'athlete_id': str})
        
        st.success(f"成功加载归档文件：{selected_athlete_file} 和 {selected_record_file}")
        
        df_history_calculated = calculate_net_time(df_history_records)
        df_history_final = df_history_calculated.merge(df_history_athletes, on='athlete_id', how='left')
        
        st.subheader(f"📊 历史比赛统计")
        
        if not df_history_final.empty:
            df_history_final = df_history_final.sort_values(by='total_time_sec', ascending=True).reset_index(drop=True)
            df_history_final['排名'] = df_history_final.index + 1
            df_history_final['总用时'] = df_history_final['total_time_sec'].apply(format_time)
            
            st.dataframe(
                df_history_final[['排名', 'name', 'department', '总用时']].head(20),
                caption="历史比赛排名前20 (完整排名请下载)",
                hide_index=True
            )
            
            csv_data = df_history_final.to_csv(encoding='utf-8-sig', index=False)
            st.download_button(
                label=f"💾 下载 {selected_athlete_file} 完整的历史排名数据",
                data=csv_data,
                file_name=f"RANKING_{selected_athlete_file}",
                mime="text/csv"
            )

        else:
            st.info("该历史文件中未找到完整的完赛记录。")
            
    except FileNotFoundError:
        st.error("错误：找不到对应的历史记录文件。")
    except Exception as e:
        st.error(f"加载历史数据时发生错误：{e}")


# --- 10. 页面函数：用户登录与登出 ---

def set_login_success(config):
    """设置管理员/裁判/领导的登录状态"""
    username = st.session_state.login_username_input.strip().lower()
    password = st.session_state.login_password_input
    
    if username in config['users'] and config['users'][username]['password'] == password:
        st.session_state.logged_in = True
        st.session_state.username = username
        st.session_state.user_role = config['users'][username]['role']
    else:
        st.session_state.logged_in = False
        st.session_state.user_role = None

def set_athlete_login_success():
    """设置选手的登录状态"""
    athlete_username = st.session_state.athlete_login_username_input.strip()
    athlete_password = st.session_state.athlete_login_password_input.strip()
    
    df_athletes = load_athletes_data()
    
    verified_athlete = df_athletes[
        (df_athletes['username'] == athlete_username) & 
        (df_athletes['password'] == athlete_password)
    ]
    
    if not verified_athlete.empty:
        st.session_state.athlete_logged_in = True
        st.session_state.athlete_username = athlete_username
    else:
        st.session_state.athlete_logged_in = False
        st.session_state.athlete_username = None

def display_login_page(config):
    """系统用户登录页面 (管理员/裁判/领导)"""
    st.header("🔑 系统用户登录")
    st.info("请输入您的用户名和密码以访问对应管理功能。")
    
    is_login_attempted = False
    
    with st.form("login_form"):
        username = st.text_input("用户名", key="login_username_input")
        password = st.text_input("密码", type="password", key="login_password_input")
        
        submitted = st.form_submit_button("登录", on_click=lambda: set_login_success(config))
        
        if submitted:
            is_login_attempted = True
    
    if is_login_attempted:
        if st.session_state.logged_in:
            st.success("登录成功！正在进入功能页面...")
            
            # 根据角色设置 page_selection
            role = st.session_state.user_role
            if role in ["SuperAdmin", "Referee"]:
                st.session_state.page_selection = "计时扫码"
            elif role == "Leader":
                st.session_state.page_selection = "排名结果"
            else:
                st.session_state.page_selection = "选手登记"
                
            st.session_state.login_password_input = "" 
            time.sleep(1)
            st.experimental_rerun()
        else:
            st.error("用户名或密码错误，请重试。")
            st.session_state.login_password_input = ""


def display_athlete_login_page(config):
    """选手账号登录页面"""
    st.header("🏃 选手账号登录")
    st.info("选手请使用 **姓名** 作为账号，**手机号** 作为密码进行登录。")
    
    is_login_attempted = False
    
    with st.form("athlete_login_form"):
        username = st.text_input("账号 (姓名)", key="athlete_login_username_input")
        password = st.text_input("密码 (手机号)", type="password", key="athlete_login_password_input")
        
        submitted = st.form_submit_button("登录", on_click=set_athlete_login_success)
        
        if submitted:
            is_login_attempted = True
    
    if is_login_attempted:
        if st.session_state.athlete_logged_in:
            st.success("登录成功！正在进入欢迎页面...")
            st.session_state.page_selection = ATHLETE_WELCOME_PAGE
            
            st.session_state.athlete_login_password_input = "" 
            time.sleep(1)
            st.experimental_rerun()
        else:
            st.error("账号或密码错误，请检查您的姓名和手机号是否正确。")
            st.session_state.athlete_login_password_input = ""


def display_logout_button():
    """退出登录按钮 (管理员/裁判/领导)"""
    def set_logout():
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.user_role = None
        st.session_state.page_selection = "选手登记"
        
    if st.sidebar.button("退出管理账号", on_click=set_logout):
        st.experimental_rerun()

def display_athlete_logout_button():
    """退出登录按钮 (选手)"""
    def set_athlete_logout():
        st.session_state.athlete_logged_in = False
        st.session_state.athlete_username = None
        st.session_state.page_selection = "选手登记"
        
    if st.sidebar.button("退出选手账号", on_click=set_athlete_logout):
        st.experimental_rerun()


# --- 11. Streamlit 主应用入口 ---

def main_app():
    # 1. 加载配置和数据
    config = load_config()
    load_athletes_data()
    load_records_data()
    
    # 2. 侧边栏标题使用配置
    st.sidebar.title(f"🏁 {config['system_title']}")
    
    # 3. 定义导航列表 (根据权限动态生成)
    
    pages = ["选手登记"] # 始终保留登记页作为起点
    
    # 选手已登录
    if st.session_state.athlete_logged_in:
        st.sidebar.write(f"当前选手：**{st.session_state.athlete_username}**")
        pages = [ATHLETE_WELCOME_PAGE] # 选手登录后，只显示欢迎页
        display_athlete_logout_button()
    
    # 管理员/系统用户已登录
    elif st.session_state.logged_in:
        role = st.session_state.user_role
        st.sidebar.write(f"管理用户：**{st.session_state.username}** ({role})")
        
        pages = ["选手登记"] # 管理员/裁判也应该能看到登记页

        # 权限页面
        if role in ["SuperAdmin", "Referee"]: pages.append("计时扫码")
        if role in ["SuperAdmin", "Leader"]: pages.append("排名结果")
        if role in ["SuperAdmin", "Referee"]: pages.append("数据管理")
        if role == "SuperAdmin": pages.append("归档与重置")
            
        display_logout_button()
        
    # 未登录 (默认显示登记、选手登录、管理员登录)
    else:
        pages.append(ATHLETE_LOGIN_PAGE)
        pages.append(LOGIN_PAGE)


    # 4. 确保当前的页面选择在可用列表中
    if st.session_state.page_selection not in pages:
        # 如果当前页面不在权限列表中，默认跳转到第一个有权限的页面
        st.session_state.page_selection = pages[0]
    
    # 5. 导航栏
    page_index = pages.index(st.session_state.page_selection) if st.session_state.page_selection in pages else 0
    page = st.sidebar.radio("选择功能模块", pages,
                            index=page_index,
                            key='page_selection')

    # 6. 路由 (根据权限显示内容)
    if page == "选手登记":
        display_registration_form(config)
    elif page == ATHLETE_LOGIN_PAGE:
        display_athlete_login_page(config)
    elif page == ATHLETE_WELCOME_PAGE:
        display_athlete_welcome_page(config)
    elif page == LOGIN_PAGE:
        display_login_page(config)
    elif page == "计时扫码":
        if check_permission(["SuperAdmin", "Referee"]):
            display_timing_scanner(config)
        else:
            st.error("您无权访问计时扫码功能，请联系管理员。")
    elif page == "排名结果":
        if check_permission(["SuperAdmin", "Leader"]):
            display_results_ranking()
        else:
            st.error("您无权访问排名结果。")
    elif page == "数据管理":
        if check_permission(["SuperAdmin", "Referee"]):
            display_admin_data_management(config)
        else:
            st.error("您无权访问数据管理。")
    elif page == "归档与重置":
        if check_permission(["SuperAdmin"]):
            display_archive_reset()
        else:
            st.error("您无权访问归档与重置。")

    st.sidebar.markdown("---")
    st.sidebar.info("数据下载和修改请前往 '数据管理' 模块。")


if __name__ == '__main__':
    # 预加载配置，用于设置浏览器标签页标题
    initial_config = load_config()
    
    st.set_page_config(
        page_title=initial_config['system_title'],
        page_icon="🏃",
        layout="wide"
    )
    main_app()
