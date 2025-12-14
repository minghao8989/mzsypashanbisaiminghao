from flask import Flask, render_template, request, redirect, url_for
import pandas as pd
import os
from datetime import datetime

# 初始化 Flask 应用
app = Flask(__name__)
# 定义数据文件名
ATHLETES_FILE = 'athletes.csv'
RECORDS_FILE = 'timing_records.csv'

# --- 辅助函数：初始化/加载数据 ---

def load_athletes_data():
    """加载选手资料文件，如果不存在或为空，则创建包含表头的空文件"""
    # 检查文件是否不存在，或者文件大小是否为 0
    if not os.path.exists(ATHLETES_FILE) or os.path.getsize(ATHLETES_FILE) == 0:
        # 确保表头与注册表单和计时逻辑一致
        df = pd.DataFrame(columns=['athlete_id', 'department', 'name', 'gender', 'phone'])
        df.to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig') 
        return df
    
    # 捕获可能出现的读取错误
    try:
        return pd.read_csv(ATHLETES_FILE, dtype={'athlete_id': str})
    except Exception as e:
        # 如果读取失败，返回空DataFrame
        return pd.DataFrame(columns=['athlete_id', 'department', 'name', 'gender', 'phone'])


def load_records_data():
    """加载计时记录文件，如果不存在或为空，则创建包含表头的空文件"""
    # 检查文件是否不存在，或者文件大小是否为 0
    if not os.path.exists(RECORDS_FILE) or os.path.getsize(RECORDS_FILE) == 0:
        df = pd.DataFrame(columns=['athlete_id', 'checkpoint_type', 'timestamp'])
        df.to_csv(RECORDS_FILE, index=False, encoding='utf-8-sig')
        return df
        
    try:
        # 确保时间戳列被识别为日期时间对象
        return pd.read_csv(RECORDS_FILE, parse_dates=['timestamp'], dtype={'athlete_id': str})
    except Exception as e:
        # 如果读取失败，返回空DataFrame
        return pd.DataFrame(columns=['athlete_id', 'checkpoint_type', 'timestamp'])


# --- 1. 资料登记路由 (/register) ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    """处理选手的资料填写和提交"""
    if request.method == 'POST':
        # 1. 收集表单数据
        department = request.form.get('department').strip()
        name = request.form.get('name').strip()
        gender = request.form.get('gender')
        phone = request.form.get('phone').strip()

        if not all([department, name, gender, phone]):
            return render_template('register.html', error="请填写所有必填信息。")

        df_athletes = load_athletes_data()
        
        # 2. 检查手机号是否已注册 (防止重复报名)
        if phone in df_athletes['phone'].values:
            return render_template('register.html', error=f"该手机号 ({phone}) 已注册，请勿重复提交。")

        # 3. 自动生成唯一的选手ID (athlete_id)
        if df_athletes.empty:
            new_id = 1001
        else:
            numeric_ids = pd.to_numeric(df_athletes['athlete_id'], errors='coerce').dropna()
            new_id = int(numeric_ids.max()) + 1 if not numeric_ids.empty else 1001
            
        new_id_str = str(new_id)

        # 4. 创建新的选手记录
        new_athlete = pd.DataFrame([{
            'athlete_id': new_id_str,
            'department': department,
            'name': name,
            'gender': gender,
            'phone': phone
        }])

        # 5. 保存资料到 CSV 文件
        df_athletes = pd.concat([df_athletes, new_athlete], ignore_index=True)
        df_athletes.to_csv(ATHLETES_FILE, index=False, encoding='utf-8-sig')

        # 6. 返回成功信息
        return render_template('register.html', success=f"报名成功! 您的比赛编号是：{new_id_str}。请牢记此编号用于比赛计时。")

    # GET 请求：显示注册表单
    return render_template('register.html')

