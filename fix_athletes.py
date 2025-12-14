import pandas as pd
import os

# 检查文件是否存在
if not os.path.exists('athletes.csv'):
    print("❌ athletes.csv 不存在！")
    exit(1)

# 尝试用 GBK 编码读取（Windows 默认中文编码）
try:
    df = pd.read_csv('athletes.csv', dtype={'athlete_id': str}, encoding='gbk')
    print("✅ 成功以 GBK 编码读取 athletes.csv")
except Exception as e_gbk:
    print(f"⚠️ GBK 读取失败，尝试 UTF-8...")
    try:
        df = pd.read_csv('athletes.csv', dtype={'athlete_id': str}, encoding='utf-8')
        print("✅ 成功以 UTF-8 编码读取")
    except Exception as e_utf8:
        print(f"❌ 所有编码都失败了！\nGBK 错误: {e_gbk}\nUTF-8 错误: {e_utf8}")
        exit(1)

# === 在这里修改你要修正的名字 ===
# 示例：把 "张1明1豪" 改成 "张明豪"
df.loc[df['name'] == '张1明1豪', 'name'] = '张明豪'

# 如果你知道编号，也可以这样改：
# df.loc[df['athlete_id'] == '1001', 'name'] = '张明豪'

# 强制保存为 UTF-8 with BOM（Flask 能正确读取）
df.to_csv('athletes.csv', index=False, encoding='utf-8-sig')
print("✅ 已成功修复并保存为 UTF-8 with BOM 格式！")