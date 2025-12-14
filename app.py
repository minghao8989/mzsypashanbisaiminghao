import streamlit as st
import pandas as pd
import os
from datetime import datetime
import time
import json
import re

# --- 1. 配置和数据文件定义 & 安全设置 ---

# 定义数据文件名
ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'
CONFIG_FILE = 'config.json'

LOGIN_PAGE = "系统用户登录"

# 初始化 Session State 以跟踪登录状态、用户信息和页面选择
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'username' not in st.session_state:
    st.session_state.username = None
if 'user_role' not in st.session_state:
    st.session_state.user_role = None
if 'page_selection' not in st.session_state:
    st.session_state.page_selection = "选手登记"


# --- 2. 辅助函数：配置文件的加载与保存 & 权限检查 ---

DEFAULT_CONFIG = {
    "system_title": "梅州市第三人民医院赛事管理系统",
    "registration_title": "梅州市第三人民医院选手资料登记",
    # 默认用户配置
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
            # 合并用户配置，确保默认用户仍在
            return {**DEFAULT_CONFIG, **config, 'users': {**DEFAULT_CONFIG['users'], **config.get('users', {})}}
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


# --- 3. 辅助函数：文件加载与保存 (保持一致) ---

def load_athletes_data():
    """加载选手资料文件，如果不存在或为空，则创建包含表头的空文件"""
    if not os.path.exists(ATHLETES_FILE) or os.path.getsize(ATHLETES_FILE) == 0:
        df = pd.DataFrame(columns=['athlete_id', 'department', 'name', 'gender', 'phone'])
        df.to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig')
        return df
    
    try:
        return pd.read_csv(ATHLETES_FILE, dtype={'athlete_id': str})
    except Exception:
        return pd.DataFrame(columns=['athlete_id', 'department', 'name', 'gender', 'phone'])


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
    
    # 确保只有 Referee/SuperAdmin 或公众才能访问登记
    if not st.session_state.logged_in or check_permission(["SuperAdmin", "Referee"]):
        st.info("请准确填写以下信息，并记住由系统生成的比赛编号。")
        
        # 使用 Streamlit state 来管理表单字段的默认值，以便在成功提交后清空
        if 'department_reg' not in st.session_state: st.session_state.department_reg = ''
        if 'name_reg' not in st.session_state: st.session_state.name_reg = ''
        if 'gender_reg' not in st.session_state: st.session_state.gender_reg = '男'
        if 'phone_reg' not in st.session_state: st.session_state.phone_reg = ''
        
        with st.form("registration_form"):
            department = st.text_input("单位/部门", key="department_reg").strip()
            name = st.text_input("姓名", key="name_reg").strip()
            gender = st.selectbox("性别", ["男", "女", "其他"], key="gender_reg")
            phone = st.text_input("手机号 (用于唯一标识)", key="phone_reg").strip()
            
            submitted = st.form_submit_button("提交报名")

            if submitted:
                if not all([department, name, gender, phone]):
                    st.error("请填写所有必填信息。")
                    return

                df_athletes = load_athletes_data()
                
                if phone in df_athletes['phone'].values:
                    st.error(f"该手机号 ({phone}) 已注册，您的比赛编号是：**{df_athletes[df_athletes['phone'] == phone]['athlete_id'].iloc[0]}**。请勿重复提交。")
                    return

                if df_athletes.empty:
                    new_id = 1001
                else:
                    numeric_ids = pd.to_numeric(df_athletes['athlete_id'], errors='coerce').dropna()
                    new_id = int(numeric_ids.max()) + 1 if not numeric_ids.empty else 1001
                
                new_id_str = str(new_id)

                new_athlete = pd.DataFrame([{
                    'athlete_id': new_id_str,
                    'department': department,
                    'name': name,
                    'gender': gender,
                    'phone': phone
                }])

                df_athletes = pd.concat([df_athletes, new_athlete], ignore_index=True)
                save_athlete_data(df_athletes)

                st.success(f"🎉 报名成功! 您的比赛编号是：**{new_id_str}**。请牢记此编号用于比赛计时。")

                # 清空输入框以准备下一次报名
                st.session_state.department_reg = ''
                st.session_state.name_reg = ''
                st.session_state.gender_reg = '男'
                st.session_state.phone_reg = ''
                st.experimental_rerun()
    else:
        st.error("您没有权限进行选手登记操作。")


# --- 6. 页面函数：计时扫码 (Referee/SuperAdmin Access) ---

def display_timing_scanner(config):
    """计时扫码页面"""
    
    if not check_permission(["SuperAdmin", "Referee"]):
        st.error("您没有权限访问计时扫码终端。")
        return

    if 'scan_athlete_id_input' not in st.session_state:
        st.session_state.scan_athlete_id_input = ""
        
    checkpoint_type = st.sidebar.selectbox(
        "选择检查点类型",
        ['START (起点)', 'MID (中途)', 'FINISH (终点)'],
        key='checkpoint_select'
    ).split(' ')[0].upper()

    st.header(f"⏱️ {config['system_title'].replace('赛事管理系统', '').strip()} {checkpoint_type} 计时终端")
    st.subheader(f"当前检查点: {checkpoint_type}")
    st.info("请在此处输入选手的比赛编号进行计时。")

    with st.form("timing_form", clear_on_submit=True):
        athlete_id = st.text_input("输入选手比赛编号", key="scan_athlete_id_input", max_chars=4).strip()
        
        submitted = st.form_submit_button(f"提交 {checkpoint_type} 计时")

        if submitted:
            if not athlete_id:
                st.error("请输入选手编号。")
                return

            df_athletes = load_athletes_data()
            if athlete_id not in df_athletes['athlete_id'].values:
                st.error(f"编号 {athlete_id} 不存在，请检查是否已报名。")
                return

            df_records = load_records_data()

            existing_records = df_records[
                (df_records['athlete_id'] == athlete_id) &
                (df_records['checkpoint_type'] == checkpoint_type)
            ]

            if not existing_records.empty:
                st.warning(f"该选手已在 {checkpoint_type} 扫码成功，请勿重复操作！")
                return
            
            # --- 提交新记录 ---
            current_time = datetime.now()
            
            new_record = pd.DataFrame({
                'athlete_id': [athlete_id],
                'checkpoint_type': [checkpoint_type],
                'timestamp': [current_time]
            })
            
            df_records = pd.concat([df_records, new_record], ignore_index=True)
            save_records_data(df_records)

            name = df_athletes[df_athletes['athlete_id'] == athlete_id]['name'].iloc[0]

            success_message = f"恭喜 **{name}**！{checkpoint_type} 计时成功！记录时间：**{current_time.strftime('%H:%M:%S.%f')[:-3]}**"
            st.success(success_message)
            
            # 自动清空输入框
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
        "registration_title": st.session_state.new_reg_title
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
    
    # 密码显示切换开关
    show_passwords = st.checkbox("🔑 显示所有用户密码", key="show_passwords_toggle")
    
    # 1. 显示现有用户（集成密码更改功能）
    st.markdown("##### 现有系统用户列表 (可直接修改密码和角色)")
    
    user_list = []
    for user, data in config['users'].items():
        user_list.append({
            "用户名": user,
            "角色": data['role'],
            # 只有勾选了显示密码，才显示实际密码，否则显示星号
            "密码": data['password'] if show_passwords else "********"
        })
        
    df_users = pd.DataFrame(user_list)
    
    # 使用 data_editor 实现密码和角色的直接修改
    edited_df = st.data_editor(
        df_users,
        key="edit_users_data",
        num_rows="disabled",
        column_config={
            "用户名": st.column_config.Column("用户名", disabled=True), # 用户名不允许修改
            "角色": st.column_config.SelectboxColumn(
                "角色", options=["SuperAdmin", "Leader", "Referee"]
            ),
            "密码": st.column_config.Column(
                "密码",
                help="点击单元格可直接修改密码。请勿使用空密码。",
                # 当密码隐藏时，禁止在表格中直接修改，需先显示密码
                disabled=not show_passwords 
            )
        },
        use_container_width=True
    )
    
    # 2. 保存修改
    if st.button("💾 确认修改并保存用户数据"):
        try:
            new_users_config = {}
            # 遍历编辑后的DataFrame，检查数据并更新配置
            for _, row in edited_df.iterrows():
                username = row['用户名']
                new_password = row['密码']
                new_role = row['角色']
                
                # 如果密码被隐藏且没有修改 ('********' 或禁用修改)，则保留原密码
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

            # 检查是否有 SuperAdmin 权限被错误移除
            if not any(data['role'] == 'SuperAdmin' for data in new_users_config.values()):
                st.error("保存失败：系统中必须至少保留一个 'SuperAdmin' 角色！")
                return

            # 更新整个配置文件的用户部分
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
        # 排除当前登录用户
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
    
    # 根据用户角色显示不同的管理项
    management_options = ["数据表 (选手/记录)"]
    if check_permission(["SuperAdmin"]):
        management_options.append("系统配置 (标题/用户)")

    data_select = st.sidebar.radio(
        "选择要管理的项目",
        management_options
    )

    if data_select == "数据表 (选手/记录)":
        st.warning("在此处修改数据需谨慎，任何更改都将直接保存到 CSV 文件中！")
        
        # 裁判只能编辑选手资料，不能编辑计时记录
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
            
            edited_df = st.data_editor(
                df_athletes,
                num_rows="dynamic",
                column_config={
                    "athlete_id": st.column_config.Column("选手编号", help="必须唯一且不能重复", disabled=False),
                },
                key="edit_athletes_data",
                use_container_width=True
            )

            if st.button("💾 确认修改并保存选手数据"):
                try:
                    edited_df['athlete_id'] = edited_df['athlete_id'].astype(str).str.strip()
                    
                    if edited_df['athlete_id'].duplicated().any():
                        st.error("保存失败：'athlete_id' 列中存在重复编号！请修正后保存。")
                    elif edited_df['athlete_id'].str.contains(r'[^\d]').any():
                        st.error("保存失败：'athlete_id' 必须是纯数字编号。")
                    elif edited_df['athlete_id'].isin(['', 'nan', 'NaN']).any():
                         st.error("保存失败：'athlete_id' 不能为空。")
                    else:
                        save_athlete_data(edited_df)
                        st.success("✅ 选手资料修改已成功保存！")
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
    elif data_select == "系统配置 (标题/用户)":
        
        config_option = st.radio("选择配置项", ["修改系统标题", "用户权限管理"])

        if config_option == "修改系统标题":
            st.subheader("⚙️ 系统标题与配置修改")
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
    """登录成功后设置状态并跳转页面"""
    username = st.session_state.login_username_input.strip().lower()
    password = st.session_state.login_password_input
    
    if username in config['users'] and config['users'][username]['password'] == password:
        st.session_state.logged_in = True
        st.session_state.username = username
        st.session_state.user_role = config['users'][username]['role']
        
        # 根据角色设置默认跳转页面
        role = st.session_state.user_role
        if role in ["SuperAdmin", "Referee"]:
            st.session_state.page_selection = "计时扫码"
        elif role == "Leader":
            st.session_state.page_selection = "排名结果"
        
        st.experimental_rerun()
    else:
        st.session_state.logged_in = False
        st.session_state.user_role = None

def display_login_page(config):
    """系统用户登录页面"""
    st.header("🔑 系统用户登录")
    st.info("请输入您的用户名和密码以访问对应功能。")
    
    with st.form("login_form"):
        username = st.text_input("用户名", key="login_username_input")
        password = st.text_input("密码", type="password", key="login_password_input")
        
        submitted = st.form_submit_button("登录")
        
        if submitted:
            set_login_success(config) 

            if not st.session_state.logged_in:
                 st.error("用户名或密码错误，请重试。")


def display_logout_button():
    """退出登录按钮"""
    def set_logout():
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.user_role = None
        st.session_state.page_selection = "选手登记"
        
    if st.sidebar.button("退出登录", on_click=set_logout):
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
    pages = ["选手登记"]
    
    if st.session_state.logged_in:
        role = st.session_state.user_role
        st.sidebar.write(f"用户：**{st.session_state.username}** ({role})")

        # 裁判和超级管理员
        if role in ["SuperAdmin", "Referee"]:
            pages.append("计时扫码")
        
        # 领导和超级管理员
        if role in ["SuperAdmin", "Leader"]:
            pages.append("排名结果")
            
        # 裁判和超级管理员 (裁判只能编辑数据表)
        if role in ["SuperAdmin", "Referee"]:
            pages.append("数据管理")
        
        # 超级管理员独有
        if role == "SuperAdmin":
            pages.append("归档与重置")
            
        display_logout_button()
    else:
        pages.append(LOGIN_PAGE)

    # 4. 确保当前的页面选择在可用列表中
    if st.session_state.page_selection not in pages:
        st.session_state.page_selection = pages[0]
    
    # 5. 导航栏
    page_index = pages.index(st.session_state.page_selection) if st.session_state.page_selection in pages else 0
    page = st.sidebar.radio("选择功能模块", pages,
                            index=page_index,
                            key='page_selection')

    # 6. 路由 (根据权限显示内容)
    if page == "选手登记":
        display_registration_form(config)
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
