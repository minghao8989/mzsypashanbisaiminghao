import streamlit as st
import pandas as pd
import os
from datetime import datetime

# --- 1. 配置和数据文件定义 ---

# 定义数据文件名
ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'

# --- 2. 辅助函数：初始化/加载数据 (保持一致) ---

def load_athletes_data():
    """加载选手资料文件，如果不存在或为空，则创建包含表头的空文件"""
    if not os.path.exists(ATHLETES_FILE) or os.path.getsize(ATHLETES_FILE) == 0:
        df = pd.DataFrame(columns=['athlete_id', 'department', 'name', 'gender', 'phone'])
        df.to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig') 
        return df
    
    try:
        # 注意: 确保 athlete_id 始终为字符串，防止 Excel 自动转换
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

# --- 3. 核心计算函数 (保持一致) ---
# ... (calculate_net_time 和 format_time 函数代码保持不变) ...

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

# --- 4. Streamlit 页面函数 (修改后的注册、计时、结果函数保持不变) ---

def display_registration_form():
    # ... (代码保持不变) ...
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


def display_timing_scanner():
    # ... (代码保持不变) ...
    checkpoint_type = st.sidebar.selectbox(
        "选择检查点类型", 
        ['START (起点)', 'MID (中途)', 'FINISH (终点)'],
        key='checkpoint_select'
    ).split(' ')[0].upper()

    st.header(f"⏱️ {checkpoint_type} 计时终端")
    st.subheader(f"当前检查点: {checkpoint_type}")
    st.info("请在此处输入选手的比赛编号进行计时。")

    with st.form("timing_form"):
        athlete_id = st.text_input("输入选手比赛编号", key="scan_athlete_id").strip()
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


def display_results_ranking():
    # ... (代码保持不变) ...
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


# --- 5. 新增的管理员数据管理页面 ---

def display_admin_data_management():
    """管理员数据查看和编辑页面"""
    st.header("🔑 数据管理 (管理员权限)")
    st.warning("在此处修改数据需谨慎，任何更改都将直接保存到 CSV 文件中！")
    
    # 侧边栏选择要编辑的数据表
    data_select = st.sidebar.radio(
        "选择要管理的数据表", 
        ["选手资料 (athletes)", "计时记录 (records)"]
    )

    if data_select == "选手资料 (athletes)":
        st.subheader("📝 选手资料编辑")
        df_athletes = load_athletes_data()
        
        # 使用 st.data_editor 允许用户修改 DataFrame
        edited_df = st.data_editor(
            df_athletes,
            num_rows="dynamic", # 允许添加/删除行
            key="edit_athletes_data",
            use_container_width=True
        )

        # 保存按钮
        if st.button("💾 确认修改并保存选手数据"):
            try:
                # 检查 athlete_id 列是否仍然是唯一的（关键校验）
                if edited_df['athlete_id'].duplicated().any():
                    st.error("保存失败：'athlete_id' 列中存在重复编号！请修正后保存。")
                else:
                    save_athlete_data(edited_df)
                    st.success("✅ 选手资料修改已成功保存！")
                    # 重新加载页面，显示最新数据
                    st.experimental_rerun() 
            except Exception as e:
                st.error(f"保存失败：{e}")


    elif data_select == "计时记录 (records)":
        st.subheader("⏱️ 计时记录编辑")
        df_records = load_records_data()
        
        st.info("提示：请谨慎修改时间戳。格式应为 YYYY-MM-DD HH:MM:SS.mmmmmm")
        
        # 计时记录编辑 (通常计时记录只允许删除或微调时间)
        edited_df = st.data_editor(
            df_records,
            num_rows="dynamic",
            key="edit_records_data",
            use_container_width=True
        )
        
        # 保存按钮
        if st.button("💾 确认修改并保存计时记录"):
            try:
                # 尝试将 'timestamp' 列转换为 datetime 对象，以验证格式
                edited_df['timestamp'] = pd.to_datetime(edited_df['timestamp'], errors='raise')
                
                save_records_data(edited_df)
                st.success("✅ 计时记录修改已成功保存！")
                st.experimental_rerun()
            except ValueError:
                st.error("保存失败：'timestamp' 列的日期时间格式不正确，请确保格式为 YYYY-MM-DD HH:MM:SS.SSSSSS。")
            except Exception as e:
                st.error(f"保存失败：{e}")


# --- 6. Streamlit 主应用入口 (修改侧边栏导航) ---

def main_app():
    # 确保文件在应用启动时存在
    load_athletes_data()
    load_records_data()
    
    # Streamlit 侧边栏导航 (添加新的管理模块)
    st.sidebar.title("🏁 赛事管理系统")
    page = st.sidebar.radio("选择功能模块", 
        ["选手登记", "计时扫码", "排名结果", "数据管理（管理员）"],
        index=0 
    )

    if page == "选手登记":
        display_registration_form()
    elif page == "计时扫码":
        display_timing_scanner()
    elif page == "排名结果":
        display_results_ranking()
    elif page == "数据管理（管理员）":
        display_admin_data_management()
    
    # 原来的管理员数据下载按钮现在位于“数据管理”页面内，作为备用下载。
    st.sidebar.markdown("---")
    st.sidebar.info("数据下载和修改请前往 '数据管理' 模块。")


if __name__ == '__main__':
    # 设置 Streamlit 页面配置
    st.set_page_config(
        page_title="山地赛计时终端",
        page_icon="🏃",
        layout="wide"
    )
    main_app()
