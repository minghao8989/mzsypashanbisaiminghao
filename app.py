import streamlit as st
import pandas as pd
import os
from datetime import datetime
import time
import json
import re # 用于更精确地验证 athlete_id

# --- 1. 配置和数据文件定义 & 安全设置 ---

# 定义数据文件名
ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'
CONFIG_FILE = 'config.json'

# 【重要安全设置】管理员密码
# !!! 安全警告：在生产环境中，请不要将密码硬编码在代码中！
# 建议使用 Streamlit Secrets 或环境变量来安全存储密码。
ADMIN_PASSWORD = "123"
LOGIN_PAGE = "管理员登录"

# 初始化 Session State 以跟踪登录状态和页面选择
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
# 确保在用户未登录时默认进入公共页面
if 'page_selection' not in st.session_state or (not st.session_state.logged_in and st.session_state.page_selection not in ["选手登记", LOGIN_PAGE]):
    st.session_state.page_selection = "选手登记"


# --- 2. 辅助函数：配置文件的加载与保存 ---

DEFAULT_CONFIG = {
    "system_title": "梅州市第三人民医院赛事管理系统",
    "registration_title": "梅州市第三人民医院选手资料登记"
}

def load_config():
    """加载配置数据，如果文件不存在或出错，则创建默认配置"""
    if not os.path.exists(CONFIG_FILE) or os.path.getsize(CONFIG_FILE) == 0:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            # 确保加载的配置包含所有默认字段
            return {**DEFAULT_CONFIG, **config}
    except Exception:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

