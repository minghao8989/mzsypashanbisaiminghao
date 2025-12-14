import streamlit as st
import pandas as pd
import os
from datetime import datetime

# --- 1. 配置和数据文件定义 ---

# 定义数据文件名
ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'

# --- 2. 辅助函数：初始化/加载数据 (与 Flask 版本保持一致，但移除了Flask的依赖) ---

def load_athletes_data():
    """加载选手资料文件，如果不存在或为空，则创建包含表头的空文件"""
    if not os.path.exists(ATHLETES_FILE) or os.path.getsize(ATHLETES_FILE) == 0:
        df = pd.DataFrame(columns=['athlete_id', 'department', 'name', 'gender', 'phone'])
        # 使用 utf-8-sig 兼容 Excel
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
        # 确保时间戳列被识别为日期时间对象
        return pd.read_csv(RECORDS_FILE, parse_dates=['timestamp'], dtype={'athlete_id': str})
    except Exception:
        return pd.DataFrame(columns=['athlete_id', 'checkpoint_type', 'timestamp'])

def save_athlete_data(df):
    """保存选手数据到 CSV"""
    df.to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig')

def save_records_data(df):
    """保存计时数据到 CSV"""
    df.to_csv(RECORDS_FILE, index=False, encoding='utf-8-sig')

# --- 3. 核心计算函数 (与 Flask 版本保持一致) ---

def calculate_net_time(df_records):
    """根据扫码记录计算每位选手的总用时和分段用时。"""
    if df_records.empty:
        return pd.DataFrame()

    # 1. 提取每个选手在每个检查点的最早时间
    timing_pivot = df_records.groupby(['athlete_id', 'checkpoint_type'])['timestamp'].min().reset_index()
    # 使用 pivot_table 将检查点类型转为列名
    timing_pivot = timing_pivot.pivot_table(index='athlete_id', columns='checkpoint_type', values='timestamp', aggfunc='first')
    
    # 确保 START 和 FINISH 时间存在
    df_results = timing_pivot.dropna(subset=['START', 'FINISH']).copy()
    
    # 逻辑校验：终点时间必须晚于起点时间
    df_results = df_results[df_results['FINISH'] > df_results['START']]

    # 计算总用时（秒）
    df_results['total_time_sec'] = (df_results['FINISH'] - df_results['START']).dt.total_seconds()

    # 计算分段用时
    df_results['segment1_sec'] = None
    df_results['segment2_sec'] = None
    
    # 只有 MID 存在时才计算分段
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


# --- 4. Streamlit 页面函数 (替代 Flask 路由) ---

def display_registration_form():
    """选手资料登记页面 (/register 路由)"""
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
            
            # 检查手机号是否已注册
            if phone in df_athletes['phone'].values:
                st.error(f"该手机号 ({phone}) 已注册，请勿重复提交。")
                return

            # 自动生成唯一的选手ID
            if df_athletes.empty:
                new_id = 1001
            else:
                numeric_ids = pd.to_numeric(df_athletes['athlete_id'], errors='coerce').dropna()
                new_id = int(numeric_ids.max()) + 1 if not numeric_ids.empty else 1001
            
            new_id_str = str(new_id)

            # 创建新的选手记录
            new_athlete = pd.DataFrame([{
                'athlete_id': new_id_str,
                'department': department,
                'name': name,
                'gender': gender,
                'phone': phone
            }])

            # 保存资料到 CSV 文件
            df_athletes = pd.concat([df_athletes, new_athlete], ignore_index=True)
            save_athlete_data(df_athletes)

            st.success(f"🎉 报名成功! 您的比赛编号是：**{new_id_str}**。请牢记此编号用于比赛计时。")


