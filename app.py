# ================================
# 登山比赛计时与管理系统（手机扫码稳定版）
# Streamlit App - 完整可替换版 app.py
# 特点：
# - 手机相机 / 微信扫码
# - Token 自动计时
# - 无摄像头调用
# - 无 st.experimental_rerun 死循环
# ================================

import streamlit as st
import pandas as pd
import os
from datetime import datetime
from itsdangerous import URLSafeTimedSerializer, BadTimeSignature, SignatureExpired

# ================================
# 基础配置
# ================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TIMING_FILE = os.path.join(DATA_DIR, "timing.csv")
ATHLETE_FILE = os.path.join(DATA_DIR, "athletes.csv")

CONFIG = {
    "SECRET_KEY": "CHANGE_THIS_SECRET_KEY",
    "QR_CODE_EXPIRY_SECONDS": 300,
}

os.makedirs(DATA_DIR, exist_ok=True)

# ================================
# 工具函数
# ================================

def get_serializer(secret_key):
    return URLSafeTimedSerializer(secret_key)


def load_athletes():
    if not os.path.exists(ATHLETE_FILE):
        df = pd.DataFrame(columns=["athlete_id", "name", "password"])
        df.to_csv(ATHLETE_FILE, index=False)
    return pd.read_csv(ATHLETE_FILE)


def load_timing():
    if not os.path.exists(TIMING_FILE):
        df = pd.DataFrame(columns=[
            "athlete_id",
            "START_TIME",
            "MID_TIME",
            "FINISH_TIME",
        ])
        df.to_csv(TIMING_FILE, index=False)
    return pd.read_csv(TIMING_FILE)


def save_timing(df):
    df.to_csv(TIMING_FILE, index=False)


# ================================
# 计时逻辑
# ================================

def record_checkpoint_time(athlete_id, checkpoint_type):
    df = load_timing()

    if athlete_id not in df["athlete_id"].values:
        df.loc[len(df)] = {
            "athlete_id": athlete_id,
            "START_TIME": None,
            "MID_TIME": None,
            "FINISH_TIME": None,
        }

    idx = df.index[df["athlete_id"] == athlete_id][0]
    col = f"{checkpoint_type}_TIME"

    if pd.notna(df.at[idx, col]):
        return "duplicate"

    df.at[idx, col] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_timing(df)
    return "success"


# ================================
# 登录
# ================================

def athlete_login():
    st.subheader("🏃 选手登录")
    athlete_id = st.text_input("比赛编号")
    password = st.text_input("密码", type="password")

    if st.button("登录"):
        df = load_athletes()
        row = df[(df["athlete_id"].astype(str) == athlete_id) & (df["password"] == password)]
        if not row.empty:
            st.session_state.athlete = {
                "id": athlete_id,
                "name": row.iloc[0]["name"],
            }
            st.success("登录成功")
        else:
            st.error("登录失败")


# ================================
# 选手欢迎页（手机扫码核心）
# ================================

def display_athlete_welcome_page():
    athlete = st.session_state.get("athlete")
    if not athlete:
        athlete_login()
        return

    st.title("🎉 报名成功，欢迎参赛！")

    col1, col2 = st.columns(2)
    col1.metric("比赛编号", athlete["id"])
    col2.metric("选手姓名", athlete["name"])

    st.divider()

    st.info(
        """
📱 **签到方式**

请使用 **手机相机 / 微信 / 支付宝** 扫描工作人员提供的二维码。

- 扫描后将自动打开本页面
- 系统将自动记录时间
- 无需打开摄像头
"""
    )

    # ========== Token 处理 ==========
    token = st.query_params.get("token")

    if token:
        if st.session_state.get("last_token") != token:
            st.session_state.last_token = token
            s = get_serializer(CONFIG["SECRET_KEY"])

            try:
                data = s.loads(
                    token,
                    salt="checkpoint-timing",
                    max_age=CONFIG["QR_CODE_EXPIRY_SECONDS"],
                )
                cp = data.get("cp")
                if cp not in ["START", "MID", "FINISH"]:
                    st.error("无效检查点")
                else:
                    result = record_checkpoint_time(athlete["id"], cp)
                    if result == "success":
                        st.success(f"✅ {cp} 签到成功")
                    else:
                        st.warning(f"⚠️ {cp} 已签到")
            except SignatureExpired:
                st.error("二维码已过期")
            except BadTimeSignature:
                st.error("二维码无效")

    st.divider()

    df = load_timing()
    row = df[df["athlete_id"] == athlete["id"]]
    if not row.empty:
        st.subheader("⏱️ 我的计时")
        st.table(row)

    if st.button("退出登录"):
        st.session_state.clear()
        st.experimental_rerun()


# ================================
# 管理员生成二维码（示例）
# ================================

def admin_panel():
    st.title("🛠️ 管理员面板（生成二维码）")

    checkpoint = st.selectbox("检查点", ["START", "MID", "FINISH"])

    if st.button("生成二维码 Token"):
        s = get_serializer(CONFIG["SECRET_KEY"])
        token = s.dumps({"cp": checkpoint}, salt="checkpoint-timing")
        url = f"{st.request.url_root}?token={token}"
        st.code(url)
        st.info("将此链接生成二维码即可")


# ================================
# 主入口
# ================================

def main():
    st.set_page_config(page_title="登山比赛计时系统", layout="centered")

    menu = st.sidebar.radio("菜单", ["选手", "管理员"])

    if menu == "选手":
        display_athlete_welcome_page()
    else:
        admin_panel()


if __name__ == "__main__":
    main()