def save_config(config_data):
    """保存配置数据到 JSON 文件"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)


# --- 3. 辅助函数：文件加载与保存 ---

def load_athletes_data():
    """加载选手资料文件，如果不存在或为空，则创建包含表头的空文件"""
    # 强制 athlete_id 为 str 类型
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
    # 强制 athlete_id 为 str 类型
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

    # 确保时间戳是 datetime 类型，且 athlete_id 是 str 类型
    df_records['timestamp'] = pd.to_datetime(df_records['timestamp'], errors='coerce')
    df_records['athlete_id'] = df_records['athlete_id'].astype(str)
    df_records.dropna(subset=['timestamp'], inplace=True)

    # 取每个检查点的最小时间（确保不会重复计时）
    timing_pivot = df_records.groupby(['athlete_id', 'checkpoint_type'])['timestamp'].min().reset_index()
    timing_pivot = timing_pivot.pivot_table(index='athlete_id', columns='checkpoint_type', values='timestamp', aggfunc='first')
    
    df_results = timing_pivot.dropna(subset=['START', 'FINISH']).copy()
    
    # 只有 FINISH 晚于 START 的记录才有效
    df_results = df_results[df_results['FINISH'] > df_results['START']]

    df_results['total_time_sec'] = (df_results['FINISH'] - df_results['START']).dt.total_seconds()

    df_results['segment1_sec'] = None
    df_results['segment2_sec'] = None
    
    # 仅对存在 MID 记录的选手计算分段用时
    valid_mid = df_results['MID'].notna()
    
    # 只有 MID 在 START 和 FINISH 之间才有效
    valid_mid = valid_mid & (df_results['MID'] > df_results['START']) & (df_results['MID'] < df_results['FINISH'])
    
    df_results.loc[valid_mid, 'segment1_sec'] = (df_results['MID'] - df_results['START']).dt.total_seconds()
    df_results.loc[valid_mid, 'segment2_sec'] = (df_results['FINISH'] - df_results['MID']).dt.total_seconds()
    
    return df_results.reset_index()


def format_time(seconds):
    """格式化秒数到 MM:SS.mmm"""
    if pd.isna(seconds) or seconds is None or seconds < 0: # 增加负数检查
        return 'N/A'
    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    return f"{minutes:02d}:{remaining_seconds:06.3f}"


# --- 5. 页面函数：选手登记 (Public Access) ---

def display_registration_form(config):
    """选手资料登记页面"""
    st.header(f"👤 {config['registration_title']}")
    st.info("请准确填写以下信息，并记住由系统生成的比赛编号。")

    # 使用 Streamlit state 来管理表单字段的默认值，以便在成功提交后清空
    if 'department' not in st.session_state:
        st.session_state.department = ''
    if 'name' not in st.session_state:
        st.session_state.name = ''
    if 'gender' not in st.session_state:
        st.session_state.gender = '男'
    if 'phone' not in st.session_state:
        st.session_state.phone = ''
        
    with st.form("registration_form"):
        department = st.text_input("单位/部门", key="department").strip()
        name = st.text_input("姓名", key="name").strip()
        gender = st.selectbox("性别", ["男", "女", "其他"], key="gender")
        phone = st.text_input("手机号 (用于唯一标识)", key="phone").strip()
        
        submitted = st.form_submit_button("提交报名")

        if submitted:
            if not all([department, name, gender, phone]):
                st.error("请填写所有必填信息。")
                return

            df_athletes = load_athletes_data()
            
            # 检查手机号是否已注册
            if phone in df_athletes['phone'].values:
                st.error(f"该手机号 ({phone}) 已注册，您的比赛编号是：**{df_athletes[df_athletes['phone'] == phone]['athlete_id'].iloc[0]}**。请勿重复提交。")
                return

            # 生成新的唯一 ID (从 1001 开始)
            if df_athletes.empty:
                new_id = 1001
            else:
                # 过滤非数字 ID，确保新 ID 的生成是基于数字最大值的
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
            st.session_state.department = ''
            st.session_state.name = ''
            st.session_state.gender = '男'
            st.session_state.phone = ''
            st.experimental_rerun() # 重新运行以清空表单字段


# --- 6. 页面函数：计时扫码 (Private Access) ---

def display_timing_scanner(config):
    """计时扫码页面"""
    
    # 确保在 session_state 中有 scan_athlete_id
    if 'scan_athlete_id' not in st.session_state:
        st.session_state.scan_athlete_id = ""
        
    checkpoint_type = st.sidebar.selectbox(
        "选择检查点类型",
        ['START (起点)', 'MID (中途)', 'FINISH (终点)'],
        key='checkpoint_select'
    ).split(' ')[0].upper()

    st.header(f"⏱️ {config['system_title'].replace('赛事管理系统', '').strip()} {checkpoint_type} 计时终端")
    st.subheader(f"当前检查点: {checkpoint_type}")
    st.info("请在此处输入选手的比赛编号进行计时。")

    with st.form("timing_form", clear_on_submit=True):
        # 使用 st.session_state.scan_athlete_id 作为 key 的值，以便在成功后清空
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

            # 检查是否重复扫码
            existing_records = df_records[
                (df_records['athlete_id'] == athlete_id) &
                (df_records['checkpoint_type'] == checkpoint_type)
            ]

            if not existing_records.empty:
                # 记录已存在，仅在 FINISH 检查是否比现有记录晚
                if checkpoint_type == 'FINISH' and existing_records['timestamp'].iloc[0] > datetime.now():
                    st.warning(f"选手编号 {athlete_id} 的 {checkpoint_type} 已成功记录。")
                else:
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
            
            # 清空输入框以便下一次输入
            st.session_state.scan_athlete_id_input = ""
            st.experimental_rerun()


# --- 7. 页面函数：排名结果 (Private Access) ---

def display_results_ranking():
    """结果统计与排名页面"""
    st.header("🏆 比赛成绩与排名")

    df_records = load_records_data()
    df_athletes = load_athletes_data()
    
    df_calculated = calculate_net_time(df_records)

    if df_calculated.empty:
        st.warning("暂无完整的完赛记录。")
        return

    df_final = df_calculated.merge(df_athletes, on='athlete_id', how='left')

    # 排名逻辑：按总用时升序排序
    df_final = df_final.sort_values(by='total_time_sec', ascending=True).reset_index(drop=True)
    df_final['排名'] = df_final.index + 1
    
    # 格式化时间列
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

    # 下载按钮
    csv_data = df_display.to_csv(encoding='utf-8-sig', index=False)
    st.download_button(
        label="💾 下载完整的排名数据 (.csv)",
        data=csv_data,
        file_name="race_ranking_results.csv",
        mime="text/csv"
    )

# --- 8. 页面函数：管理员数据管理 (Private Access) ---

# 新增回调函数，用于解决 config 保存后的 Attribute Error
def save_config_callback():
    """将表单数据保存到 config.json 文件"""
    new_config = {
        "system_title": st.session_state.new_sys_title,
        "registration_title": st.session_state.new_reg_title
    }
    save_config(new_config)
    # Streamlit 会自动检测文件变化并重新运行，无需手动调用 rerun


def display_admin_data_management(config):
    """管理员数据查看和编辑页面"""
    st.header("🔑 数据管理 (管理员权限)")
    
    data_select = st.sidebar.radio(
        "选择要管理的项目",
        ["数据表 (选手/记录)", "系统配置 (标题)"]
    )

    if data_select == "数据表 (选手/记录)":
        st.warning("在此处修改数据需谨慎，任何更改都将直接保存到 CSV 文件中！")
        data_table_select = st.radio(
            "选择要管理的数据表",
            ["选手资料 (athletes)", "计时记录 (records)"]
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
                    # 严格检查 athlete_id
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
                    # 尝试转换时间戳，如果失败会抛出 ValueError
                    edited_df['timestamp'] = pd.to_datetime(edited_df['timestamp'], errors='raise')
                    
                    # 检查检查点类型是否有效
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
    elif data_select == "系统配置 (标题)":
        st.subheader("⚙️ 系统标题与配置修改")
        st.info("修改以下配置项后，点击保存，系统将自动重新加载以应用新标题。")

        with st.form("config_form"):
            st.text_input(
                "系统主标题 (侧边栏顶部和计时页面)",
                value=config['system_title'],
                key="new_sys_title" # 绑定到 session_state
            )
            
            st.text_input(
                "选手登记页面标题",
                value=config['registration_title'],
                key="new_reg_title" # 绑定到 session_state
            )

            # 使用回调函数，避免直接在表单内部调用文件写入和 rerun 导致的冲突
            if st.form_submit_button("✅ 保存并应用配置", on_click=save_config_callback):
                st.success("配置已保存！系统正在重新加载...")
                time.sleep(1)
                st.experimental_rerun() # 触发一次刷新来应用新的系统标题


# --- 9. 页面函数：归档与重置 (Private Access) ---

def archive_and_reset_race_data():
    """将当前数据归档，并清空活动文件以便开始新的比赛。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 确保归档文件名是唯一的
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
    # 只列出选手档案文件，因为记录文件是配对的
    athletes_archives = sorted([f for f in archived if f.startswith('ARCHIVE_ATHLETES_')], reverse=True)
    return athletes_archives