def display_timing_scanner():
    """计时扫码页面 (/scan 路由)"""
    
    # 侧边栏选择检查点类型 (替代 URL 参数)
    checkpoint_type = st.sidebar.selectbox(
        "选择检查点类型", 
        ['START (起点)', 'MID (中途)', 'FINISH (终点)'],
        key='checkpoint_select'
    ).split(' ')[0].upper() # 提取 START, MID, FINISH

    st.header(f"⏱️ {checkpoint_type} 计时终端")
    st.subheader(f"当前检查点: {checkpoint_type}")
    st.info("请在此处输入选手的比赛编号进行计时。")

    # 计时表单
    with st.form("timing_form"):
        athlete_id = st.text_input("输入选手比赛编号", key="scan_athlete_id").strip()
        submitted = st.form_submit_button(f"提交 {checkpoint_type} 计时")

        if submitted:
            if not athlete_id:
                st.error("请输入选手编号。")
                return

            # 1. 身份验证
            df_athletes = load_athletes_data()
            if athlete_id not in df_athletes['athlete_id'].values:
                st.error(f"编号 {athlete_id} 不存在，请检查是否已报名。")
                return

            df_records = load_records_data()

            # 2. 防重复记录检查
            existing_records = df_records[
                (df_records['athlete_id'] == athlete_id) & 
                (df_records['checkpoint_type'] == checkpoint_type)
            ]

            if not existing_records.empty:
                st.warning(f"该选手已在 {checkpoint_type} 扫码成功，请勿重复操作！")
                return

            # 3. 记录时间 (使用服务器时间)
            current_time = datetime.now()
            
            # 写入新的记录
            new_record = pd.DataFrame({
                'athlete_id': [athlete_id], 
                'checkpoint_type': [checkpoint_type], 
                'timestamp': [current_time]
            })
            
            df_records = pd.concat([df_records, new_record], ignore_index=True)
            save_records_data(df_records)

            name = df_athletes[df_athletes['athlete_id'] == athlete_id]['name'].iloc[0]

            # 4. 返回成功信息
            success_message = f"恭喜 **{name}**！{checkpoint_type} 计时成功！记录时间：**{current_time.strftime('%H:%M:%S.%f')[:-3]}**"
            st.success(success_message)
            
            # 清空输入框，方便下一次扫码
            st.session_state.scan_athlete_id = ""


def display_results_ranking():
    """结果统计与排名页面 (/results 路由)"""
    st.header("🏆 比赛成绩与排名")

    df_records = load_records_data()
    df_athletes = load_athletes_data()
    
    # 1. 计算总用时和分段用时
    df_calculated = calculate_net_time(df_records)

    if df_calculated.empty:
        st.warning("暂无完整的完赛记录。")
        return

    # 2. 合并选手资料
    df_final = df_calculated.merge(df_athletes, on='athlete_id', how='left')

    # 3. 核心排名：按总用时升序排列
    df_final = df_final.sort_values(by='total_time_sec', ascending=True).reset_index(drop=True)
    df_final['排名'] = df_final.index + 1
    
    # 4. 格式化时间并准备显示列
    df_final['总用时'] = df_final['total_time_sec'].apply(format_time)
    df_final['第一段'] = df_final['segment1_sec'].apply(format_time)
    df_final['第二段'] = df_final['segment2_sec'].apply(format_time)

    total_finishers = len(df_final)
    st.success(f"🎉 当前共有 **{total_finishers}** 位选手完成比赛并计入排名。")
    
    # 5. 显示排名榜单
    display_cols = ['排名', 'name', 'department', 'athlete_id', '总用时', '第一段', '第二段']
    
    # 重命名列以在 Streamlit 中更美观
    df_display = df_final[display_cols].rename(columns={
        'name': '姓名',
        'department': '单位/部门',
        'athlete_id': '编号'
    })
    
    st.dataframe(df_display, hide_index=True, use_container_width=True)

    # 6. 数据下载 (原 Flask 版本通过 /download 路由实现，Streamlit 使用 download_button)
    csv_data = df_display.to_csv(encoding='utf-8-sig', index=False)
    st.download_button(
        label="💾 下载完整的排名数据 (.csv)",
        data=csv_data,
        file_name="race_ranking_results.csv",
        mime="text/csv"
    )


# --- 5. Streamlit 主应用入口 ---

def main_app():
    # 确保文件在应用启动时存在 (Streamlit 会在每次运行时执行此代码)
    load_athletes_data()
    load_records_data()
    
    # Streamlit 侧边栏导航 (替代路由)
    st.sidebar.title("🏁 赛事管理系统")
    page = st.sidebar.radio("选择功能模块", 
        ["选手登记", "计时扫码", "排名结果"],
        index=0 
    )

    if page == "选手登记":
        display_registration_form()
    elif page == "计时扫码":
        display_timing_scanner()
    elif page == "排名结果":
        display_results_ranking()
    
    # 底部显示数据文件下载链接（方便管理员）
    st.sidebar.markdown("---")
    st.sidebar.subheader("管理员数据下载")
    
    # 允许管理员下载原始数据文件
    st.sidebar.download_button(
        label="📥 原始选手数据 (.csv)",
        data=load_athletes_data().to_csv(encoding='utf-8-sig', index=False),
        file_name="athletes_raw.csv",
        mime="text/csv"
    )
    st.sidebar.download_button(
        label="📥 原始计时记录 (.csv)",
        data=load_records_data().to_csv(encoding='utf-8-sig', index=False),
        file_name="records_raw.csv",
        mime="text/csv"
    )


if __name__ == '__main__':
    main_app()
