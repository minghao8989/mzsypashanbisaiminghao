import streamlit as st
import pandas as pd
import os
from datetime import datetime
import time 

# --- 1. 配置和数据文件定义 & 安全设置 ---

# 定义数据文件名
ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'

# 【重要安全设置】管理员密码
# ⚠️ 请务必将这里的默认密码替换成你自己的安全密码！
ADMIN_PASSWORD = "your_secure_password_123" 
LOGIN_PAGE = "管理员登录"

# 初始化 Session State 以跟踪登录状态和页面选择
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'page_selection' not in st.session_state:
    st.session_state.page_selection = "选手登记"


# --- 2. 辅助函数：文件加载与保存 (保持一致) ---

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

# --- 3. 核心计算与格式化函数 (保持一致) ---

def calculate_net_time(df_records):
    """根据扫码记录计算每位选手的总用时和分段用时。"""
    if df_records.empty:
        return pd.DataFrame()

    timing_pivot = df_records.groupby(['athlete_id', 'checkpoint_type'])['timestamp'].min().reset_index()
    timing_pivot = timing_pivot.pivot_table(index='athlete_id', columns='checkpoint_type', values='timestamp', aggfunc='first')
    
    df_results = timing_pivot.dropna(subset=['START', 'FINISH']).copy()
    df_results = df_results[df_results['FINISH'] > df_results['START']]

    df_results['total_time_sec'] = (df_results['FINISH'] - df_results['START']).dt.total_seconds()

    df_results['segment1_sec'] = None
    df_results['segment2_sec'] = None
    
    valid_mid = df_results['MID'].notna()
    df_results.loc[valid_mid, 'segment1_sec'] = (df_results['MID'] - df_results['START']).dt.total_seconds()
    df_results.loc[valid_mid, 'segment2_sec'] = (df_results['FINISH'] - df_results['MID']).dt.total_seconds()
    
    return df_results.reset_index()


def format_time(seconds):
    """格式化秒数到 MM:SS.mmm"""
    if pd.isna(seconds) or seconds is None:
        return 'N/A'
    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    return f"{minutes:02d}:{remaining_seconds:06.3f}"


# --- 4. 页面函数：选手登记 (Public Access) ---

def display_registration_form():
    """选手资料登记页面"""
    st.header("👤 选手资料登记")
    st.info("请准确填写以下信息，并记住系统生成的比赛编号。")

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
            
            if phone in df_athletes['phone'].values:
                st.error(f"该手机号 ({phone}) 已注册，请勿重复提交。")
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

            st.session_state.department = ''
            st.session_state.name = ''
            st.session_state.gender = '男'
            st.session_state.phone = ''


# --- 5. 页面函数：计时扫码 (Private Access) ---

def display_timing_scanner():
    """计时扫码页面"""
    
    checkpoint_type = st.sidebar.selectbox(
        "选择检查点类型", 
        ['START (起点)', 'MID (中途)', 'FINISH (终点)'],
        key='checkpoint_select'
    ).split(' ')[0].upper()

    st.header(f"⏱️ {checkpoint_type} 计时终端")
    st.subheader(f"当前检查点: {checkpoint_type}")
    st.info("请在此处输入选手的比赛编号进行计时。")

    with st.form("timing_form"):
        athlete_id = st.text_input("输入选手比赛编号", key="scan_athlete_id", max_chars=4).strip()
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
            
            st.session_state.scan_athlete_id = ""


# --- 6. 页面函数：排名结果 (Private Access) ---

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

# --- 7. 页面函数：管理员数据管理 (Private Access) ---

def display_admin_data_management():
    """管理员数据查看和编辑页面"""
    st.header("🔑 数据管理 (管理员权限)")
    st.warning("在此处修改数据需谨慎，任何更改都将直接保存到 CSV 文件中！")
    
    data_select = st.sidebar.radio(
        "选择要管理的数据表", 
        ["选手资料 (athletes)", "计时记录 (records)"]
    )

    if data_select == "选手资料 (athletes)":
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
                if edited_df['athlete_id'].duplicated().any():
                    st.error("保存失败：'athlete_id' 列中存在重复编号！请修正后保存。")
                elif edited_df['athlete_id'].astype(str).str.contains(r'[^\d]').any():
                    st.error("保存失败：'athlete_id' 必须是纯数字编号。")
                else:
                    edited_df['athlete_id'] = edited_df['athlete_id'].astype(str) 
                    save_athlete_data(edited_df)
                    st.success("✅ 选手资料修改已成功保存！")
                    time.sleep(1)
                    st.experimental_rerun() 
            except Exception as e:
                st.error(f"保存失败：{e}")


    elif data_select == "计时记录 (records)":
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
                st.error("保存失败：'timestamp' 列的日期时间格式不正确，请确保格式正确。")
            except Exception as e:
                st.error(f"保存失败：{e}")