def display_archive_reset():
    """比赛数据归档与重置页面"""
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
    
    # 根据选手档案文件名推断对应的记录档案文件名
    selected_record_file = selected_athlete_file.replace("ATHLETES", "RECORDS")
    
    try:
        # 检查记录文件是否存在
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
            
            # 下载按钮
            display_cols = ['排名', 'name', 'department', 'athlete_id', '总用时', 'total_time_sec', 'segment1_sec', 'segment2_sec']
            csv_data = df_history_final[display_cols].to_csv(encoding='utf-8-sig', index=False)
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


# --- 10. 页面函数：管理员登录 ---

# 定义登录成功后的回调函数
def set_login_success():
    """登录成功后设置状态并跳转页面"""
    if st.session_state.login_password_input == ADMIN_PASSWORD:
        st.session_state.logged_in = True
        # 默认跳转到计时扫码页面
        st.session_state.page_selection = "计时扫码"
    else:
        st.session_state.logged_in = False

def display_login_page():
    """管理员登录页面"""
    st.header("🔑 管理员登录")
    st.info("请输入管理员密码以访问后台管理功能。")
    
    with st.form("login_form"):
        password = st.text_input("密码", type="password", key="login_password_input")
        
        submitted = st.form_submit_button(
            "登录",
            on_click=set_login_success # 使用回调函数
        )
        
        if submitted:
            if st.session_state.logged_in:
                st.success("登录成功！正在进入后台管理页面...")
                time.sleep(1)
                st.experimental_rerun() # 触发一次刷新
            else:
                st.error("密码错误，请重试。")


def display_logout_button():
    """退出登录按钮"""
    def set_logout():
        st.session_state.logged_in = False
        st.session_state.page_selection = "选手登记"
        
    if st.sidebar.button("退出登录", on_click=set_logout):
        st.experimental_rerun()


# --- 11. Streamlit 主应用入口 ---

def main_app():
    # 1. 加载配置和数据
    config = load_config()
    # 预加载数据，确保文件存在
    load_athletes_data()
    load_records_data()
    
    # 2. 侧边栏标题使用配置
    st.sidebar.title(f"🏁 {config['system_title']}")
    
    # 3. 定义导航列表
    if st.session_state.logged_in:
        pages = ["选手登记", "计时扫码", "排名结果", "数据管理（管理员）", "归档与重置"]
        display_logout_button()
    else:
        pages = ["选手登记", LOGIN_PAGE]

    # 4. 确保当前的页面选择在可用列表中
    if st.session_state.page_selection not in pages:
        st.session_state.page_selection = pages[0]
    
    # 5. 导航栏
    # 使用 st.session_state.page_selection 来设置默认值
    page = st.sidebar.radio("选择功能模块", pages,
                            index=pages.index(st.session_state.page_selection),
                            key='page_selection')

    # 6. 路由 (传递 config 到需要标题的页面)
    if page == "选手登记":
        display_registration_form(config)
    elif page == LOGIN_PAGE:
        display_login_page()
    elif page == "计时扫码":
        if st.session_state.logged_in:
            display_timing_scanner(config)
        else:
            st.warning("请先登录管理员账号以访问此功能。")
            display_login_page()
    elif page == "排名结果":
        if st.session_state.logged_in:
            display_results_ranking()
        else:
            st.warning("请先登录管理员账号以访问此功能。")
            display_login_page()
    elif page == "数据管理（管理员）":
        if st.session_state.logged_in:
            display_admin_data_management(config)
        else:
            st.warning("请先登录管理员账号以访问此功能。")
            display_login_page()
    elif page == "归档与重置":
        if st.session_state.logged_in:
            display_archive_reset()
        else:
            st.warning("请先登录管理员账号以访问此功能。")
            display_login_page()
    
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