# --- 2. 计时路由 (/scan) ---
@app.route('/scan', methods=['GET', 'POST'])
def scan_checkpoint():
    """处理起点、中途和终点的扫码请求。"""
    # 自动识别检查点类型：START, MID, FINISH
    checkpoint_type = request.args.get('point', 'unknown').upper() 

    if request.method == 'POST':
        athlete_id = request.form.get('athlete_id', '').strip()

        # 1. 身份验证
        df_athletes = load_athletes_data()
        if athlete_id not in df_athletes['athlete_id'].values:
            return render_template('scan.html', point_type=checkpoint_type, error=f"编号 {athlete_id} 不存在，请检查是否已报名。")

        df_records = load_records_data()

        # 2. 防重复记录检查：只接受该检查点的第一次有效记录
        existing_records = df_records[
            (df_records['athlete_id'] == athlete_id) & 
            (df_records['checkpoint_type'] == checkpoint_type)
        ]

        if not existing_records.empty:
            return render_template('scan.html', point_type=checkpoint_type, 
                                   error=f"您已在 {checkpoint_type} 扫码成功，请勿重复操作！")

        # 3. 记录时间 (使用服务器时间)
        current_time = datetime.now()
        
        # 写入新的记录
        new_record = pd.DataFrame({
            'athlete_id': [athlete_id], 
            'checkpoint_type': [checkpoint_type], 
            'timestamp': [current_time]
        })
        
        df_records = pd.concat([df_records, new_record], ignore_index=True)
        df_records.to_csv(RECORDS_FILE, index=False, encoding='utf-8-sig')

        name = df_athletes[df_athletes['athlete_id'] == athlete_id]['name'].iloc[0]

        # 4. 返回成功信息
        success_message = f"恭喜 {name}！{checkpoint_type} 计时成功！时间：{current_time.strftime('%H:%M:%S')}"
        
        return render_template('scan.html', point_type=checkpoint_type, success=success_message)

    # GET 请求：显示扫码输入界面
    if checkpoint_type not in ['START', 'MID', 'FINISH']:
        # 如果URL参数错误，返回404错误
        return "错误：检查点类型未知。", 404 
        
    return render_template('scan.html', point_type=checkpoint_type)

# --- 3. 结果统计与排名路由 (/results) ---

def calculate_net_time(df_records):
    """
    核心计算函数：根据扫码记录计算每位选手的总用时和分段用时。
    使用 pivot_table 替代 unstack，解决版本兼容性问题。
    """
    if df_records.empty:
        return pd.DataFrame()

    # 1. 提取每个选手在每个检查点的最早时间
    # 这一步生成一个包含 START, MID, FINISH 时间的 DataFrame
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


@app.route('/results')
def show_results():
    """显示最终排名榜单"""
    df_records = load_records_data()
    df_athletes = load_athletes_data()
    
    # 1. 计算总用时和分段用时
    df_calculated = calculate_net_time(df_records)

    if df_calculated.empty:
        return render_template('results.html', ranking=[], total_finishers=0, error="暂无完整的完赛记录。")

    # 2. 合并选手资料
    df_final = df_calculated.merge(df_athletes, on='athlete_id', how='left')

    # 3. 核心排名：按总用时升序排列
    df_final = df_final.sort_values(by='total_time_sec', ascending=True).reset_index(drop=True)
    df_final['rank'] = df_final.index + 1
    
    # 4. 格式化时间
    def format_time(seconds):
        if pd.isna(seconds):
            return 'N/A'
        minutes = int(seconds // 60)
        remaining_seconds = seconds % 60
        # 格式化为 MM:SS.mmm (分:秒.毫秒)
        return f"{minutes:02d}:{remaining_seconds:06.3f}"
        
    df_final['Total Time'] = df_final['total_time_sec'].apply(format_time)
    df_final['Segment 1'] = df_final['segment1_sec'].apply(format_time)
    df_final['Segment 2'] = df_final['segment2_sec'].apply(format_time)

    # 5. 准备传输给网页的数据
    ranking_data = df_final[['rank', 'name', 'department', 'Total Time', 'Segment 1', 'Segment 2', 'athlete_id']].to_dict('records')

    total_finishers = len(df_final)
    
    return render_template('results.html', ranking=ranking_data, total_finishers=total_finishers)


# --- 运行 Flask 应用前的初始化 ---

def init_files():
    """在应用启动前，确保两个 CSV 文件都存在且有表头"""
    load_athletes_data()
    load_records_data()
    
# --- 运行 Flask 应用 ---
if __name__ == '__main__':
    # 初始化文件 (会创建或加载CSV文件)
    init_files() 
    # host='0.0.0.0' 允许外部访问, debug=True 方便调试
    app.run(debug=True, host='0.0.0.0', port=5000)