# --- 8. 页面函数：归档与重置 (Private Access) ---

def archive_and_reset_race_data():
    """将当前数据归档，并清空活动文件以便开始新的比赛。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if os.path.exists(ATHLETES_FILE) and os.path.getsize(ATHLETES_FILE) > 0:
        new_archive_name = f"ARCHIVE_ATHLETES_{timestamp}.csv"
        os.rename(ATHLETES_FILE, new_archive_name)
    
    if os.path.exists(RECORDS_FILE) and os.path.getsize(RECORDS_FILE) > 0:
        new_archive_name = f"ARCHIVE_RECORDS_{timestamp}.csv"
        os.rename(RECORDS_FILE, new_archive_name)

    load_athletes_data()
    load_records_data()
    
    return True

def get_archived_files():
    """查找所有已归档的历史数据文件。"""
    files = os.listdir('.')
    archived = [f for f in files if f.startswith('ARCHIVE_')]
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
                st.error("归档失败，请检查文件权限。")

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
        df_history_athletes = pd.read_csv(selected_athlete_file, dtype={'athlete_id': str})
        df_history_records = pd.read_csv(selected_record_file, parse_dates=['timestamp'], dtype={'athlete_id': str})
        
        st.success(f"成功加载归档文件：{selected_athlete_file}")
        
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


# --- 9. 页面函数：管理员登录 (优化后的跳转逻辑) ---

def display_login_page():
    """管理员登录页面"""
    st.header("🔑 管理员登录")
    st.info("请输入管理员密码以访问后台管理功能。")
    
    with st.form("login_form"):
        password = st.text_input("密码", type="password")
        submitted = st.form_submit_button("登录")
        
        if submitted:
            if password == ADMIN_PASSWORD:
                # 1. 设置登录状态为 True
                st.session_state.logged_in = True
                
                # 2. 强制将页面导航状态设置为一个后台页面，实现“跳转”
                st.session_state.page_selection = "计时扫码" 
                
                # 3. 提供成功反馈和短暂延时，让 Streamlit 自然刷新
                st.success("登录成功！正在进入后台管理页面...")
                time.sleep(1) # 暂停1秒，让用户看到成功信息，然后让 Streamlit 自动完成刷新周期
            else:
                st.error("密码错误，请重试。")

def display_logout_button():
    """退出登录按钮"""
    if st.sidebar.button("退出登录"):
        st.session_state.logged_in = False
        st.session_state.page_selection = "选手登记" # 退出后返回公共页面
        st.experimental_rerun()


# --- 10. Streamlit 主应用入口 (Session State 管理页面选择) ---

def main_app():
    load_athletes_data()
    load_records_data()
    
    st.sidebar.title("🏁 赛事管理系统")
    
    # 1. 定义导航列表
    if st.session_state.logged_in:
        pages = ["选手登记", "计时扫码", "排名结果", "数据管理（管理员）", "归档与重置"]
        display_logout_button()
    else:
        pages = ["选手登记", LOGIN_PAGE]

    # 2. 确保当前的页面选择在可用列表中
    if st.session_state.page_selection not in pages:
        # 如果当前页面（比如计时扫码）在退出后不再可用，则默认跳转到第一个可用页面
        st.session_state.page_selection = pages[0]
    
    # 3. 导航栏：使用 key='page_selection' 来管理当前选中的页面
    page = st.sidebar.radio("选择功能模块", pages, 
                            index=pages.index(st.session_state.page_selection), 
                            key='page_selection') 

    # 4. 路由
    if page == "选手登记":
        display_registration_form()
    elif page == LOGIN_PAGE:
        display_login_page()
    elif page == "计时扫码":
        display_timing_scanner()
    elif page == "排名结果":
        display_results_ranking()
    elif page == "数据管理（管理员）":
        display_admin_data_management()
    elif page == "归档与重置":
        display_archive_reset()
    
    st.sidebar.markdown("---")
    st.sidebar.info("数据下载和修改请前往 '数据管理' 模块。")


if __name__ == '__main__':
    st.set_page_config(
        page_title="山地赛计时终端",
        page_icon="🏃",
        layout="wide"
    )
    main_app()
