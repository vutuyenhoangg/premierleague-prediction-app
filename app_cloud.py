# ============================================================
# WORLD CUP 2026 PREDICTION APP
# Stack: Streamlit + Supabase/PostgreSQL
# Database input: Supabase via DATABASE_URL
# ============================================================

import streamlit.components.v1 as components
import html
import os
import hmac
import hashlib
import base64
import mimetypes
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import Engine
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import streamlit as st
import plotly.express as px
from streamlit_extras.stylable_container import stylable_container
import secrets
from streamlit_cookies_controller import CookieController
import re
from google import genai
from google.genai import types

# ============================================================
# 1. CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = st.secrets["DATABASE_URL"]
RUN_DB_MIGRATIONS = str(
    os.getenv(
        "RUN_DB_MIGRATIONS",
        st.secrets.get("RUN_DB_MIGRATIONS", "false")
    )
).strip().lower() in ["true", "1", "yes", "y"]

APP_NAME = "World Cup 2026 Prediction Arena"
APP_SHORT_NAME = "WC 2026"
APP_TAGLINE = "Dự đoán tỉ số, tích điểm và leo bảng xếp hạng cùng bạn bè."
COOKIE_NAME = "wc_session_token"
SESSION_DAYS = 30
HOPE_STARS_PER_USER = 5
SUPER_STARS_PER_USER = 1
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME = st.secrets.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")

AVATAR_FOLDER = "data/static/avatars"
DEFAULT_AVATAR_KEY = "avatar_default_1.png"
AVATAR_EXTENSIONS = {".png"}
AVATAR_ORDER = [
    "avatar_default_1.png",
    "avatar_default_2.png",
    "avatar_1.png",
    "avatar_2.png",
    "avatar_3.png",
    "avatar_4.png",
    "avatar_5.png",
    "avatar_6.png",
    "avatar_7.png",
    "avatar_8.png",
    "avatar_9.png",
    "avatar_10.png",
    "avatar_11.png",
    "avatar_12.png",
    "avatar_13.png",
    "avatar_14.png",
    "avatar_15.png",
    "avatar_16.png",
    "avatar_17.png",
    "avatar_18.png",
    "avatar_19.png",
    "avatar_20.png",
    "avatar_21.png",
    "avatar_22.png",
    "avatar_23.png",
    "avatar_24.png",
    "avatar_25.png",
    "avatar_26.png",
    "avatar_27.png",
    "avatar_28.png",
    "avatar_29.png",
    "avatar_30.png"
]

STAR_TYPE_NONE = "none"
STAR_TYPE_HOPE = "hope"
STAR_TYPE_SUPER = "super"

STAR_CONFIG = {
    STAR_TYPE_NONE: {
        "label": "Không dùng sao",
        "short_label": "Không dùng sao",
        "multiplier": 1
    },
    STAR_TYPE_HOPE: {
        "label": "⭐ Ngôi sao hy vọng x2",
        "short_label": "⭐ Ngôi sao hy vọng",
        "multiplier": 2
    },
    STAR_TYPE_SUPER: {
        "label": "✨ Siêu sao x3",
        "short_label": "✨ Siêu sao",
        "multiplier": 3
    }
}

# ============================================================
# TODO LINK AREA
# ============================================================

APP_LOGO_URL = "data/static/app-logo.png"

HERO_BACKGROUND_URL = "data/static/hero-background.jpeg"

HERO_TROPHY_IMAGE_URL = "data/static/trophy-render.png"

SIDEBAR_DECORATION_URL = "data/static/sidebar.png"

FOOTER_PROJECT_URL = ""
# TODO LINK 5:
# Gắn link GitHub repo / portfolio / project page của bạn.
# Có thể để trống.
# FOOTER_PROJECT_URL = "https://github.com/yourname/worldcup-prediction-app"

@st.cache_data(show_spinner=False)
def resolve_asset_src(asset_path: str) -> str:
    """
    Nhận link ảnh online hoặc đường dẫn ảnh local, rồi trả về src dùng được trong HTML/CSS.

    Cách dùng local khuyên dùng:
    - Đặt ảnh trong folder static/ cùng cấp với app.py
    - Ví dụ: static/app-logo.png

    Function này sẽ tự chuyển ảnh local thành base64 data URI, vì vậy bạn KHÔNG cần
    bắt buộc phải tạo .streamlit/config.toml để test giao diện local.
    """
    if not asset_path:
        return ""

    asset_path = str(asset_path).strip()

    if asset_path.startswith(("http://", "https://", "data:", "/app/static/")):
        return asset_path

    normalized_path = asset_path.replace("\\", "/")

    candidate_paths = []

    raw_path = Path(normalized_path)

    if raw_path.is_absolute():
        candidate_paths.append(raw_path)
    else:
        candidate_paths.append(BASE_DIR / raw_path)

        # Nếu trước đó bạn lỡ ghi data/static/..., app vẫn thử hiểu lại thành static/...
        if normalized_path.startswith("data/static/"):
            candidate_paths.append(BASE_DIR / normalized_path.replace("data/static/", "static/", 1))

        # Nếu notebook/app đang chạy trong folder data, ảnh thường nằm ở BASE_DIR/static/
        candidate_paths.append(BASE_DIR / "static" / raw_path.name)

    for candidate_path in candidate_paths:
        if candidate_path.exists() and candidate_path.is_file():
            mime_type, _ = mimetypes.guess_type(str(candidate_path))
            mime_type = mime_type or "image/png"

            encoded = base64.b64encode(candidate_path.read_bytes()).decode("utf-8")
            return f"data:{mime_type};base64,{encoded}"

    # Fallback để dễ debug nếu file không tồn tại
    return asset_path


st.set_page_config(
    page_title=APP_NAME,
    page_icon="⚽",
    layout="wide"
)

cookie_controller = CookieController()

@st.cache_data(show_spinner=False)
def load_avatar_keys() -> list[str]:
    """
    Load danh sách avatar có sẵn trong folder data/static/avatars.

    Nếu AVATAR_ORDER có khai báo thứ tự, app sẽ ưu tiên hiển thị theo thứ tự đó.
    Các file avatar chưa có trong AVATAR_ORDER sẽ được xếp phía sau theo tên file.
    """
    avatar_dir = BASE_DIR / AVATAR_FOLDER

    if not avatar_dir.exists() or not avatar_dir.is_dir():
        return []

    avatar_keys = []

    for file_path in avatar_dir.iterdir():
        if (
            file_path.is_file()
            and file_path.suffix.lower() in AVATAR_EXTENSIONS
        ):
            avatar_keys.append(file_path.name)

    available_avatar_keys = set(avatar_keys)

    ordered_avatar_keys = [
        avatar_key
        for avatar_key in AVATAR_ORDER
        if avatar_key in available_avatar_keys
    ]

    remaining_avatar_keys = sorted(
        avatar_key
        for avatar_key in avatar_keys
        if avatar_key not in set(ordered_avatar_keys)
    )

    return ordered_avatar_keys + remaining_avatar_keys


def normalize_avatar_key(avatar_key) -> str:
    """
    Chuẩn hóa avatar_key.

    Mục tiêu:
    - Nếu user chưa có avatar thì dùng avatar mặc định.
    - Nếu avatar đang lưu trong DB không còn tồn tại thì fallback về avatar mặc định.
    - Chỉ nhận tên file, không nhận path tùy ý.
    """
    avatar_keys = load_avatar_keys()

    if not avatar_keys:
        return ""

    if avatar_key is None or pd.isna(avatar_key):
        avatar_key = DEFAULT_AVATAR_KEY

    avatar_key = Path(str(avatar_key).strip()).name

    if avatar_key in avatar_keys:
        return avatar_key

    if DEFAULT_AVATAR_KEY in avatar_keys:
        return DEFAULT_AVATAR_KEY

    return avatar_keys[0]


@st.cache_data(show_spinner=False)
def get_avatar_src(avatar_key: str) -> str:
    """
    Trả về src ảnh avatar để nhúng vào HTML/CSS.
    Tận dụng resolve_asset_src() hiện có của app.
    """
    avatar_key = normalize_avatar_key(avatar_key)

    if not avatar_key:
        return ""

    return resolve_asset_src(f"{AVATAR_FOLDER}/{avatar_key}")
# ============================================================
# 2. THEME + UI HELPERS
# ============================================================

def inject_worldcup_theme():
    hero_background_src = resolve_asset_src(HERO_BACKGROUND_URL)

    if hero_background_src:
        hero_background_css = f"""
            background-image:
                linear-gradient(90deg, rgba(7, 17, 31, 0.96), rgba(11, 31, 58, 0.88), rgba(18, 60, 105, 0.70)),
                url("{hero_background_src}");
            background-size: cover;
            background-position: center;
        """
    else:
        hero_background_css = """
            background:
                radial-gradient(circle at 12% 18%, rgba(0, 180, 216, 0.32), transparent 24%),
                radial-gradient(circle at 82% 16%, rgba(245, 197, 66, 0.30), transparent 22%),
                linear-gradient(135deg, #07111F 0%, #0B1F3A 52%, #123C69 100%);
        """

    st.markdown(
        f"""
        <style>
        :root {{
            --wc-midnight: #07111F;
            --wc-deep-blue: #0B1F3A;
            --wc-royal-blue: #123C69;
            --wc-sky: #00B4D8;
            --wc-gold: #F5C542;
            --wc-red: #E63946;
            --wc-green: #16A34A;
            --wc-orange: #F59E0B;
            --wc-slate: #64748B;
            --wc-paper: #F8FAFC;
            --wc-card: rgba(255, 255, 255, 0.94);
            --wc-ink: #07111F;
            --wc-muted: #64748B;
        }}

        .stApp {{
            background:
                radial-gradient(circle at top left, rgba(0, 180, 216, 0.14), transparent 28%),
                radial-gradient(circle at top right, rgba(245, 197, 66, 0.18), transparent 24%),
                linear-gradient(180deg, #F8FAFC 0%, #EEF4FA 100%);
            color: var(--wc-ink);
        }}

        .block-container {{
            padding-top: 1.6rem;
            padding-bottom: 2.4rem;
            max-width: 1440px;
        }}

        section[data-testid="stSidebar"] {{
            background:
                radial-gradient(circle at 30% 15%, rgba(0, 180, 216, 0.20), transparent 24%),
                linear-gradient(180deg, #07111F 0%, #0B1F3A 66%, #04101F 100%);
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }}

        section[data-testid="stSidebar"] * {{
            color: #F8FAFC;
        }}

        section[data-testid="stSidebar"] .stRadio > div {{
            gap: 8px;
        }}

        section[data-testid="stSidebar"] label[data-baseweb="radio"] {{
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 14px;
            padding: 10px 12px;
            margin-bottom: 6px;
        }}

        section[data-testid="stSidebar"] label[data-baseweb="radio"]:has(input:checked) {{
            background: linear-gradient(90deg, rgba(245,197,66,0.28), rgba(0,180,216,0.14));
            border: 1px solid rgba(245,197,66,0.66);
        }}

        .wc-sidebar-brand {{
            padding: 18px 8px 22px 8px;
            margin-bottom: 12px;
        }}

        .wc-logo-row {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}

        .wc-logo-fallback {{
            width: 54px;
            height: 54px;
            border-radius: 18px;
            background:
                radial-gradient(circle at 32% 28%, #F5C542 0%, #F5C542 22%, transparent 23%),
                linear-gradient(135deg, #123C69, #00B4D8);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 900;
            font-size: 15px;
            line-height: 1.05;
            box-shadow: 0 10px 24px rgba(0, 180, 216, 0.24);
        }}

        .wc-logo-img {{
            width: 58px;
            height: 58px;
            object-fit: contain;
            border-radius: 16px;
        }}

        .wc-brand-title {{
            font-weight: 900;
            font-size: 19px;
            letter-spacing: -0.02em;
            line-height: 1.05;
        }}

        .wc-brand-subtitle {{
            color: #CBD5E1;
            font-size: 12px;
            margin-top: 3px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}

        .wc-sidebar-footer {{
            margin-top: 36px;
            padding: 14px;
            border-radius: 18px;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.10);
            color: #CBD5E1;
            font-size: 13px;
        }}

        .wc-sidebar-decoration {{
            width: 100%;
            border-radius: 18px;
            margin-top: 12px;
            opacity: 0.86;
        }}

        .wc-hero {{
            {hero_background_css}
            border-radius: 28px;
            padding: 30px 34px;
            color: white;
            margin-bottom: 22px;
            box-shadow: 0 20px 48px rgba(7, 17, 31, 0.22);
            border: 1px solid rgba(255,255,255,0.20);
            overflow: hidden;
            position: relative;
        }}

        .wc-hero::after {{
            content: "";
            position: absolute;
            right: -80px;
            bottom: -90px;
            width: 320px;
            height: 320px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(245,197,66,0.26), transparent 62%);
            pointer-events: none;
        }}

        .wc-hero-grid {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 24px;
            align-items: center;
            position: relative;
            z-index: 1;
        }}

        .wc-eyebrow {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 7px 12px;
            border-radius: 999px;
            background: rgba(255,255,255,0.10);
            border: 1px solid rgba(255,255,255,0.20);
            color: #E2E8F0;
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 14px;
        }}

        .wc-hero-title {{
            font-size: clamp(34px, 4vw, 58px);
            font-weight: 950;
            letter-spacing: -0.055em;
            line-height: 0.95;
            margin-bottom: 12px;
        }}

        .wc-gold {{
            color: var(--wc-gold);
        }}

        .wc-hero-subtitle {{
            color: #CBD5E1;
            font-size: 17px;
            max-width: 760px;
            line-height: 1.6;
        }}

        .wc-hero-actions {{
            display: flex;
            gap: 10px;
            margin-top: 22px;
            flex-wrap: wrap;
        }}

        .wc-pill {{
            padding: 9px 13px;
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.18);
            background: rgba(255,255,255,0.08);
            color: #E2E8F0;
            font-size: 13px;
            font-weight: 700;
        }}

        .wc-hero-orb {{
            width: 142px;
            height: 142px;
            border-radius: 36px;
            background:
                radial-gradient(circle at 35% 25%, #FFF7CC, #F5C542 38%, #B45309 100%);
            color: #07111F;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 950;
            font-size: 32px;
            box-shadow: 0 18px 38px rgba(245,197,66,0.24);
            transform: rotate(-6deg);
        }}

        .wc-hero-img {{
            width: 150px;
            max-height: 170px;
            object-fit: contain;
            filter: drop-shadow(0 16px 32px rgba(0,0,0,0.34));
        }}

        .wc-page-title {{
            margin: 10px 0 18px 0;
        }}

        .wc-page-title h2 {{
            font-size: 26px;
            margin-bottom: 4px;
            letter-spacing: -0.03em;
        }}

        .wc-page-title p {{
            color: var(--wc-muted);
            margin: 0;
        }}

        .wc-filter-shell {{
            background: rgba(255,255,255,0.90);
            border: 1px solid rgba(15,23,42,0.08);
            border-radius: 22px;
            padding: 18px;
            box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
            margin-bottom: 18px;
        }}

        .wc-section-card {{
            background: rgba(255,255,255,0.92);
            border: 1px solid rgba(15,23,42,0.08);
            border-radius: 22px;
            padding: 18px;
            box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
            margin-bottom: 18px;
        }}

        .wc-kpi-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin-bottom: 18px;
        }}

        .wc-kpi-tile {{
            border-radius: 20px;
            padding: 16px 17px;
            background: rgba(255,255,255,0.92);
            border: 1px solid rgba(15,23,42,0.08);
            box-shadow: 0 10px 26px rgba(15,23,42,0.06);
        }}

        .wc-kpi-label {{
            color: #64748B;
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 8px;
        }}

        .wc-kpi-value {{
            font-size: 28px;
            font-weight: 950;
            color: #07111F;
            letter-spacing: -0.04em;
        }}

        .wc-kpi-note {{
            color: #94A3B8;
            font-size: 12px;
            margin-top: 3px;
        }}

        .wc-status-legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin: 8px 0 18px 0;
        }}

        .wc-legend-item {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 11px;
            border-radius: 999px;
            background: rgba(255,255,255,0.82);
            border: 1px solid rgba(15,23,42,0.08);
            font-size: 13px;
            color: #334155;
            font-weight: 700;
        }}

        .wc-dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }}

        div[data-testid="stMetric"] {{
            background: rgba(255,255,255,0.76);
            border: 1px solid rgba(15,23,42,0.08);
            padding: 12px 14px;
            border-radius: 16px;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
        }}

        div[data-testid="stMetricLabel"] {{
            color: #64748B;
            font-weight: 800;
        }}

        div[data-testid="stMetricValue"] {{
            color: #07111F;
            font-weight: 950;
        }}

        .stButton > button {{
            border-radius: 999px;
            font-weight: 850;
            border: 1px solid rgba(18, 60, 105, 0.22);
            box-shadow: 0 7px 18px rgba(18, 60, 105, 0.12);
            transition: 0.18s ease;
        }}

        .stButton > button:hover {{
            border-color: #F5C542;
            color: #07111F;
            transform: translateY(-1px);
        }}

        /* Fix nút Đăng xuất trong sidebar: nền trắng nhưng chữ không bị trắng theo sidebar */
        section[data-testid="stSidebar"] .stButton > button {{
            background: rgba(255, 255, 255, 0.96) !important;
            color: #07111F !important;
            border: 1px solid rgba(245, 197, 66, 0.35) !important;
        }}

        section[data-testid="stSidebar"] .stButton > button * {{
            color: #07111F !important;
        }}

        section[data-testid="stSidebar"] .stButton > button:hover {{
            background: #F5C542 !important;
            color: #07111F !important;
            border-color: #F5C542 !important;
        }}

        .stSelectbox div[data-baseweb="select"] > div,
        .stNumberInput input,
        .stTextInput input {{
            border-radius: 13px;
        }}

        .wc-footer {{
            text-align: center;
            color: #64748B;
            font-size: 13px;
            margin-top: 28px;
            padding: 18px 0 10px 0;
        }}

        .wc-footer a {{
            color: #123C69;
            font-weight: 800;
            text-decoration: none;
        }}

        /* =========================
           Add clickable "Menu" text to Streamlit native sidebar toggle
           ========================= */

        button[data-testid="stBaseButton-headerNoPadding"]:first-of-type,
        button[kind="headerNoPadding"]:first-of-type {{
            width: auto !important;
            min-width: 88px !important;
            height: 38px !important;
            min-height: 38px !important;
            padding: 0 12px !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: flex-start !important;
            gap: 8px !important;
            border-radius: 999px !important;
            background: transparent !important;
            box-shadow: none !important;
            border: none !important;
        }}

        button[data-testid="stBaseButton-headerNoPadding"]:first-of-type::after,
        button[kind="headerNoPadding"]:first-of-type::after {{
            content: "MENU";
            display: inline-block;
            color: #07111F;
            font-size: 14px;
            font-weight: 900;
            letter-spacing: 0.01em;
            line-height: 1;
            margin-left: 4px;
        }}
        /* Khi sidebar đang mở, nút nằm trên nền xanh đậm nên chữ Menu phải chuyển sang trắng */
        section[data-testid="stSidebar"] button[data-testid="stBaseButton-headerNoPadding"]:first-of-type::after,
        section[data-testid="stSidebar"] button[kind="headerNoPadding"]:first-of-type::after {{
            color: #F8FAFC !important;
        }}

        section[data-testid="stSidebar"] button[data-testid="stBaseButton-headerNoPadding"]:first-of-type svg,
        section[data-testid="stSidebar"] button[kind="headerNoPadding"]:first-of-type svg {{
            color: #F8FAFC !important;
            stroke: #F8FAFC !important;
        }}

        section[data-testid="stSidebar"] button[data-testid="stBaseButton-headerNoPadding"]:first-of-type:hover,
        section[data-testid="stSidebar"] button[kind="headerNoPadding"]:first-of-type:hover {{
            background: rgba(255,255,255,0.08) !important;
        }}

        button[data-testid="stBaseButton-headerNoPadding"]:first-of-type:hover,
        button[kind="headerNoPadding"]:first-of-type:hover {{
            background: rgba(15,23,42,0.05) !important;
        }}

        button[data-testid="stBaseButton-headerNoPadding"]:first-of-type svg,
        button[kind="headerNoPadding"]:first-of-type svg {{
            width: 20px !important;
            height: 20px !important;
            color: #64748B !important;
            stroke: #64748B !important;
        }}
        .wc-match-title-mobile {{
            display: none;
        }}

        @media (max-width: 768px) {{
            .wc-match-title-mobile {{
                display: block;
                width: 100%;
                max-width: 100%;
                margin: 2px 0 10px 0;
            }}

            .wc-match-title-mobile .wc-match-team {{
                display: block;
                width: 100%;
                max-width: 100%;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                color: #07111F;
                font-size: clamp(20px, 5.6vw, 23px);
                line-height: 1.13;
                font-weight: 950;
                letter-spacing: -0.035em;
            }}

            .wc-match-title-mobile .wc-match-vs {{
                display: block;
                width: 100%;
                color: #07111F;
                font-size: clamp(18px, 5vw, 21px);
                line-height: 1.08;
                font-weight: 950;
                letter-spacing: -0.025em;
            }}
        }}

        @media (max-width: 390px) {{
            .wc-match-title-mobile .wc-match-team {{
                font-size: 20px;
            }}

            .wc-match-title-mobile .wc-match-vs {{
                font-size: 18px;
            }}
        }}
        @media (max-width: 900px) {{
            .wc-hero-grid {{
                grid-template-columns: 1fr;
            }}

            .wc-hero-orb,
            .wc-hero-img {{
                display: none;
            }}

            .wc-kpi-grid {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True
    )


inject_worldcup_theme()

def inject_mobile_match_title_css():
    st.markdown(
        """
        <style>
        .wc-match-title-mobile {
            display: none;
        }

        @media (max-width: 768px) {
            div[class*="st-key-match_title_desktop_"] {
                display: none !important;
            }

            .wc-match-title-mobile {
                display: block;
                width: 100%;
                max-width: 100%;
                margin: 2px 0 10px 0;
            }

            .wc-match-title-mobile .wc-match-team {
                display: block;
                width: 100%;
                max-width: 100%;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                color: #07111F;
                font-size: clamp(20px, 5.6vw, 23px);
                line-height: 1.13;
                font-weight: 950;
                letter-spacing: -0.035em;
            }

            .wc-match-title-mobile .wc-match-vs {
                display: block;
                width: 100%;
                color: #07111F;
                font-size: clamp(18px, 5vw, 21px);
                line-height: 1.08;
                font-weight: 950;
                letter-spacing: -0.025em;
            }
        }

        @media (max-width: 390px) {
            .wc-match-title-mobile .wc-match-team {
                font-size: 20px;
            }

            .wc-match-title-mobile .wc-match-vs {
                font-size: 18px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )


inject_mobile_match_title_css()

def inject_mobile_goal_scorer_button_css():
    """
    CSS riêng cho nút Xem cầu thủ ghi bàn trên mobile.

    Mục tiêu:
    - Chỉ áp dụng trên điện thoại.
    - Không thay đổi logic nút.
    - Không ảnh hưởng desktop.
    - Ép chữ trong nút chỉ hiển thị trên 1 dòng.
    - Tạo thêm khoảng cách phía trên nút để tránh bị sát phần "Thắng chung cuộc"
      khi card kết quả có thêm penalty.
    """
    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            div[class*="st-key-goal_scorers_button_"] {
                width: auto !important;
                max-width: 100% !important;

                /* Chỉnh khoảng cách nút với phần phía trên ở mobile */
                margin-top: 18px !important;
                margin-bottom: 8px !important;
            }

            div[class*="st-key-goal_scorers_button_"] button {
                width: auto !important;
                min-width: 172px !important;
                max-width: 100% !important;
                min-height: 42px !important;
                padding: 8px 14px !important;
                display: inline-flex !important;
                align-items: center !important;
                justify-content: center !important;
                flex-wrap: nowrap !important;
                white-space: nowrap !important;
                font-size: 13px !important;
                line-height: 1 !important;
            }

            div[class*="st-key-goal_scorers_button_"] button * {
                white-space: nowrap !important;
                word-break: keep-all !important;
                overflow-wrap: normal !important;
                line-height: 1 !important;
                font-size: inherit !important;
            }
        }

        @media (max-width: 390px) {
            div[class*="st-key-goal_scorers_button_"] {
                margin-top: 20px !important;
                margin-bottom: 8px !important;
            }

            div[class*="st-key-goal_scorers_button_"] button {
                min-width: 164px !important;
                padding-left: 12px !important;
                padding-right: 12px !important;
                font-size: 12.5px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )


inject_mobile_goal_scorer_button_css()

def inject_mobile_goal_scorer_panel_css():
    """
    CSS riêng cho box Cầu thủ ghi bàn.

    Mục tiêu:
    - Desktop: in đậm tên đội trong danh sách cầu thủ ghi bàn.
    - Mobile: giữ logic kéo rộng box như hiện tại.
    - Không đổi logic render dữ liệu.
    """
    st.markdown(
        """
        <style>
        /* Desktop: in đậm tên đội khi xem cầu thủ ghi bàn */
        @media (min-width: 769px) {
            .wc-goal-scorer-team {
                font-weight: 950 !important;
                color: #07111F !important;
                white-space: nowrap !important;
            }

            .wc-goal-scorer-names {
                color: #334155 !important;
            }
        }

        @media (max-width: 768px) {
            .wc-goal-scorers-box {
                width: calc(100vw - 78px) !important;
                max-width: calc(100vw - 78px) !important;
                box-sizing: border-box !important;
                margin-top: 10px !important;
                margin-bottom: 18px !important;
            }

            .wc-goal-scorer-line {
                width: 100% !important;
                max-width: 100% !important;
                margin-top: 3px !important;
                white-space: normal !important;
                word-break: normal !important;
                overflow-wrap: normal !important;
            }

            .wc-goal-scorer-team {
                font-weight: 900 !important;
                color: #0F172A !important;
                white-space: nowrap !important;
            }

            .wc-goal-scorer-names {
                color: #334155 !important;
                white-space: normal !important;
                word-break: normal !important;
                overflow-wrap: normal !important;
            }
        }

        @media (max-width: 390px) {
            .wc-goal-scorers-box {
                width: calc(100vw - 70px) !important;
                max-width: calc(100vw - 70px) !important;
                font-size: 12.5px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )


inject_mobile_goal_scorer_panel_css()

def inject_ai_summary_button_css():
    ai_summary_icon_svg = """
    <svg xmlns="http://www.w3.org/2000/svg"
         width="24"
         height="24"
         viewBox="0 0 24 24"
         fill="none"
         stroke="currentColor"
         stroke-width="1"
         stroke-linecap="round"
         stroke-linejoin="round"
         class="icon icon-tabler icons-tabler-outline icon-tabler-file-text-ai">
      <path stroke="none" d="M0 0h24v24H0z" fill="none" />
      <path d="M14 3v4a1 1 0 0 0 1 1h4" />
      <path d="M10 21h-3a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v3.5" />
      <path d="M9 9h1" />
      <path d="M9 13h2.5" />
      <path d="M9 17h1" />
      <path d="M14 21v-4a2 2 0 1 1 4 0v4" />
      <path d="M14 19h4" />
      <path d="M21 15v6" />
    </svg>
    """

    ai_summary_icon_base64 = base64.b64encode(
        ai_summary_icon_svg.encode("utf-8")
    ).decode("utf-8")

    st.markdown(
        f"""
        <style>
        div[class*="st-key-ai_summary_button_"] {{
            margin-bottom: 14px !important;
        }}

        div[class*="st-key-ai_summary_button_"] button {{
            width: 100% !important;
            min-height: 48px !important;
            padding: 10px 18px !important;

            border-radius: 14px !important;
            border: 1.6px solid transparent !important;

            background:
                linear-gradient(#FFFFFF, #FFFFFF) padding-box,
                linear-gradient(90deg, #69D2FF 0%, #B66DFF 100%) border-box !important;

            color: #1F2937 !important;
            box-shadow: 0 3px 10px rgba(15, 23, 42, 0.06) !important;

            font-size: 14px !important;
            font-weight: 700 !important;
            line-height: 1 !important;
            white-space: nowrap !important;

            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 10px !important;

            transition:
                transform 0.18s ease,
                box-shadow 0.18s ease,
                filter 0.18s ease !important;
        }}

        div[class*="st-key-ai_summary_button_"] button::before {{
            content: "";
            display: inline-block;
            width: 18px;
            height: 18px;
            flex: 0 0 auto;

            background: linear-gradient(135deg, #6CCBFF 0%, #A855F7 100%);
            -webkit-mask: url("data:image/svg+xml;base64,{ai_summary_icon_base64}") center / contain no-repeat;
            mask: url("data:image/svg+xml;base64,{ai_summary_icon_base64}") center / contain no-repeat;
        }}

        div[class*="st-key-ai_summary_button_"] button:hover {{
            transform: translateY(-1px) !important;
            box-shadow: 0 6px 16px rgba(15, 23, 42, 0.10) !important;
            filter: brightness(0.995) !important;
        }}

        div[class*="st-key-ai_summary_button_"] button:active {{
            transform: translateY(0) scale(0.995) !important;
        }}

        div[class*="st-key-ai_summary_button_"] button * {{
            color: #1F2937 !important;
            white-space: nowrap !important;
            word-break: keep-all !important;
            overflow-wrap: normal !important;
            line-height: 1 !important;
            font-size: inherit !important;
            font-weight: inherit !important;
        }}

        @media (max-width: 768px) {{
            div[class*="st-key-ai_summary_button_"] button {{
                min-height: 45px !important;
                padding: 9px 14px !important;
                font-size: 13px !important;
                border-radius: 13px !important;
            }}

            div[class*="st-key-ai_summary_button_"] button::before {{
                width: 17px;
                height: 17px;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True
    )


inject_ai_summary_button_css()

def get_prediction_radio_css():
    return """
    label[data-baseweb="radio"] {
        display: inline-flex !important;
        align-items: center !important;
        gap: 8px !important;
        padding: 2px 8px 2px 2px !important;
        border-radius: 999px !important;
        border: 1px solid transparent !important;
        background: transparent !important;
        transition:
            background 0.16s ease,
            border-color 0.16s ease,
            color 0.16s ease;
    }

    label[data-baseweb="radio"]:has(input:checked) {
        background: rgba(245, 197, 66, 0.14) !important;
        border-color: rgba(245, 197, 66, 0.32) !important;
        color: #07111F !important;
        font-weight: 800 !important;
    }

    label[data-baseweb="radio"] > div:first-child {
        width: 16px !important;
        height: 16px !important;
        min-width: 16px !important;
        min-height: 16px !important;

        border-radius: 999px !important;
        border: 2px solid #CBD5E1 !important;
        background: #FFFFFF !important;

        box-shadow: none !important;
        position: relative !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin-right: 2px !important;
        box-sizing: border-box !important;
        overflow: hidden !important;

        transition:
            border-color 0.16s ease,
            background 0.16s ease,
            box-shadow 0.16s ease;
    }

    /* Ẩn phần tick/chấm mặc định bên trong radio của Streamlit/BaseWeb */
    label[data-baseweb="radio"] > div:first-child * {
        opacity: 0 !important;
    }

    /* Không vẽ chấm riêng nữa */
    label[data-baseweb="radio"] > div:first-child::before,
    label[data-baseweb="radio"] > div:first-child::after {
        content: none !important;
        display: none !important;
    }

    /* Khi chọn: tô vàng toàn bộ hình tròn */
    label[data-baseweb="radio"]:has(input:checked) > div:first-child {
        border-color: #D97706 !important;
        background: #F5C542 !important;
        box-shadow: 0 0 0 3px rgba(245, 197, 66, 0.22) !important;
    }

    label[data-baseweb="radio"]:hover > div:first-child {
        border-color: #F5C542 !important;
    }
    """

def get_star_radio_css(
    disable_hope: bool = False,
    disable_super: bool = False
) -> str:
    css = get_prediction_radio_css()

    if disable_hope:
        css += """
        label[data-baseweb="radio"]:nth-of-type(2) {
            opacity: 0.48 !important;
            pointer-events: none !important;
            color: #94A3B8 !important;
            background: rgba(148, 163, 184, 0.08) !important;
            border-color: rgba(148, 163, 184, 0.16) !important;
        }

        label[data-baseweb="radio"]:nth-of-type(2) * {
            color: #94A3B8 !important;
        }
        """

    if disable_super:
        css += """
        label[data-baseweb="radio"]:nth-of-type(3) {
            opacity: 0.48 !important;
            pointer-events: none !important;
            color: #94A3B8 !important;
            background: rgba(148, 163, 184, 0.08) !important;
            border-color: rgba(148, 163, 184, 0.16) !important;
        }

        label[data-baseweb="radio"]:nth-of-type(3) * {
            color: #94A3B8 !important;
        }
        """

    return css

def get_prediction_action_spacing_css():
    return """
    {
        margin-top: 16px !important;
        margin-bottom: 18px !important;
    }

    button {
        white-space: nowrap !important;
    }

    button * {
        white-space: nowrap !important;
        word-break: keep-all !important;
        overflow-wrap: normal !important;
    }

    @media (max-width: 768px) {
        {
            margin-top: 15px !important;
            margin-bottom: 20px !important;
        }
    }
    """

def inject_sidebar_menu_radio_css():
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] div[class*="st-key-selected_page"] label[data-baseweb="radio"] {
            display: inline-flex !important;
            align-items: center !important;
            gap: 10px !important;

            width: fit-content !important;
            min-height: 42px !important;

            padding: 10px 14px !important;
            margin: 0 0 8px 0 !important;

            border-radius: 16px !important;
            border: 1px solid rgba(255,255,255,0.08) !important;
            background: rgba(255,255,255,0.06) !important;

            color: #F8FAFC !important;
            font-weight: 800 !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            cursor: pointer !important;
        }

        section[data-testid="stSidebar"] div[class*="st-key-selected_page"] label[data-baseweb="radio"]:has(input:checked) {
            background: linear-gradient(
                90deg,
                rgba(245,197,66,0.28),
                rgba(0,180,216,0.14)
            ) !important;
            border-color: rgba(245,197,66,0.66) !important;
        }

        section[data-testid="stSidebar"] div[class*="st-key-selected_page"] label[data-baseweb="radio"] > div:first-child {
            width: 18px !important;
            height: 18px !important;
            min-width: 18px !important;
            min-height: 18px !important;

            border-radius: 999px !important;
            border: 2px solid #CBD5E1 !important;
            background: #FFFFFF !important;
            background-image: none !important;

            box-shadow: none !important;
            box-sizing: border-box !important;

            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;

            position: relative !important;
            overflow: hidden !important;
            margin-right: 0 !important;
        }

        section[data-testid="stSidebar"] div[class*="st-key-selected_page"] label[data-baseweb="radio"] > div:first-child * {
            opacity: 0 !important;
            background-image: none !important;
            color: transparent !important;
            box-shadow: none !important;
        }

        section[data-testid="stSidebar"] div[class*="st-key-selected_page"] label[data-baseweb="radio"] > div:first-child::before,
        section[data-testid="stSidebar"] div[class*="st-key-selected_page"] label[data-baseweb="radio"] > div:first-child::after {
            content: none !important;
            display: none !important;
        }

        section[data-testid="stSidebar"] div[class*="st-key-selected_page"] label[data-baseweb="radio"]:has(input:checked) > div:first-child {
            border-color: #D97706 !important;
            background: #F5C542 !important;
            background-image: none !important;
            box-shadow: 0 0 0 3px rgba(245, 197, 66, 0.22) !important;
        }

        section[data-testid="stSidebar"] div[class*="st-key-selected_page"] label[data-baseweb="radio"]:hover > div:first-child {
            border-color: #F5C542 !important;
        }

        section[data-testid="stSidebar"] div[class*="st-key-selected_page"] label[data-baseweb="radio"] p,
        section[data-testid="stSidebar"] div[class*="st-key-selected_page"] label[data-baseweb="radio"] span {
            color: #F8FAFC !important;
            font-weight: 800 !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

inject_sidebar_menu_radio_css()

def render_sidebar_brand():
    app_logo_src = resolve_asset_src(APP_LOGO_URL)

    if app_logo_src:
        logo_html = f'<img class="wc-logo-img" src="{app_logo_src}" alt="App logo">'
    else:
        logo_html = '<div class="wc-logo-fallback">WC<br>26</div>'

    st.markdown(
        f"""
        <div class="wc-sidebar-brand">
            <div class="wc-logo-row">
                {logo_html}
                <div>
                    <div class="wc-brand-title">{APP_SHORT_NAME}</div>
                    <div class="wc-brand-subtitle">Prediction Arena</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_sidebar_footer():
    project_link_html = ""

    if FOOTER_PROJECT_URL:
        project_link_html = f"""
        <div style="margin-top:10px;">
            <a href="{FOOTER_PROJECT_URL}" target="_blank">Xem project ↗</a>
        </div>
        """

    image_html = ""

    sidebar_decoration_src = resolve_asset_src(SIDEBAR_DECORATION_URL)

    if sidebar_decoration_src:
        image_html = f"""
        <img class="wc-sidebar-decoration" src="{sidebar_decoration_src}" alt="Sidebar decoration">
        """

    st.markdown(
        f"""
        <div class="wc-sidebar-footer">
            <strong>One World. One Game.</strong>
            <div style="margin-top:6px;color:#CBD5E1;">
                Developed by JKH
            </div>
            {project_link_html}
            {image_html}
        </div>
        """,
        unsafe_allow_html=True
    )


def render_app_hero():
    hero_trophy_src = resolve_asset_src(HERO_TROPHY_IMAGE_URL)

    if hero_trophy_src:
        hero_visual = f'<img class="wc-hero-img" src="{hero_trophy_src}" alt="Hero visual">'
    else:
        hero_visual = '<div class="wc-hero-orb">2026</div>'

    st.markdown(
        f"""
        <div class="wc-hero">
            <div class="wc-hero-grid">
                <div>
                    <div class="wc-eyebrow">⚽ Tournament Prediction Hub</div>
                    <div class="wc-hero-title">
                        World Cup <span class="wc-gold">2026</span><br>
                        Prediction Arena
                    </div>
                    <div class="wc-hero-subtitle">
                        {APP_TAGLINE}
                    </div>
                    <div class="wc-hero-actions">
                        <div class="wc-pill">Leaderboard</div>
                        <div class="wc-pill">Exact score challenge</div>
                        <div class="wc-pill">North America 2026</div>
                    </div>
                </div>
                <div>
                    {hero_visual}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_page_title(title: str, subtitle: str = ""):
    st.markdown(
        f"""
        <div class="wc-page-title">
            <h2>{title}</h2>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_status_legend():
    st.markdown(
        """
        <div class="wc-status-legend">
            <div class="wc-legend-item"><span class="wc-dot" style="background:#2563EB;"></span>Đang mở dự đoán</div>
            <div class="wc-legend-item"><span class="wc-dot" style="background:#F59E0B;"></span>Đã khóa</div>
            <div class="wc-legend-item"><span class="wc-dot" style="background:#16A34A;"></span>Đã có kết quả</div>
            <div class="wc-legend-item"><span class="wc-dot" style="background:#9CA3AF;"></span>Chưa xác định đội</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_kpi_tiles(matches: pd.DataFrame):
    total_matches = len(matches)

    finished_matches = int(matches["is_finished"].apply(to_bool).sum())
    unknown_matches = int(
        matches.apply(
            lambda row: is_unknown_team(row.get("home_team_name")) or is_unknown_team(row.get("away_team_name")),
            axis=1
        ).sum()
    )

    now_utc = pd.Timestamp.now(tz="UTC")

    open_matches = int(
        (
            (matches["kickoff_time_utc_dt"] > now_utc)
            & (~matches["is_finished"].apply(to_bool))
        ).sum()
    )

    locked_matches = int(
        (
            (matches["kickoff_time_utc_dt"] <= now_utc)
            & (~matches["is_finished"].apply(to_bool))
        ).sum()
    )

    st.markdown(
        f"""
        <div class="wc-kpi-grid">
            <div class="wc-kpi-tile">
                <div class="wc-kpi-label">Tổng số trận</div>
                <div class="wc-kpi-value">{total_matches}</div>
            </div>
            <div class="wc-kpi-tile">
                <div class="wc-kpi-label">Đang mở dự đoán</div>
                <div class="wc-kpi-value" style="color:#2563EB;">{open_matches}</div>
            </div>
            <div class="wc-kpi-tile">
                <div class="wc-kpi-label">Đã có kết quả</div>
                <div class="wc-kpi-value" style="color:#16A34A;">{finished_matches}</div>
            </div>
            <div class="wc-kpi-tile">
                <div class="wc-kpi-label">Chưa xác định đội</div>
                <div class="wc-kpi-value" style="color:#64748B;">{unknown_matches}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

def render_star_balance(user_id: int):
    usage = get_user_star_usage(user_id)

    st.markdown(
        """
        <div style="
            margin-top: 26px;
            margin-bottom: 12px;
        ">
            <div style="
                color: #07111F;
                font-weight: 950;
                font-size: 20px;
                letter-spacing: -0.02em;
                line-height: 1.2;
            ">
                Bổ trợ
            </div>
            <div style="
                color: #64748B;
                font-size: 13px;
                margin-top: 4px;
            ">
                Sử dụng sao để nhân điểm cho những trận bạn tự tin nhất. Có thể chọn sử dụng khi dự đoán tỉ số từng trận phía dưới. Mỗi trận chỉ được dùng tối đa 1 sao.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    col_hope, col_super = st.columns([1, 1], gap="large")

    with col_hope:
        with stylable_container(
            key="hope_star_balance_card",
            css_styles="""
            {
                background: linear-gradient(135deg, #FFF7ED, #FFFFFF);
                border: 1px solid rgba(245, 158, 11, 0.32);
                border-radius: 22px;
                padding: 24px 28px;
                box-shadow: 0 12px 30px rgba(15, 23, 42, 0.07);
                margin: 0 0 28px 0;
                min-height: 142px;
                width: 100%;
                box-sizing: border-box;
            }

            @media (max-width: 768px) {
                {
                    height: 150px !important;
                    min-height: 150px !important;
                    max-height: 150px !important;
                    width: 100% !important;
            
                    padding: 17px 10px 12px 14px !important;
                    margin: 0 0 22px 0 !important;
            
                    overflow: hidden !important;
                    box-sizing: border-box !important;
                }
            
                .wc-star-balance-title {
                    width: 100% !important;
                    min-height: 38px !important;
                    margin-bottom: 12px !important;
            
                    font-size: 13.5px !important;
                    line-height: 1.32 !important;
                    font-weight: 900 !important;
            
                    text-align: left !important;
                    white-space: normal !important;
                    word-break: normal !important;
                    overflow-wrap: normal !important;
                }
            
                .wc-star-balance-value {
                    width: 100% !important;
                    min-height: 31px !important;
                    margin-bottom: 7px !important;
            
                    font-size: 31px !important;
                    line-height: 1 !important;
                    font-weight: 950 !important;
            
                    text-align: left !important;
                }
            
                .wc-star-balance-note {
                    width: 100% !important;
                    min-height: 31px !important;
            
                    font-size: 11.5px !important;
                    line-height: 1.28 !important;
            
                    text-align: left !important;
                    white-space: normal !important;
                    word-break: normal !important;
                    overflow-wrap: normal !important;
                }
            }
            
            @media (max-width: 390px) {
                {
                    height: 150px !important;
                    min-height: 150px !important;
                    max-height: 150px !important;
            
                    padding-left: 12px !important;
                    padding-right: 8px !important;
                }
            
                .wc-star-balance-title {
                    min-height: 38px !important;
                    font-size: 13px !important;
                    line-height: 1.32 !important;
                    margin-bottom: 12px !important;
                }
            
                .wc-star-balance-value {
                    min-height: 30px !important;
                    font-size: 30px !important;
                    margin-bottom: 7px !important;
                }
            
                .wc-star-balance-note {
                    min-height: 31px !important;
                    font-size: 11px !important;
                    line-height: 1.28 !important;
                }
            }
            """
        ):
            st.markdown(
                """
                <div class="wc-star-balance-title" style="
                    color:#92400E;
                    font-weight:900;
                    font-size:15px;
                    line-height:1.2;
                    margin-bottom:24px;
                ">
                    ⭐ Ngôi sao hy vọng
                </div>
                """,
                unsafe_allow_html=True
            )

            st.markdown(
                f"""
                <div class="wc-star-balance-value" style="
                    color:#07111F;
                    font-weight:950;
                    font-size:36px;
                    line-height:1;
                    margin-bottom:16px;
                ">
                    {usage["hope_left"]}/{HOPE_STARS_PER_USER}
                </div>
                """,
                unsafe_allow_html=True
            )

            st.markdown(
                """
                <div class="wc-star-balance-note" style="
                    color:#64748B;
                    font-size:13px;
                    line-height:1.35;
                ">
                    x2 điểm dự đoán của trận được chọn
                </div>
                """,
                unsafe_allow_html=True
            )

    with col_super:
        with stylable_container(
            key="super_star_balance_card",
            css_styles="""
            {
                background: linear-gradient(135deg, #FEF3C7, #FFFFFF);
                border: 1px solid rgba(245, 197, 66, 0.50);
                border-radius: 22px;
                padding: 24px 28px;
                box-shadow: 0 12px 30px rgba(15, 23, 42, 0.07);
                margin: 0 0 28px 0;
                min-height: 142px;
                width: 100%;
                box-sizing: border-box;
            }
            @media (max-width: 768px) {
                {
                    height: 150px !important;
                    min-height: 150px !important;
                    max-height: 150px !important;
                    width: 100% !important;
            
                    padding: 17px 10px 12px 14px !important;
                    margin: 0 0 22px 0 !important;
            
                    overflow: hidden !important;
                    box-sizing: border-box !important;
                }
            
                .wc-star-balance-title {
                    width: 100% !important;
                    min-height: 38px !important;
                    margin-bottom: 12px !important;
            
                    font-size: 13.5px !important;
                    line-height: 1.32 !important;
                    font-weight: 900 !important;
            
                    text-align: left !important;
                    white-space: normal !important;
                    word-break: normal !important;
                    overflow-wrap: normal !important;
                }
            
                .wc-star-balance-value {
                    width: 100% !important;
                    min-height: 31px !important;
                    margin-bottom: 7px !important;
            
                    font-size: 31px !important;
                    line-height: 1 !important;
                    font-weight: 950 !important;
            
                    text-align: left !important;
                }
            
                .wc-star-balance-note {
                    width: 100% !important;
                    min-height: 31px !important;
            
                    font-size: 11.5px !important;
                    line-height: 1.28 !important;
            
                    text-align: left !important;
                    white-space: normal !important;
                    word-break: normal !important;
                    overflow-wrap: normal !important;
                }
            }

            @media (max-width: 390px) {
                {
                    height: 150px !important;
                    min-height: 150px !important;
                    max-height: 150px !important;
            
                    padding-left: 12px !important;
                    padding-right: 8px !important;
                }
            
                .wc-star-balance-title {
                    min-height: 38px !important;
                    font-size: 13px !important;
                    line-height: 1.32 !important;
                    margin-bottom: 12px !important;
                }
            
                .wc-star-balance-value {
                    min-height: 30px !important;
                    font-size: 30px !important;
                    margin-bottom: 7px !important;
                }
            
                .wc-star-balance-note {
                    min-height: 31px !important;
                    font-size: 11px !important;
                    line-height: 1.28 !important;
                }
            }
            """
        ):
            st.markdown(
                """
                <div class="wc-star-balance-title" style="
                    color:#78350F;
                    font-weight:900;
                    font-size:15px;
                    line-height:1.2;
                    margin-bottom:24px;
                ">
                    ✨ Siêu sao
                </div>
                """,
                unsafe_allow_html=True
            )

            st.markdown(
                f"""
                <div class="wc-star-balance-value" style="
                    color:#07111F;
                    font-weight:950;
                    font-size:36px;
                    line-height:1;
                    margin-bottom:16px;
                ">
                    {usage["super_left"]}/{SUPER_STARS_PER_USER}
                </div>
                """,
                unsafe_allow_html=True
            )

            st.markdown(
                """
                <div class="wc-star-balance-note" style="
                    color:#64748B;
                    font-size:13px;
                    line-height:1.35;
                ">
                    x3 điểm dự đoán của trận được chọn
                </div>
                """,
                unsafe_allow_html=True
            )

def render_scoring_rules():
    with stylable_container(
        key="scoring_rules_expander_shell",
        css_styles="""
        {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            padding: 0 !important;
            margin: 4px 0 28px 0;
        }

        div[data-testid="stExpander"] {
            border: none !important;
            background: transparent !important;
        }

        div[data-testid="stExpander"] details {
            border: 1px solid rgba(245, 197, 66, 0.60) !important;
            border-left: 6px solid #F5C542 !important;
            border-radius: 18px !important;
            background:
                radial-gradient(circle at top left, rgba(245, 197, 66, 0.18), transparent 28%),
                linear-gradient(135deg, rgba(255, 251, 235, 0.98), rgba(255, 255, 255, 0.94)) !important;
            box-shadow: 0 14px 34px rgba(15, 23, 42, 0.08) !important;
            overflow: hidden !important;
        }

        div[data-testid="stExpander"] summary {
            padding: 15px 18px !important;
            font-weight: 950 !important;
            color: #07111F !important;
            font-size: 16px !important;
            letter-spacing: -0.01em !important;
        }

        div[data-testid="stExpander"] summary:hover {
            background: rgba(245, 197, 66, 0.12) !important;
        }

        div[data-testid="stExpander"] details[open] summary {
            border-bottom: 1px solid rgba(245, 197, 66, 0.30) !important;
        }

        div[data-testid="stExpander"] div[data-testid="stMarkdownContainer"] {
            color: #334155 !important;
        }
        """
    ):
        with st.expander("Cách tính điểm", expanded=False):
            st.markdown(
                f"""
                **Vòng bảng**

                - Đúng hoàn toàn tỉ số: **+3 điểm**
                - Đúng kết quả thắng/hòa/thua: **+1 điểm**
                - Sai kết quả: **0 điểm**

                **Vòng knockout**

                - Điểm = **điểm tỉ số + điểm đội thắng chung cuộc**
                - Điểm tỉ số vẫn tính như vòng bảng: **+3 / +1 / 0**
                - Đúng đội thắng chung cuộc: **+1 điểm**
                - Nếu dự đoán hòa trong 120 phút, cần chọn thêm đội thắng chung cuộc.

                **Bổ trợ**

                - {STAR_CONFIG[STAR_TYPE_HOPE]["short_label"]}: **x2** tổng điểm trận đó
                - {STAR_CONFIG[STAR_TYPE_SUPER]["short_label"]}: **x3** tổng điểm trận đó
                """
            )

def render_sidebar_star_balance(user_id: int):
    usage = get_user_star_usage(user_id)

    st.markdown(
        f"""
        <div style="
            margin-top: 10px;
            padding: 12px 13px;
            border-radius: 16px;
            background: rgba(255,255,255,0.07);
            border: 1px solid rgba(255,255,255,0.12);
        ">
            <div style="font-weight:900;color:#F8FAFC;margin-bottom:8px;">
                Kho sao của bạn
            </div>
            <div style="font-size:13px;color:#CBD5E1;">
                ⭐ Ngôi sao hy vọng: <b style="color:#F5C542;">{usage["hope_left"]}/{HOPE_STARS_PER_USER}</b>
            </div>
            <div style="font-size:13px;color:#CBD5E1;margin-top:4px;">
                ✨ Siêu sao: <b style="color:#F5C542;">{usage["super_left"]}/{SUPER_STARS_PER_USER}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

def render_avatar_popover(user: dict):
    """
    Hiển thị avatar tròn ở góc trên bên phải.
    Bấm vào avatar để mở kho chọn avatar.

    Cập nhật UI:
    - Avatar chính có viền vàng nhẹ và badge bút chì nhỏ ở chính giữa mép dưới.
    - Popup desktop: 4 avatar mỗi hàng.
    - Popup mobile: 2 avatar mỗi hàng, card cao hơn, ảnh avatar lớn hơn để dễ nhìn.
    - Người dùng chọn avatar bằng cách bấm trực tiếp vào khung avatar.
    - CSS target theo key riêng để hạn chế ảnh hưởng các nút khác.
    """
    avatar_keys = load_avatar_keys()

    if not avatar_keys:
        return

    current_avatar_key = normalize_avatar_key(user.get("avatar_key"))
    current_avatar_src = get_avatar_src(current_avatar_key)

    def make_safe_key(text: str) -> str:
        return (
            str(text)
            .replace(".", "_")
            .replace("-", "_")
            .replace(" ", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )

    def render_avatar_grid(avatars_per_row: int, key_prefix: str):
        for start_idx in range(0, len(avatar_keys), avatars_per_row):
            row_avatar_keys = avatar_keys[start_idx:start_idx + avatars_per_row]
            cols = st.columns(avatars_per_row, gap="small")

            for col, avatar_key in zip(cols, row_avatar_keys):
                with col:
                    avatar_src = get_avatar_src(avatar_key)
                    is_selected = avatar_key == current_avatar_key

                    border_color = "#F5C542" if is_selected else "rgba(15,23,42,0.10)"
                    bg_color = "#FFF7ED" if is_selected else "#FFFFFF"
                    selected_shadow = (
                        "0 0 0 4px rgba(245,197,66,0.20), 0 10px 24px rgba(15,23,42,0.10)"
                        if is_selected
                        else "0 8px 20px rgba(15,23,42,0.06)"
                    )

                    safe_avatar_key = make_safe_key(avatar_key)
                    avatar_button_key = f"{key_prefix}_avatar_pick_{safe_avatar_key}"

                    st.markdown(
                        f"""
                        <style>
                        .st-key-{avatar_button_key} button {{
                            position: relative !important;
                            width: 100% !important;
                            height: 88px !important;
                            min-height: 88px !important;
                            padding: 0 !important;
                            margin: 0 0 8px 0 !important;
                            border-radius: 18px !important;
                            border: 2px solid {border_color} !important;
                            background: {bg_color} !important;
                            box-shadow: {selected_shadow} !important;
                            overflow: hidden !important;
                            cursor: pointer !important;
                            color: transparent !important;
                            font-size: 0 !important;
                            line-height: 0 !important;
                            transition:
                                transform 0.18s ease,
                                box-shadow 0.18s ease,
                                border-color 0.18s ease,
                                background 0.18s ease !important;
                        }}

                        .st-key-{avatar_button_key} button:hover {{
                            border-color: #F5C542 !important;
                            background: #FFF7ED !important;
                            transform: translateY(-1px) !important;
                            box-shadow: 0 0 0 4px rgba(245,197,66,0.18), 0 12px 28px rgba(15,23,42,0.13) !important;
                        }}

                        .st-key-{avatar_button_key} button:active {{
                            transform: translateY(0) scale(0.98) !important;
                        }}

                        .st-key-{avatar_button_key} button::before {{
                            content: "";
                            position: absolute;
                            left: 50%;
                            top: 50%;
                            width: 64px;
                            height: 64px;
                            transform: translate(-50%, -50%);
                            border-radius: 999px;
                            background-image: url("{avatar_src}");
                            background-size: cover;
                            background-position: center;
                            background-repeat: no-repeat;
                            border: 3px solid #FFFFFF;
                            box-shadow: 0 7px 18px rgba(15,23,42,0.16);
                        }}

                        .st-key-{avatar_button_key} button::after {{
                            content: {"'✓'" if is_selected else "''"};
                            position: absolute;
                            right: 13px;
                            bottom: 13px;
                            width: 22px;
                            height: 22px;
                            border-radius: 999px;
                            background: #F5C542;
                            color: #07111F;
                            border: 2px solid #FFFFFF;
                            display: {"flex" if is_selected else "none"};
                            align-items: center;
                            justify-content: center;
                            font-size: 13px;
                            font-weight: 950;
                            line-height: 1;
                            box-shadow: 0 5px 12px rgba(15,23,42,0.18);
                            pointer-events: none;
                        }}

                        .st-key-{avatar_button_key} button * {{
                            display: none !important;
                            visibility: hidden !important;
                            color: transparent !important;
                            font-size: 0 !important;
                            line-height: 0 !important;
                        }}

                        @media (max-width: 768px) {{
                            .st-key-{avatar_button_key} button {{
                                height: 112px !important;
                                min-height: 112px !important;
                                border-radius: 18px !important;
                                margin-bottom: 10px !important;
                            }}

                            .st-key-{avatar_button_key} button::before {{
                                width: 82px;
                                height: 82px;
                                border-width: 3px;
                                box-shadow: 0 8px 20px rgba(15,23,42,0.18);
                            }}

                            .st-key-{avatar_button_key} button::after {{
                                right: 12px;
                                bottom: 12px;
                                width: 22px;
                                height: 22px;
                                font-size: 12px;
                            }}
                        }}

                        @media (max-width: 390px) {{
                            .st-key-{avatar_button_key} button {{
                                height: 104px !important;
                                min-height: 104px !important;
                                border-radius: 16px !important;
                            }}

                            .st-key-{avatar_button_key} button::before {{
                                width: 76px;
                                height: 76px;
                            }}
                        }}
                        </style>
                        """,
                        unsafe_allow_html=True
                    )

                    avatar_clicked = st.button(
                        "Chọn avatar",
                        key=avatar_button_key,
                        use_container_width=True,
                        help="Bấm để chọn avatar này."
                    )

                    if avatar_clicked and not is_selected:
                        try:
                            selected_page_before_avatar_change = st.session_state.get(
                                "selected_page",
                                None
                            )
                    
                            update_user_avatar(
                                user_id=int(user["user_id"]),
                                avatar_key=avatar_key
                            )
                    
                            st.session_state["user"]["avatar_key"] = avatar_key
                    
                            if selected_page_before_avatar_change:
                                st.session_state["selected_page"] = selected_page_before_avatar_change
                                st.session_state["_selected_page_after_avatar_change"] = selected_page_before_avatar_change
                    
                            st.rerun()
                    
                        except ValueError as e:
                            st.error(str(e))

    with stylable_container(
        key="top_right_avatar_popover_shell",
        css_styles=f"""
        {{
            position: fixed;
            top: 72px;
            right: 26px;
            z-index: 999999;
            width: 72px !important;
            height: 72px !important;
            overflow: visible !important;
        }}

        div[data-testid="stPopover"] {{
            width: 72px !important;
            height: 72px !important;
            overflow: visible !important;
        }}

        div[data-testid="stPopover"] > button,
        div[data-testid="stPopover"] > div > button {{
            position: relative !important;
            width: 58px !important;
            height: 58px !important;
            min-width: 58px !important;
            min-height: 58px !important;
            max-width: 58px !important;
            max-height: 58px !important;
            padding: 0 !important;
            margin: 0 !important;
            border-radius: 999px !important;
            border: 3px solid #FFFFFF !important;
            outline: 2px solid rgba(245, 197, 66, 0.78) !important;
            outline-offset: 3px !important;
            background: url("{current_avatar_src}") center center / cover no-repeat !important;
            box-shadow:
                0 12px 30px rgba(7, 17, 31, 0.24),
                0 0 0 6px rgba(245, 197, 66, 0.08) !important;
            overflow: visible !important;
            cursor: pointer !important;
            font-size: 0 !important;
            line-height: 0 !important;
            color: transparent !important;
            transition:
                transform 0.18s ease,
                box-shadow 0.18s ease,
                border-color 0.18s ease,
                outline-color 0.18s ease !important;
        }}

        /* Badge bút chì nhỏ, nằm chính giữa mép dưới avatar */
        div[data-testid="stPopover"] > button::after,
        div[data-testid="stPopover"] > div > button::after {{
            content: "✎";
            position: absolute;
            left: 50%;
            bottom: -10px;
            right: auto;
            top: auto;
            width: 15px;
            height: 15px;
            border-radius: 999px;
            background: #F5C542;
            color: #07111F;
            border: 2px solid #FFFFFF;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 7px;
            font-weight: 950;
            line-height: 1;
            box-shadow: 0 4px 10px rgba(7, 17, 31, 0.18);
            pointer-events: none;
            transform: translateX(-50%);
            transition: transform 0.18s ease, background 0.18s ease;
        }}

        div[data-testid="stPopover"] > button::before,
        div[data-testid="stPopover"] > div > button::before {{
            content: "Đổi avatar";
            position: absolute;
            right: 68px;
            top: 50%;
            transform: translateY(-50%) translateX(8px);
            opacity: 0;
            pointer-events: none;
            white-space: nowrap;
            padding: 8px 11px;
            border-radius: 999px;
            background: rgba(7, 17, 31, 0.94);
            color: #F8FAFC;
            font-size: 12px;
            font-weight: 850;
            line-height: 1;
            box-shadow: 0 10px 24px rgba(7, 17, 31, 0.22);
            transition: opacity 0.18s ease, transform 0.18s ease;
        }}

        div[data-testid="stPopover"] > button:hover,
        div[data-testid="stPopover"] > div > button:hover {{
            transform: translateY(-1px) scale(1.045) !important;
            border-color: #F5C542 !important;
            outline-color: rgba(245, 197, 66, 0.96) !important;
            box-shadow:
                0 16px 36px rgba(7, 17, 31, 0.30),
                0 0 0 7px rgba(245, 197, 66, 0.12) !important;
        }}

        div[data-testid="stPopover"] > button:hover::before,
        div[data-testid="stPopover"] > div > button:hover::before {{
            opacity: 1;
            transform: translateY(-50%) translateX(0);
        }}

        div[data-testid="stPopover"] > button:hover::after,
        div[data-testid="stPopover"] > div > button:hover::after {{
            transform: translateX(-50%) scale(1.08);
            background: #FFD761;
        }}

        div[data-testid="stPopover"] > button:focus-visible,
        div[data-testid="stPopover"] > div > button:focus-visible {{
            outline: 3px solid rgba(37, 99, 235, 0.72) !important;
            outline-offset: 4px !important;
        }}

        div[data-testid="stPopover"] > button[aria-expanded="true"],
        div[data-testid="stPopover"] > div > button[aria-expanded="true"] {{
            border-color: #F5C542 !important;
            outline-color: rgba(245, 197, 66, 1) !important;
            box-shadow:
                0 16px 36px rgba(7, 17, 31, 0.30),
                0 0 0 7px rgba(245, 197, 66, 0.14) !important;
        }}

        div[data-testid="stPopover"] > button *,
        div[data-testid="stPopover"] > div > button * {{
            display: none !important;
            visibility: hidden !important;
            font-size: 0 !important;
            line-height: 0 !important;
            color: transparent !important;
        }}

        div[data-testid="stPopoverBody"],
        div[data-testid="stPopoverContent"] {{
            min-width: 520px !important;
            max-width: 560px !important;
            max-height: calc(100vh - 110px) !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            border-radius: 22px !important;
            box-shadow: 0 22px 56px rgba(7, 17, 31, 0.24) !important;
            border: 1px solid rgba(15, 23, 42, 0.10) !important;
        }}

        .wc-avatar-grid-desktop-shell {{
            display: block;
        }}

        .wc-avatar-grid-mobile-shell {{
            display: none;
        }}

        @media (max-width: 768px) {{
            {{
                top: 64px;
                right: 12px;
                width: 56px !important;
                height: 56px !important;
            }}

            div[data-testid="stPopover"] {{
                width: 56px !important;
                height: 56px !important;
            }}

            div[data-testid="stPopover"] > button,
            div[data-testid="stPopover"] > div > button {{
                width: 48px !important;
                height: 48px !important;
                min-width: 48px !important;
                min-height: 48px !important;
                max-width: 48px !important;
                max-height: 48px !important;
                border-width: 2px !important;
                outline-width: 2px !important;
                outline-offset: 2px !important;
                box-shadow:
                    0 10px 24px rgba(7, 17, 31, 0.22),
                    0 0 0 4px rgba(245, 197, 66, 0.10) !important;
            }}

            div[data-testid="stPopover"] > button::before,
            div[data-testid="stPopover"] > div > button::before {{
                display: none !important;
            }}

            div[data-testid="stPopover"] > button::after,
            div[data-testid="stPopover"] > div > button::after {{
                left: 50%;
                bottom: -8px;
                right: auto;
                top: auto;
                width: 13px;
                height: 13px;
                font-size: 6px;
                border-width: 2px;
                transform: translateX(-50%);
            }}

            div[data-testid="stPopover"] > button:hover::after,
            div[data-testid="stPopover"] > div > button:hover::after {{
                transform: translateX(-50%) scale(1.08);
            }}

            div[data-testid="stPopoverBody"],
            div[data-testid="stPopoverContent"] {{
                position: fixed !important;
                top: 82px !important;
                left: 50% !important;
                right: auto !important;
                transform: translateX(-50%) !important;
                width: min(360px, calc(100vw - 32px)) !important;
                min-width: unset !important;
                max-width: 360px !important;
                max-height: 64vh !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
                padding: 16px 14px !important;
                border-radius: 20px !important;
            }}

            .wc-avatar-grid-desktop-shell {{
                display: none !important;
            }}

            .wc-avatar-grid-mobile-shell {{
                display: block !important;
            }}

            div[data-testid="stPopoverBody"] [data-testid="column"],
            div[data-testid="stPopoverContent"] [data-testid="column"] {{
                padding-left: 0 !important;
                padding-right: 0 !important;
            }}
        }}

        @media (max-width: 390px) {{
            div[data-testid="stPopoverBody"],
            div[data-testid="stPopoverContent"] {{
                top: 78px !important;
                width: min(340px, calc(100vw - 28px)) !important;
                max-width: 340px !important;
                max-height: 62vh !important;
                padding: 14px 12px !important;
            }}
        }}
        """
    ):
        with st.popover("Đổi avatar", use_container_width=False):
            st.markdown(
                """
                <div style="
                    font-weight: 950;
                    font-size: 17px;
                    color: #07111F;
                    margin-bottom: 4px;
                ">
                    Chọn avatar
                </div>
                <div style="
                    color: #64748B;
                    font-size: 13px;
                    margin-bottom: 14px;
                    line-height: 1.4;
                ">
                    Chọn ảnh đại diện của bạn để hiển thị.
                </div>
                """,
                unsafe_allow_html=True
            )

            with stylable_container(
                key="avatar_grid_desktop_shell",
                css_styles="""
                {
                    display: block;
                }

                @media (max-width: 768px) {
                    {
                        display: none !important;
                    }
                }
                """
            ):
                st.markdown(
                    '<div class="wc-avatar-grid-desktop-shell">',
                    unsafe_allow_html=True
                )
                render_avatar_grid(avatars_per_row=4, key_prefix="desktop")
                st.markdown("</div>", unsafe_allow_html=True)

            with stylable_container(
                key="avatar_grid_mobile_shell",
                css_styles="""
                {
                    display: none;
                }

                @media (max-width: 768px) {
                    {
                        display: block !important;
                    }

                    div[data-testid="stHorizontalBlock"] {
                        display: grid !important;
                        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                        gap: 10px !important;
                        align-items: stretch !important;
                        width: 100% !important;
                    }

                    div[data-testid="column"] {
                        width: 100% !important;
                        min-width: 0 !important;
                        flex: unset !important;
                        padding-left: 0 !important;
                        padding-right: 0 !important;
                    }

                    div[data-testid="stButton"] {
                        width: 100% !important;
                    }
                }
                """
            ):
                st.markdown(
                    '<div class="wc-avatar-grid-mobile-shell">',
                    unsafe_allow_html=True
                )
                render_avatar_grid(avatars_per_row=2, key_prefix="mobile")
                st.markdown("</div>", unsafe_allow_html=True)
# ============================================================
# 3. BASIC UTILITIES
# ============================================================

@st.cache_resource
def get_engine() -> Engine:
    """
    Tạo kết nối Supabase/PostgreSQL.

    Fix loading lâu:
    - connect_timeout: không để app chờ kết nối vô hạn.
    - statement_timeout: không để query/DDL bị treo quá lâu.
    - lock_timeout: tránh kẹt nếu database đang bị lock.
    """
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_timeout=15,
        pool_size=3,
        max_overflow=5,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=20000 -c lock_timeout=5000"
        }
    )

    return engine


def read_sql(query: str, params: dict | None = None) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql_query(
            text(query),
            conn,
            params=params or {}
        )


def fetch_one(query: str, params: dict | None = None):
    with get_engine().connect() as conn:
        row = conn.execute(
            text(query),
            params or {}
        ).mappings().fetchone()

    if row is None:
        return None

    return dict(row)


def execute_sql(query: str, params: dict | None = None):
    with get_engine().begin() as conn:
        conn.execute(
            text(query),
            params or {}
        )


def execute_many(query: str, rows: list[dict]):
    if not rows:
        return

    with get_engine().begin() as conn:
        conn.execute(
            text(query),
            rows
        )


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


def today_vietnam_date():
    return pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").date()


def tomorrow_vietnam_date():
    return today_vietnam_date() + timedelta(days=1)


def format_filter_date(date_value):
    today = today_vietnam_date()
    tomorrow = tomorrow_vietnam_date()

    if date_value == today:
        return "Hôm nay"

    if date_value == tomorrow:
        return "Ngày mai"

    return date_value.strftime("%d/%m/%Y")


def to_bool(value) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    if pd.isna(value):
        return False

    if isinstance(value, (int, float)):
        return value == 1

    value_str = str(value).strip().lower()

    return value_str in ["true", "1", "yes", "y"]


def to_optional_int(value):
    if value is None:
        return None

    if pd.isna(value):
        return None

    return int(value)


def parse_utc_datetime(value):
    return pd.to_datetime(value, utc=True, errors="coerce")


def can_edit_prediction(kickoff_time_utc) -> bool:
    kickoff = parse_utc_datetime(kickoff_time_utc)

    if pd.isna(kickoff):
        return False

    now = pd.Timestamp.now(tz="UTC")

    return now < kickoff

def is_match_locked_for_star(kickoff_time_utc, is_finished=False) -> bool:
    """
    Một sao chỉ được tính là đã dùng thật khi trận đã khóa dự đoán:
    - Đã có kết quả, hoặc
    - Đã qua giờ kickoff.
    """
    if to_bool(is_finished):
        return True

    kickoff = parse_utc_datetime(kickoff_time_utc)

    if pd.isna(kickoff):
        return True

    now = pd.Timestamp.now(tz="UTC")

    return now >= kickoff


def is_match_open_for_star_transfer(kickoff_time_utc, is_finished=False) -> bool:
    """
    Trận còn mở dự đoán thì sao trên trận đó chỉ là giữ tạm,
    có thể chuyển sang trận khác.
    """
    if to_bool(is_finished):
        return False

    kickoff = parse_utc_datetime(kickoff_time_utc)

    if pd.isna(kickoff):
        return False

    now = pd.Timestamp.now(tz="UTC")

    return now < kickoff

def is_unknown_team(team_name) -> bool:
    if team_name is None or pd.isna(team_name):
        return True

    text = str(team_name).lower()

    unknown_keywords = [
        "tbd",
        "to be decided",
        "winner",
        "runner-up",
        "runner up",
        "2nd group",
        "3rd group",
        "1st group"
    ]

    return any(keyword in text for keyword in unknown_keywords)


def get_outcome(home_score, away_score):
    if home_score > away_score:
        return "HOME_WIN"

    if home_score < away_score:
        return "AWAY_WIN"

    return "DRAW"


def calculate_score_points(pred_home, pred_away, actual_home, actual_away) -> int:
    if pred_home is None or pred_away is None:
        return 0

    if actual_home is None or actual_away is None:
        return 0

    pred_home = int(pred_home)
    pred_away = int(pred_away)
    actual_home = int(actual_home)
    actual_away = int(actual_away)

    if pred_home == actual_home and pred_away == actual_away:
        return 3

    if get_outcome(pred_home, pred_away) == get_outcome(actual_home, actual_away):
        return 1

    return 0


def calculate_total_points(row) -> int:
    pred_home = to_optional_int(row.get("predicted_home_score"))
    pred_away = to_optional_int(row.get("predicted_away_score"))

    actual_home = to_optional_int(row.get("home_score_for_prediction"))
    actual_away = to_optional_int(row.get("away_score_for_prediction"))

    points = calculate_score_points(
        pred_home,
        pred_away,
        actual_home,
        actual_away
    )

    is_knockout = to_bool(row.get("is_knockout"))

    if is_knockout:
        predicted_winner_team_id = to_optional_int(row.get("predicted_winner_team_id"))
        actual_winner_team_id = to_optional_int(row.get("winner_team_id"))

        if (
            predicted_winner_team_id is not None
            and actual_winner_team_id is not None
            and predicted_winner_team_id == actual_winner_team_id
        ):
            points += 1

    return points

def normalize_star_type(star_type) -> str:
    if star_type is None:
        return STAR_TYPE_NONE

    if pd.isna(star_type):
        return STAR_TYPE_NONE

    star_type = str(star_type).strip().lower()

    if star_type not in STAR_CONFIG:
        return STAR_TYPE_NONE

    return star_type


def get_star_multiplier(star_type) -> int:
    star_type = normalize_star_type(star_type)
    return int(STAR_CONFIG[star_type]["multiplier"])


def calculate_points_with_star(base_points: int, star_type: str) -> dict:
    base_points = int(base_points or 0)
    multiplier = get_star_multiplier(star_type)

    final_points = base_points * multiplier
    bonus_points = final_points - base_points

    return {
        "base_points": base_points,
        "star_bonus_points": bonus_points,
        "points": final_points
    }


def format_star_short(star_type) -> str:
    star_type = normalize_star_type(star_type)
    return STAR_CONFIG[star_type]["short_label"]


def get_user_star_usage(user_id: int, exclude_match_id: int | None = None) -> dict:
    """
    Dùng cho UI.

    Logic mới:
    - locked_used: chỉ tính sao ở các trận đã khóa dự đoán.
    - reserved_used: sao đang giữ tạm ở các trận chưa diễn ra.
    - left: số sao còn lại theo kho chính thức, chỉ trừ locked_used.
    - free_left: số sao còn trống để gắn ngay, đã trừ cả reserved_used.
    """
    predictions = load_predictions()
    matches = load_matches()

    if predictions.empty or matches.empty:
        hope_locked_used = 0
        super_locked_used = 0
        hope_reserved_used = 0
        super_reserved_used = 0
    else:
        user_predictions = predictions[
            predictions["user_id"].astype(int) == int(user_id)
        ].copy()

        if exclude_match_id is not None and not user_predictions.empty:
            user_predictions = user_predictions[
                user_predictions["match_id"].astype(int) != int(exclude_match_id)
            ]

        if user_predictions.empty:
            hope_locked_used = 0
            super_locked_used = 0
            hope_reserved_used = 0
            super_reserved_used = 0
        else:
            match_cols = [
                "match_id",
                "kickoff_time_utc",
                "is_finished"
            ]

            match_info = matches[match_cols].copy()

            df = user_predictions.merge(
                match_info,
                on="match_id",
                how="left"
            )

            df["star_type"] = df["star_type"].apply(normalize_star_type)

            df["is_star_locked"] = df.apply(
                lambda row: is_match_locked_for_star(
                    row.get("kickoff_time_utc"),
                    row.get("is_finished")
                ),
                axis=1
            )

            df["is_star_reserved"] = df.apply(
                lambda row: is_match_open_for_star_transfer(
                    row.get("kickoff_time_utc"),
                    row.get("is_finished")
                ),
                axis=1
            )

            hope_locked_used = int(
                ((df["star_type"] == STAR_TYPE_HOPE) & df["is_star_locked"]).sum()
            )

            super_locked_used = int(
                ((df["star_type"] == STAR_TYPE_SUPER) & df["is_star_locked"]).sum()
            )

            hope_reserved_used = int(
                ((df["star_type"] == STAR_TYPE_HOPE) & df["is_star_reserved"]).sum()
            )

            super_reserved_used = int(
                ((df["star_type"] == STAR_TYPE_SUPER) & df["is_star_reserved"]).sum()
            )

    hope_left = max(0, HOPE_STARS_PER_USER - hope_locked_used)
    super_left = max(0, SUPER_STARS_PER_USER - super_locked_used)

    hope_free_left = max(0, hope_left - hope_reserved_used)
    super_free_left = max(0, super_left - super_reserved_used)

    return {
        "hope_used": hope_locked_used,
        "super_used": super_locked_used,

        "hope_locked_used": hope_locked_used,
        "super_locked_used": super_locked_used,

        "hope_reserved_used": hope_reserved_used,
        "super_reserved_used": super_reserved_used,

        "hope_left": hope_left,
        "super_left": super_left,

        "hope_free_left": hope_free_left,
        "super_free_left": super_free_left
    }

def validate_star_quota(user_id: int, match_id: int, star_type: str):
    star_type = normalize_star_type(star_type)

    usage = get_user_star_usage_from_db(
        user_id=user_id,
        exclude_match_id=match_id
    )

    if star_type == STAR_TYPE_HOPE and usage["hope_left"] <= 0:
        raise ValueError("Bạn đã dùng hết Ngôi sao hy vọng.")

    if star_type == STAR_TYPE_SUPER and usage["super_left"] <= 0:
        raise ValueError("Bạn đã dùng hết Siêu sao.")


def get_available_star_options(
    user_id: int,
    match_id: int,
    current_star_type: str,
    usage: dict | None = None
) -> list[str]:
    """
    Luôn hiển thị đủ các option bổ trợ.
    Option hết thật sẽ được xử lý bằng label xám + validate khi lưu.
    """
    return [
        STAR_TYPE_NONE,
        STAR_TYPE_HOPE,
        STAR_TYPE_SUPER
    ]


def format_star_option_label(
    star_type: str,
    current_star_type: str,
    usage: dict
) -> str:
    """
    Format label cho option bổ trợ.

    Quy ước hiển thị:
    - Kho còn lại = tổng sao - sao đã khóa/mất.
      Sao đang giữ tạm ở các trận chưa khóa vẫn nằm trong kho này.
    - Đang dùng = số sao đang giữ tạm ở các trận chưa khóa.
    - free_left vẫn chỉ dùng ngầm cho logic chuyển sao, không đưa lên label.
    """
    star_type = normalize_star_type(star_type)
    current_star_type = normalize_star_type(current_star_type)

    if star_type == STAR_TYPE_NONE:
        return "Không dùng sao"

    if star_type == STAR_TYPE_HOPE:
        hope_label = STAR_CONFIG[STAR_TYPE_HOPE]["label"]

        hope_left = int(usage.get("hope_left", 0))
        hope_using = int(usage.get("hope_reserved_used", 0))

        if hope_left <= 0 and current_star_type != STAR_TYPE_HOPE:
            return f"{hope_label} (đã hết)"

        return (
            f"{hope_label} "
            f"(Kho còn lại: {hope_left}/{HOPE_STARS_PER_USER}; "
            f"Đang dùng: {hope_using}/{HOPE_STARS_PER_USER})"
        )

    if star_type == STAR_TYPE_SUPER:
        super_label = STAR_CONFIG[STAR_TYPE_SUPER]["label"]

        super_left = int(usage.get("super_left", 0))
        super_using = int(usage.get("super_reserved_used", 0))

        if super_left <= 0 and current_star_type != STAR_TYPE_SUPER:
            return f"{super_label} (đã hết)"

        return (
            f"{super_label} "
            f"(Kho còn lại: {super_left}/{SUPER_STARS_PER_USER}; "
            f"Đang dùng: {super_using}/{SUPER_STARS_PER_USER})"
        )

    return STAR_CONFIG[star_type]["label"]

def get_prediction_result_info(
    pred_home,
    pred_away,
    actual_home,
    actual_away,
    is_finished,
    is_knockout=False,
    predicted_winner_team_id=None,
    actual_winner_team_id=None
):
    """
    Trả về thông tin hiển thị kết quả dự đoán:
    - Đúng hoàn toàn tỉ số
    - Đúng kết quả
    - Đúng đội thắng chung cuộc
    - Sai

    Logic:
    - Đúng hoàn toàn tỉ số: dự đoán đúng chính xác tỉ số.
    - Đúng kết quả: không đúng tỉ số, nhưng đúng kết quả thắng/hòa/thua.
    - Đúng đội thắng chung cuộc: trận knockout, sai outcome tỉ số,
      nhưng chọn đúng đội thắng chung cuộc.
    - Sai: không đúng các trường hợp trên.
    """
    if not is_finished:
        return None

    pred_home = to_optional_int(pred_home)
    pred_away = to_optional_int(pred_away)
    actual_home = to_optional_int(actual_home)
    actual_away = to_optional_int(actual_away)

    if (
        pred_home is None
        or pred_away is None
        or actual_home is None
        or actual_away is None
    ):
        return None

    predicted_winner_team_id = to_optional_int(predicted_winner_team_id)
    actual_winner_team_id = to_optional_int(actual_winner_team_id)

    if pred_home == actual_home and pred_away == actual_away:
        return {
            "label": "Đúng hoàn toàn tỉ số",
            "text_color": "#166534",
            "bg_color": "#DCFCE7",
            "border_color": "#86EFAC"
        }

    if get_outcome(pred_home, pred_away) == get_outcome(actual_home, actual_away):
        return {
            "label": "Đúng kết quả",
            "text_color": "#0369A1",
            "bg_color": "#E0F2FE",
            "border_color": "#7DD3FC"
        }

    correct_knockout_winner = (
        to_bool(is_knockout)
        and predicted_winner_team_id is not None
        and actual_winner_team_id is not None
        and predicted_winner_team_id == actual_winner_team_id
    )

    if correct_knockout_winner:
        return {
            "label": "Đúng đội thắng chung cuộc",
            "text_color": "#C2410C",
            "bg_color": "#FFEDD5",
            "border_color": "#FDBA74"
        }

    return {
        "label": "Sai",
        "text_color": "#B91C1C",
        "bg_color": "#FEE2E2",
        "border_color": "#FCA5A5"
    }


def render_prediction_result_line(result_info):
    if result_info is None:
        return

    st.markdown(
        f"""
        <div style="
            margin-top: 8px;
            margin-bottom: 8px;
            font-size: 15px;
            color: #07111F;
        ">
            Kết quả dự đoán:
            <span style="
                display: inline-block;
                margin-left: 6px;
                padding: 5px 11px;
                border-radius: 999px;
                background: {result_info["bg_color"]};
                color: {result_info["text_color"]};
                border: 1px solid {result_info["border_color"]};
                font-weight: 850;
                font-size: 14px;
            ">
                {result_info["label"]}
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

def calculate_display_points_for_prediction(existing, match_row) -> dict | None:
    """
    Tính điểm hiển thị ngay tại card trận đấu.

    Ưu tiên tính live từ:
    - Dự đoán của user
    - Kết quả thật của trận
    - Bổ trợ sao đang dùng

    Mục tiêu:
    - UI luôn hiện điểm thực tế đã nhân sao.
    - Không phụ thuộc hoàn toàn vào points đang cache/lưu trong DB.
    - Không ghi database, không ảnh hưởng BXH/chấm điểm chính thức.
    """
    if existing is None:
        return None

    is_finished = to_bool(match_row.get("is_finished"))

    actual_home = to_optional_int(match_row.get("home_score_for_prediction"))
    actual_away = to_optional_int(match_row.get("away_score_for_prediction"))

    if not is_finished or actual_home is None or actual_away is None:
        db_points = to_optional_int(existing.get("points"))

        if db_points is None:
            return None

        return {
            "base_points": to_optional_int(existing.get("base_points")),
            "star_bonus_points": to_optional_int(existing.get("star_bonus_points")),
            "points": db_points
        }

    scoring_row = {
        "predicted_home_score": existing.get("predicted_home_score"),
        "predicted_away_score": existing.get("predicted_away_score"),
        "predicted_winner_team_id": existing.get("predicted_winner_team_id"),

        "home_score_for_prediction": match_row.get("home_score_for_prediction"),
        "away_score_for_prediction": match_row.get("away_score_for_prediction"),

        "is_knockout": match_row.get("is_knockout"),
        "winner_team_id": match_row.get("winner_team_id")
    }

    base_points = calculate_total_points(scoring_row)

    return calculate_points_with_star(
        base_points=base_points,
        star_type=existing.get("star_type")
    )

def render_prediction_result_and_score_row(result_info, existing, match_row=None):
    display_point_info = None

    if match_row is not None:
        display_point_info = calculate_display_points_for_prediction(
            existing=existing,
            match_row=match_row
        )

    if display_point_info is None and existing is not None:
        db_points = to_optional_int(existing.get("points"))

        if db_points is not None:
            display_point_info = {
                "base_points": to_optional_int(existing.get("base_points")),
                "star_bonus_points": to_optional_int(existing.get("star_bonus_points")),
                "points": db_points
            }

    has_result = result_info is not None
    has_points = (
        display_point_info is not None
        and display_point_info.get("points") is not None
    )

    if not has_result and not has_points:
        return

    result_html = ""
    score_html = ""

    if has_result:
        result_label = html.escape(str(result_info["label"]))

        result_html = (
            '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">'
            '<span style="color:#07111F;font-size:15px;font-weight:650;">'
            'Kết quả dự đoán:'
            '</span>'
            '<span style="'
            'display:inline-block;'
            'padding:7px 13px;'
            'border-radius:999px;'
            f'background:{result_info["bg_color"]};'
            f'color:{result_info["text_color"]};'
            f'border:1px solid {result_info["border_color"]};'
            'font-weight:850;'
            'font-size:14px;'
            '">'
            f'{result_label}'
            '</span>'
            '</div>'
        )

    if has_points:
        final_points = int(round(float(display_point_info.get("points") or 0)))
        base_points = int(round(float(display_point_info.get("base_points") or 0)))
        star_bonus_points = int(round(float(display_point_info.get("star_bonus_points") or 0)))

        if has_result:
            score_bg = result_info["bg_color"]
            score_text = result_info["text_color"]
            score_border = result_info["border_color"]
        else:
            score_bg = "#FFF7ED"
            score_text = "#9A3412"
            score_border = "rgba(251,146,60,0.45)"

        score_title = f"Điểm gốc: {base_points} | Thưởng sao: {star_bonus_points} | Tổng điểm: {final_points}"

        score_html = (
            '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">'
            '<span style="color:#07111F;font-size:15px;font-weight:650;">'
            'Điểm:'
            '</span>'
            '<span title="'
            f'{html.escape(score_title)}'
            '" style="'
            'display:inline-block;'
            'min-width:34px;'
            'text-align:center;'
            'padding:7px 13px;'
            'border-radius:999px;'
            f'background:{score_bg};'
            f'color:{score_text};'
            f'border:1px solid {score_border};'
            'font-weight:950;'
            'font-size:14px;'
            '">'
            f'{final_points}'
            '</span>'
            '</div>'
        )

    st.markdown(
        (
            '<div style="'
            'display:flex;'
            'align-items:center;'
            'gap:22px;'
            'flex-wrap:wrap;'
            'margin-top:18px;'
            'margin-bottom:6px;'
            '">'
            f'{result_html}'
            f'{score_html}'
            '</div>'
        ),
        unsafe_allow_html=True
    )

def hash_password(password: str, salt: str | None = None):
    if salt is None:
        salt = os.urandom(16).hex()

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        150_000
    ).hex()

    return salt, password_hash


def verify_password(password: str, salt: str, stored_hash: str) -> bool:
    _, password_hash = hash_password(password, salt)
    return hmac.compare_digest(password_hash, stored_hash)


def clear_filter_state():
    for key in [
        "filter_date",
        "filter_status",
        "filter_prediction_status",
        "pending_prediction"
    ]:
        if key in st.session_state:
            del st.session_state[key]


def get_match_status_info(row):
    is_finished = to_bool(row.get("is_finished"))
    editable = can_edit_prediction(row.get("kickoff_time_utc"))

    home_name = row.get("home_team_name")
    away_name = row.get("away_team_name")

    if is_unknown_team(home_name) or is_unknown_team(away_name):
        return {
            "status_key": "unknown",
            "label": "Chưa xác định đội",
            "border_color": "#9CA3AF",
            "background": "linear-gradient(135deg, rgba(248,250,252,0.96), rgba(241,245,249,0.90))",
            "badge_bg": "#E5E7EB",
            "badge_text": "#374151"
        }

    if is_finished:
        return {
            "status_key": "finished",
            "label": "Đã có kết quả",
            "border_color": "#16A34A",
            "background": "linear-gradient(135deg, rgba(240,253,244,0.98), rgba(255,255,255,0.92))",
            "badge_bg": "#DCFCE7",
            "badge_text": "#166534"
        }

    if editable:
        return {
            "status_key": "open",
            "label": "Đang mở dự đoán",
            "border_color": "#2563EB",
            "background": "linear-gradient(135deg, rgba(239,246,255,0.98), rgba(255,255,255,0.94))",
            "badge_bg": "#DBEAFE",
            "badge_text": "#1D4ED8"
        }

    return {
        "status_key": "locked",
        "label": "Đã khóa dự đoán",
        "border_color": "#F59E0B",
        "background": "linear-gradient(135deg, rgba(255,251,235,0.98), rgba(255,255,255,0.94))",
        "badge_bg": "#FEF3C7",
        "badge_text": "#92400E"
    }


def get_match_card_css(status_info):
    return f"""
    {{
        border: 2px solid {status_info["border_color"]};
        border-radius: 20px;
        padding: 22px 22px 16px 22px;
        margin-bottom: 22px;
        background: {status_info["background"]};
        box-shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
    }}
    """


def render_status_badge(status_info):
    st.markdown(
        f"""
        <div style="
            display:inline-block;
            padding:7px 13px;
            border-radius:999px;
            background:{status_info["badge_bg"]};
            color:{status_info["badge_text"]};
            font-weight:850;
            font-size:13px;
            margin-bottom:8px;
            border:1px solid rgba(15,23,42,0.06);
        ">
            {status_info["label"]}
        </div>
        """,
        unsafe_allow_html=True
    )


def render_match_status_box(status_info):
    """
    Thay cho st.metric khi hiển thị trạng thái dạng text.
    st.metric phù hợp với số, nhưng với text dài như "Đang mở dự đoán" thì font quá lớn và bị cắt.
    """
    st.markdown(
        f"""
        <div style="
            background: rgba(255, 255, 255, 0.86);
            border: 1px solid rgba(15, 23, 42, 0.08);
            border-left: 5px solid {status_info["border_color"]};
            border-radius: 16px;
            padding: 13px 15px;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
            min-width: 180px;
        ">
            <div style="
                color: #64748B;
                font-size: 12px;
                font-weight: 800;
                margin-bottom: 5px;
            ">
                Trạng thái
            </div>
            <div style="
                color: {status_info["badge_text"]};
                font-size: 16px;
                font-weight: 900;
                line-height: 1.25;
                white-space: normal;
                overflow: visible;
                text-overflow: unset;
            ">
                {status_info["label"]}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# 4. DATABASE INIT
# ============================================================

def check_base_database():
    try:
        tables = read_sql(
            """
            SELECT table_name AS name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            """
        )
    except Exception as e:
        st.error("Không kết nối được Supabase database.")
        st.exception(e)
        st.stop()

    table_names = set(tables["name"].tolist())

    if "matches" not in table_names:
        st.error("Supabase database chưa có bảng `matches`. Hãy kiểm tra lại bước import dữ liệu.")
        st.stop()

def check_required_app_tables():
    """
    Kiểm tra các bảng app cần có khi không chạy migration ở startup.

    Nếu thiếu bảng thì báo lỗi rõ ràng thay vì loading mãi.
    """
    try:
        tables = read_sql(
            """
            SELECT table_name AS name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            """
        )
    except Exception as e:
        st.error("Không kiểm tra được schema Supabase.")
        st.exception(e)
        st.stop()

    table_names = set(tables["name"].tolist())

    required_tables = {
        "matches",
        "users",
        "predictions",
        "prediction_history",
        "login_sessions"
    }

    missing_tables = sorted(required_tables - table_names)

    if missing_tables:
        st.error(
            "Database đang thiếu bảng bắt buộc: "
            + ", ".join(missing_tables)
            + ". Hãy bật RUN_DB_MIGRATIONS=true một lần để khởi tạo schema."
        )
        st.stop()

def init_app_tables():
    execute_sql(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'player',
            created_at TEXT NOT NULL
        )
        """
    )

    execute_sql(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS avatar_key TEXT DEFAULT 'avatar_01.png'
        """
    )

    execute_sql(
        """
        UPDATE users
        SET avatar_key = :default_avatar_key
        WHERE avatar_key IS NULL
           OR TRIM(avatar_key) = ''
        """,
        {
            "default_avatar_key": DEFAULT_AVATAR_KEY
        }
    )

    execute_sql(
        """
        CREATE TABLE IF NOT EXISTS predictions (
            prediction_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            match_id INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            predicted_home_score INTEGER NOT NULL,
            predicted_away_score INTEGER NOT NULL,
            predicted_winner_team_id INTEGER,
            star_type TEXT NOT NULL DEFAULT 'none',
            base_points INTEGER,
            star_bonus_points INTEGER,
            points INTEGER,
            submitted_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, match_id)
        )
        """
    )

    execute_sql(
        """
        CREATE TABLE IF NOT EXISTS prediction_history (
            history_id SERIAL PRIMARY KEY,
            prediction_id INTEGER NOT NULL REFERENCES predictions(prediction_id) ON DELETE CASCADE,
            old_home_score INTEGER,
            old_away_score INTEGER,
            old_winner_team_id INTEGER,
            new_home_score INTEGER NOT NULL,
            new_away_score INTEGER NOT NULL,
            new_winner_team_id INTEGER,
            changed_at TEXT NOT NULL
        )
        """
    )

    execute_sql(
    """
    ALTER TABLE predictions
    ADD COLUMN IF NOT EXISTS star_type TEXT DEFAULT 'none'
    """
    )
    
    execute_sql(
        """
        UPDATE predictions
        SET star_type = 'none'
        WHERE star_type IS NULL
        """
    )
    
    execute_sql(
        """
        ALTER TABLE predictions
        ALTER COLUMN star_type SET NOT NULL
        """
    )
    
    execute_sql(
        """
        ALTER TABLE predictions
        ADD COLUMN IF NOT EXISTS base_points INTEGER
        """
    )
    
    execute_sql(
        """
        ALTER TABLE predictions
        ADD COLUMN IF NOT EXISTS star_bonus_points INTEGER
        """
    )
    
    execute_sql(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'predictions_star_type_check'
            ) THEN
                ALTER TABLE predictions
                ADD CONSTRAINT predictions_star_type_check
                CHECK (star_type IN ('none', 'hope', 'super'));
            END IF;
        END $$;
        """
    )

    execute_sql(
        """
        CREATE TABLE IF NOT EXISTS login_sessions (
            session_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL
        )
        """
    )

    execute_sql(
        """
        DELETE FROM login_sessions
        WHERE expires_at <= NOW()
        """
    )
    # Tạo unique index cho tên hiển thị nếu dữ liệu hiện tại chưa bị trùng.
    # Index này giúp chặn các biến thể như "Hoang", " hoang ", "HOANG".
    try:
        duplicate_display_names = read_sql(
            """
            SELECT LOWER(TRIM(display_name)) AS normalized_display_name,
                   COUNT(*) AS n
            FROM users
            GROUP BY LOWER(TRIM(display_name))
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )

        if duplicate_display_names.empty:
            execute_sql(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_display_name_unique_ci
                ON users (LOWER(TRIM(display_name)))
                """
            )

    except Exception:
        # Không chặn app khởi động nếu database đã có dữ liệu trùng hoặc index lỗi.
        # create_user() vẫn có kiểm tra app-level để ngăn tên hiển thị trùng về sau.
        pass


@st.cache_resource
def initialize_app_once():
    """
    Khởi động app một lần cho mỗi app process.

    Fix loading lâu:
    - Luôn kiểm tra bảng matches.
    - Chỉ chạy migration khi RUN_DB_MIGRATIONS=true.
    - App chính nên để RUN_DB_MIGRATIONS=false sau khi schema đã ổn định.
    """
    check_base_database()

    if RUN_DB_MIGRATIONS:
        init_app_tables()
    else:
        check_required_app_tables()

    return True


def count_users() -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM users
        """
    )

    return int(row["n"])

def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_login_session(user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    token_hash = hash_session_token(token)

    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)

    execute_sql(
        """
        INSERT INTO login_sessions (
            user_id,
            token_hash,
            expires_at
        )
        VALUES (
            :user_id,
            :token_hash,
            :expires_at
        )
        """,
        {
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at
        }
    )

    return token

def set_login_cookie_and_reload(token: str):
    """
    Ghi session token vào browser cookie rồi reload lại app.

    Lý do:
    - st.session_state sẽ mất khi F5.
    - Cookie phải được browser ghi chắc chắn trước khi app rerun/reload.
    - Không đổi logic login/session, chỉ đảm bảo cookie được persist đúng.
    """
    max_age_seconds = SESSION_DAYS * 24 * 60 * 60

    safe_cookie_name = html.escape(COOKIE_NAME, quote=True)
    safe_token = html.escape(str(token), quote=True)

    components.html(
        f"""
        <script>
        (function() {{
            document.cookie = "{safe_cookie_name}={safe_token}; path=/; max-age={max_age_seconds}; SameSite=Lax";
            setTimeout(function() {{
                window.parent.location.reload();
            }}, 120);
        }})();
        </script>
        """,
        height=0
    )

    st.stop()

def get_user_by_session_token(token: str):
    if not token:
        return None

    token_hash = hash_session_token(token)

    return fetch_one(
        """
        SELECT
            u.user_id,
            u.username,
            u.display_name,
            u.role,
            u.created_at,
            COALESCE(u.avatar_key, :default_avatar_key) AS avatar_key
        FROM login_sessions s
        JOIN users u
          ON s.user_id = u.user_id
        WHERE s.token_hash = :token_hash
          AND s.expires_at > NOW()
        """,
        {
            "token_hash": token_hash,
            "default_avatar_key": DEFAULT_AVATAR_KEY
        }
    )


def delete_login_session(token: str):
    if not token:
        return

    execute_sql(
        """
        DELETE FROM login_sessions
        WHERE token_hash = :token_hash
        """,
        {
            "token_hash": hash_session_token(token)
        }
    )


def restore_user_from_cookie() -> bool:
    """
    Khôi phục user từ cookie.

    Bản an toàn:
    - Nếu cookie component lỗi, không làm app kẹt.
    - Nếu token lỗi/hết hạn, xóa cookie và quay về trang đăng nhập.
    """
    if "user" in st.session_state:
        return True

    token = None

    try:
        token = cookie_controller.get(COOKIE_NAME)
    except Exception:
        token = None

    if not token:
        try:
            cookies = cookie_controller.getAll()

            if isinstance(cookies, dict):
                token = cookies.get(COOKIE_NAME)

        except Exception:
            token = None

    if not token:
        return False

    token = str(token).strip()

    if not token:
        return False

    try:
        user = get_user_by_session_token(token)
    except Exception:
        return False

    if user is None:
        try:
            cookie_controller.remove(COOKIE_NAME)
        except Exception:
            pass

        return False

    st.session_state["user"] = user
    return True


# ============================================================
# 5. AUTH FUNCTIONS
# ============================================================

def create_user(username: str, display_name: str, password: str):
    username = username.strip().lower()
    display_name = display_name.strip()

    if not username:
        raise ValueError("Username không được để trống.")

    if not display_name:
        raise ValueError("Tên hiển thị không được để trống.")

    if len(password) < 8:
        raise ValueError("Mật khẩu nên có ít nhất 8 ký tự.")

    existing_username = fetch_one(
        """
        SELECT user_id
        FROM users
        WHERE username = :username
        """,
        {
            "username": username
        }
    )

    if existing_username is not None:
        raise ValueError("Username này đã tồn tại.")

    existing_display_name = fetch_one(
        """
        SELECT user_id
        FROM users
        WHERE LOWER(TRIM(display_name)) = LOWER(TRIM(:display_name))
        """,
        {
            "display_name": display_name
        }
    )

    if existing_display_name is not None:
        raise ValueError("Tên hiển thị này đã được sử dụng. Hãy chọn tên khác.")

    salt, password_hash = hash_password(password)

    role = "admin" if count_users() == 0 else "player"

    try:
        execute_sql(
            """
            INSERT INTO users (
                username,
                display_name,
                password_salt,
                password_hash,
                role,
                created_at
            )
            VALUES (
                :username,
                :display_name,
                :password_salt,
                :password_hash,
                :role,
                :created_at
            )
            """,
            {
                "username": username,
                "display_name": display_name,
                "password_salt": salt,
                "password_hash": password_hash,
                "role": role,
                "created_at": now_utc_iso()
            }
        )

        clear_data_cache()

    except IntegrityError:
        raise ValueError("Username hoặc tên hiển thị đã tồn tại.")

    return role


def login_user(username: str, password: str):
    username = username.strip().lower()

    user = fetch_one(
        """
        SELECT *
        FROM users
        WHERE username = :username
        """,
        {
            "username": username
        }
    )

    if user is None:
        return None

    is_valid = verify_password(
        password=password,
        salt=user["password_salt"],
        stored_hash=user["password_hash"]
    )

    if not is_valid:
        return None

    return user


def logout_user():
    token = cookie_controller.get(COOKIE_NAME)

    if token:
        delete_login_session(token)
        cookie_controller.remove(COOKIE_NAME)

    for key in list(st.session_state.keys()):
        del st.session_state[key]

    st.rerun()


# ============================================================
# 6. DATA LOADING
# ============================================================

@st.cache_data(ttl=30, show_spinner=False)
def load_matches() -> pd.DataFrame:
    df = read_sql(
        """
        SELECT *
        FROM matches
        ORDER BY kickoff_time_utc
        """
    )

    if df.empty:
        return df

    df["kickoff_time_utc_dt"] = pd.to_datetime(
        df["kickoff_time_utc"],
        utc=True,
        errors="coerce"
    )

    if "kickoff_date_vietnam" in df.columns:
        df["kickoff_date_filter"] = pd.to_datetime(
            df["kickoff_date_vietnam"],
            errors="coerce"
        ).dt.date
    else:
        df["kickoff_date_filter"] = df["kickoff_time_utc_dt"].dt.tz_convert(
            "Asia/Ho_Chi_Minh"
        ).dt.date

    return df


@st.cache_data(ttl=30, show_spinner=False)
def load_users() -> pd.DataFrame:
    return read_sql(
        """
        SELECT
            user_id,
            username,
            display_name,
            role,
            created_at,
            COALESCE(avatar_key, :default_avatar_key) AS avatar_key
        FROM users
        """,
        {
            "default_avatar_key": DEFAULT_AVATAR_KEY
        }
    )


@st.cache_data(ttl=10, show_spinner=False)
def load_predictions() -> pd.DataFrame:
    return read_sql(
        """
        SELECT *
        FROM predictions
        """
    )


@st.cache_data(ttl=300, show_spinner=False)
def load_goal_scorers_for_match(match_id: int) -> pd.DataFrame:
    """
    Chỉ load danh sách cầu thủ ghi bàn của đúng 1 trận.
    Không query toàn bộ bảng match_goals nữa.
    """
    try:
        return read_sql(
            """
            SELECT
                goal_key,
                match_id,
                team_id,
                team_name,
                team_side,
                player_name,
                minute,
                is_penalty,
                is_own_goal
            FROM match_goals
            WHERE match_id = :match_id
            ORDER BY team_side, goal_key
            """,
            {
                "match_id": int(match_id)
            }
        )

    except Exception:
        return pd.DataFrame()


def format_goal_text(row) -> str:
    """
    Format 1 dòng cầu thủ ghi bàn để hiển thị UI.
    """
    from html import escape

    player_name = escape(str(row.get("player_name", "")).strip())
    minute = row.get("minute")

    parts = [player_name]

    if pd.notna(minute) and str(minute).strip():
        parts.append(escape(str(minute).strip()))

    tags = []

    if to_bool(row.get("is_own_goal")):
        tags.append("OG")

    if to_bool(row.get("is_penalty")):
        tags.append("pen")

    if tags:
        parts.append(f"({', '.join(tags)})")

    return " ".join(parts)


def toggle_goal_scorers(match_id: int):
    """
    Mỗi trận có trạng thái ẩn/hiện cầu thủ ghi bàn riêng.
    Bấm trận nào thì chỉ đổi trạng thái của trận đó,
    không ảnh hưởng các trận khác.
    """
    toggle_key = f"show_goal_scorers_{int(match_id)}"

    st.session_state[toggle_key] = not st.session_state.get(
        toggle_key,
        False
    )


def render_goal_scorers_for_match(match_id: int):
    """
    Hiển thị nút mở rộng/thu gọn danh sách cầu thủ ghi bàn.

    Logic giữ nguyên:
    - Mỗi card có trạng thái ẩn/hiện riêng.
    - Bấm mở/ẩn trận này không tự đóng các trận khác.
    - Chưa mở thì không query bảng match_goals.
    - Khi mở thì chỉ query cầu thủ ghi bàn của đúng trận đó.

    UI update:
    - Thêm class CSS cho box cầu thủ ghi bàn để mobile có thể kéo rộng sang phải.
    """
    from html import escape

    match_id = int(match_id)
    toggle_key = f"show_goal_scorers_{match_id}"

    is_open = st.session_state.get(toggle_key, False)

    button_label = (
        "Ẩn cầu thủ ghi bàn"
        if is_open
        else "⚽ Xem cầu thủ ghi bàn"
    )

    st.button(
        button_label,
        key=f"goal_scorers_button_{match_id}",
        type="secondary",
        on_click=toggle_goal_scorers,
        args=(match_id,)
    )

    if not is_open:
        return

    match_goals = load_goal_scorers_for_match(match_id)

    if match_goals.empty:
        st.caption("Chưa có dữ liệu cầu thủ ghi bàn cho trận này.")
        return

    home_goals = match_goals[match_goals["team_side"] == "home"]
    away_goals = match_goals[match_goals["team_side"] == "away"]

    goal_lines = []

    if not home_goals.empty:
        home_team = escape(
            str(home_goals.iloc[0]["team_name"]).strip(),
            quote=False
        )
        home_text = ", ".join(home_goals.apply(format_goal_text, axis=1))

        goal_lines.append(
            '<div class="wc-goal-scorer-line">'
            f'<span class="wc-goal-scorer-team">{home_team}:</span> '
            f'<span class="wc-goal-scorer-names">{home_text}</span>'
            '</div>'
        )

    if not away_goals.empty:
        away_team = escape(
            str(away_goals.iloc[0]["team_name"]).strip(),
            quote=False
        )
        away_text = ", ".join(away_goals.apply(format_goal_text, axis=1))

        goal_lines.append(
            '<div class="wc-goal-scorer-line">'
            f'<span class="wc-goal-scorer-team">{away_team}:</span> '
            f'<span class="wc-goal-scorer-names">{away_text}</span>'
            '</div>'
        )

    if not goal_lines:
        st.caption("Trận này chưa có dữ liệu cầu thủ ghi bàn.")
        return

    scorers_html = (
        '<div class="wc-goal-scorers-box" style="'
        'margin-top:8px;'
        'margin-bottom:18px;'
        'padding-left:12px;'
        'border-left:3px solid rgba(245,197,66,0.9);'
        'font-size:13px;'
        'line-height:1.55;'
        '">'
        '<div class="wc-goal-scorers-title" style="'
        'font-weight:900;'
        'color:#07111F;'
        'margin-bottom:4px;'
        'letter-spacing:0.01em;'
        '">'
        'Cầu thủ ghi bàn'
        '</div>'
        f'{"".join(goal_lines)}'
        '</div>'
    )

    st.markdown(
        scorers_html,
        unsafe_allow_html=True
    )

def clear_data_cache():
    """
    Xóa cache dữ liệu đọc từ Supabase sau khi có thao tác ghi dữ liệu.
    """
    load_matches.clear()
    load_users.clear()
    load_predictions.clear()

    try:
        build_leaderboard_df.clear()
    except NameError:
        pass

    try:
        load_goal_scorers_for_match.clear()
    except NameError:
        pass

def get_user_prediction_from_db(user_id: int, match_id: int):
    """
    Dùng cho thao tác ghi dữ liệu/save.
    Luôn đọc trực tiếp database để đảm bảo dữ liệu mới nhất.
    """
    return fetch_one(
        """
        SELECT *
        FROM predictions
        WHERE user_id = :user_id
          AND match_id = :match_id
        """,
        {
            "user_id": user_id,
            "match_id": match_id
        }
    )


def get_user_star_usage_from_db(user_id: int, exclude_match_id: int | None = None) -> dict:
    """
    Dùng cho validate khi lưu dự đoán.

    Logic mới:
    - Sao ở trận đã khóa mới tính là đã dùng thật.
    - Sao ở trận chưa diễn ra tính là đang giữ tạm.
    """
    query = """
        SELECT
            p.star_type,
            p.match_id,
            m.kickoff_time_utc,
            m.is_finished
        FROM predictions p
        JOIN matches m
          ON p.match_id = m.match_id
        WHERE p.user_id = :user_id
    """

    params = {
        "user_id": user_id
    }

    if exclude_match_id is not None:
        query += " AND p.match_id <> :exclude_match_id"
        params["exclude_match_id"] = exclude_match_id

    df = read_sql(query, params)

    if df.empty:
        hope_locked_used = 0
        super_locked_used = 0
        hope_reserved_used = 0
        super_reserved_used = 0
    else:
        df["star_type"] = df["star_type"].apply(normalize_star_type)

        df["is_star_locked"] = df.apply(
            lambda row: is_match_locked_for_star(
                row.get("kickoff_time_utc"),
                row.get("is_finished")
            ),
            axis=1
        )

        df["is_star_reserved"] = df.apply(
            lambda row: is_match_open_for_star_transfer(
                row.get("kickoff_time_utc"),
                row.get("is_finished")
            ),
            axis=1
        )

        hope_locked_used = int(
            ((df["star_type"] == STAR_TYPE_HOPE) & df["is_star_locked"]).sum()
        )

        super_locked_used = int(
            ((df["star_type"] == STAR_TYPE_SUPER) & df["is_star_locked"]).sum()
        )

        hope_reserved_used = int(
            ((df["star_type"] == STAR_TYPE_HOPE) & df["is_star_reserved"]).sum()
        )

        super_reserved_used = int(
            ((df["star_type"] == STAR_TYPE_SUPER) & df["is_star_reserved"]).sum()
        )

    hope_left = max(0, HOPE_STARS_PER_USER - hope_locked_used)
    super_left = max(0, SUPER_STARS_PER_USER - super_locked_used)

    hope_free_left = max(0, hope_left - hope_reserved_used)
    super_free_left = max(0, super_left - super_reserved_used)

    return {
        "hope_used": hope_locked_used,
        "super_used": super_locked_used,

        "hope_locked_used": hope_locked_used,
        "super_locked_used": super_locked_used,

        "hope_reserved_used": hope_reserved_used,
        "super_reserved_used": super_reserved_used,

        "hope_left": hope_left,
        "super_left": super_left,

        "hope_free_left": hope_free_left,
        "super_free_left": super_free_left
    }

def update_user_avatar(user_id: int, avatar_key: str):
    """
    Cập nhật avatar cho user hiện tại.

    Chỉ lưu tên file avatar vào database.
    Sau khi đổi avatar, clear cache users và leaderboard để Bảng xếp hạng cập nhật ngay.
    """
    avatar_key = normalize_avatar_key(avatar_key)

    if not avatar_key:
        raise ValueError("Chưa có avatar hợp lệ để chọn.")

    execute_sql(
        """
        UPDATE users
        SET avatar_key = :avatar_key
        WHERE user_id = :user_id
        """,
        {
            "avatar_key": avatar_key,
            "user_id": int(user_id)
        }
    )

    try:
        load_users.clear()
    except Exception:
        pass

    try:
        build_leaderboard_df.clear()
    except Exception:
        pass

def get_user_prediction(user_id: int, match_id: int):
    """
    Dùng cho UI.
    Lấy từ load_predictions() đã cache để tránh query database lặp lại cho từng card.
    """
    predictions = load_predictions()

    if predictions.empty:
        return None

    filtered = predictions[
        (predictions["user_id"].astype(int) == int(user_id))
        & (predictions["match_id"].astype(int) == int(match_id))
    ]

    if filtered.empty:
        return None

    return filtered.iloc[0].to_dict()

def build_user_prediction_map(predictions: pd.DataFrame, user_id: int) -> dict[int, dict]:
    """
    Tạo map dự đoán của user hiện tại để render card nhanh hơn.

    Không đổi logic:
    - Vẫn dùng dữ liệu từ load_predictions().
    - Vẫn lấy đúng prediction theo user_id và match_id.
    - Chỉ tránh filter DataFrame lặp lại trong từng match card.
    """
    if predictions.empty:
        return {}

    user_predictions = predictions[
        predictions["user_id"].astype(int) == int(user_id)
    ]

    if user_predictions.empty:
        return {}

    return {
        int(row["match_id"]): row.to_dict()
        for _, row in user_predictions.iterrows()
    }

def get_match_by_id(match_id: int):
    return fetch_one(
        """
        SELECT *
        FROM matches
        WHERE match_id = :match_id
        """,
        {
            "match_id": match_id
        }
    )

@st.cache_resource(show_spinner=False)
def get_gemini_client():
    if not GEMINI_API_KEY:
        raise ValueError("Chưa cấu hình GEMINI_API_KEY trong Streamlit Secrets.")

    return genai.Client(api_key=GEMINI_API_KEY)


def normalize_ai_summary_text(text: str) -> str:
    text = str(text or "").strip()

    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("```", "")
    text = text.replace("AI Summary:", "")
    text = text.replace("AI summary:", "")
    text = text.replace("AI tổng kết:", "")
    text = text.replace("Nguồn:", "")
    text = text.replace("Sources:", "")
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("* ", "")
    text = re.sub(r"^\s*[-*•]\s*", "", text, flags=re.MULTILINE)

    # Giữ lại toàn bộ nội dung, chỉ chuẩn hóa khoảng trắng
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def build_ai_match_summary_prompt(match_row: dict) -> str:
    home_name = match_row.get("home_team_name")
    away_name = match_row.get("away_team_name")
    match_name = f"{home_name} vs {away_name}"

    actual_home = to_optional_int(match_row.get("home_score_for_prediction"))
    actual_away = to_optional_int(match_row.get("away_score_for_prediction"))

    round_name = match_row.get("round_name", "")
    date_text = match_row.get(
        "kickoff_date_display_vietnam",
        match_row.get("kickoff_date_vietnam", "")
    )
    time_text = match_row.get("kickoff_time_vietnam", "")
    venue = match_row.get("venue", "")

    app_context_parts = [
        f"Trận đấu trong app: {match_name}",
        f"Vòng đấu: {round_name}",
        f"Thời gian theo Việt Nam: {date_text} {time_text}",
    ]

    if actual_home is not None and actual_away is not None:
        app_context_parts.append(f"Tỉ số trong app: {actual_home} - {actual_away}")

    if venue is not None and not pd.isna(venue) and str(venue).strip():
        app_context_parts.append(f"Sân vận động: {venue}")

    app_context = "\n".join(app_context_parts)

    prompt = (
        "Bạn là một chuyên gia cập nhật tin tức bóng đá và World Cup 2026. "
        "Trước khi trả lời, hãy sử dụng Google Search để tìm thông tin cập nhật về trận đấu này. "
        f"Hãy viết summary về trận đấu giữa {match_name} trong khuôn khổ World Cup 2026. "
        "Mục tiêu là giúp người xem hiểu thêm diễn biến trận đấu và thế trận, "
        "bổ sung thêm thông tin so với việc chỉ nhìn tỉ số và cầu thủ ghi bàn. "
        "Chỉ trả lời bằng tiếng Việt, không quá 60 chữ. "
        "Chỉ trả lời bằng văn bản thuần, không dùng HTML, CSS, Markdown, bảng, bullet point, code block hoặc thẻ div. "
        "Không thêm tiêu đề, không thêm nhãn 'AI Summary', không thêm phần 'Nguồn'. "
        "Có thể viết đầy đủ nhiều câu nếu cần, miễn là rõ ràng và dễ hiểu.\n\n"
        "Thông tin gợi ý từ app để đối chiếu khi tìm kiếm:\n"
        f"{app_context}\n\n"
        "Nếu kết quả tìm kiếm có nhiều trận trùng tên, hãy ưu tiên trận đúng World Cup 2026, đúng tỉ số và đúng vòng đấu ở trên."
    )

    return prompt


def get_ai_match_summary_from_db(match_id: int):
    return fetch_one(
        """
        SELECT
            match_id,
            summary_text,
            model_name,
            created_at,
            updated_at
        FROM match_ai_summaries
        WHERE match_id = :match_id
        """,
        {
            "match_id": int(match_id)
        }
    )


def save_ai_match_summary_to_db(
    match_id: int,
    summary_text: str,
    model_name: str
):
    now_text = now_utc_iso()

    execute_sql(
        """
        INSERT INTO match_ai_summaries (
            match_id,
            summary_text,
            model_name,
            created_at,
            updated_at
        )
        VALUES (
            :match_id,
            :summary_text,
            :model_name,
            :created_at,
            :updated_at
        )
        ON CONFLICT (match_id)
        DO UPDATE SET
            summary_text = EXCLUDED.summary_text,
            model_name = EXCLUDED.model_name,
            updated_at = EXCLUDED.updated_at
        """,
        {
            "match_id": int(match_id),
            "summary_text": summary_text,
            "model_name": model_name,
            "created_at": now_text,
            "updated_at": now_text
        }
    )


def generate_ai_match_summary(match_row: dict) -> str:
    client = get_gemini_client()
    prompt = build_ai_match_summary_prompt(match_row)

    grounding_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    config = types.GenerateContentConfig(
        tools=[grounding_tool]
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=prompt,
            config=config
        )

    except Exception as e:
        error_text = str(e)

        if (
            "prepayment credits are depleted" in error_text.lower()
            or "resource_exhausted" in error_text.lower()
            or "too_many_requests" in error_text.lower()
            or "429" in error_text
        ):
            raise ValueError(
                "Gemini API đã hết credit hoặc vượt giới hạn quota. "
                "Hãy kiểm tra billing/quota trong Google AI Studio."
            )

        raise

    summary_text = normalize_ai_summary_text(getattr(response, "text", ""))

    if not summary_text:
        raise ValueError("Gemini không trả về nội dung summary hợp lệ.")

    bad_markers = [
        "chưa diễn ra",
        "chưa có thông tin",
        "không tìm thấy thông tin",
        "không có dữ liệu",
        "không thể xác nhận"
    ]

    lowered_summary = summary_text.lower()

    if any(marker in lowered_summary for marker in bad_markers):
        raise ValueError(
            "Gemini chưa tìm được thông tin đủ chắc chắn về trận này. "
            "Summary chưa được lưu để tránh lưu nội dung sai."
        )

    return summary_text

# ============================================================
# 7. PREDICTION SAVE + SCORING
# ============================================================
def get_star_transfer_candidates(
    user_id: int,
    target_match_id: int,
    star_type: str
) -> list[dict]:
    """
    Lấy các trận đang giữ tạm loại sao này và còn mở dự đoán,
    để người chơi có thể chọn chuyển sao sang trận hiện tại.
    """
    star_type = normalize_star_type(star_type)

    if star_type == STAR_TYPE_NONE:
        return []

    df = read_sql(
        """
        SELECT
            p.prediction_id,
            p.match_id,
            p.star_type,
            m.home_team_name,
            m.away_team_name,
            m.round_name,
            m.kickoff_date_display_vietnam,
            m.kickoff_date_vietnam,
            m.kickoff_time_vietnam,
            m.kickoff_time_utc,
            m.is_finished
        FROM predictions p
        JOIN matches m
          ON p.match_id = m.match_id
        WHERE p.user_id = :user_id
          AND p.match_id <> :target_match_id
          AND p.star_type = :star_type
        ORDER BY m.kickoff_time_utc
        """,
        {
            "user_id": int(user_id),
            "target_match_id": int(target_match_id),
            "star_type": star_type
        }
    )

    if df.empty:
        return []

    candidates = []

    for _, row in df.iterrows():
        if not is_match_open_for_star_transfer(
            row.get("kickoff_time_utc"),
            row.get("is_finished")
        ):
            continue

        date_text = row.get(
            "kickoff_date_display_vietnam",
            row.get("kickoff_date_vietnam", "")
        )

        label = (
            f"{row.get('home_team_name')} vs {row.get('away_team_name')}"
            f" | {row.get('round_name')}"
            f" | {date_text} {row.get('kickoff_time_vietnam', '')}"
        )

        candidates.append({
            "prediction_id": int(row["prediction_id"]),
            "match_id": int(row["match_id"]),
            "label": label
        })

    return candidates


def get_star_save_plan(
    user_id: int,
    match_id: int,
    selected_star_type: str,
    current_star_type: str
) -> dict:
    """
    Quyết định khi lưu:
    - save_direct: lưu thẳng.
    - exhausted: sao đã hết thật.
    - transfer_required: cần hỏi chuyển sao từ trận khác.
    """
    selected_star_type = normalize_star_type(selected_star_type)
    current_star_type = normalize_star_type(current_star_type)

    if selected_star_type == STAR_TYPE_NONE:
        return {
            "status": "save_direct",
            "candidates": []
        }

    if selected_star_type == current_star_type:
        return {
            "status": "save_direct",
            "candidates": []
        }

    usage = get_user_star_usage_from_db(
        user_id=user_id,
        exclude_match_id=match_id
    )

    if selected_star_type == STAR_TYPE_HOPE:
        left_key = "hope_left"
        free_key = "hope_free_left"
        star_name = "Ngôi sao hy vọng"

    elif selected_star_type == STAR_TYPE_SUPER:
        left_key = "super_left"
        free_key = "super_free_left"
        star_name = "Siêu sao"

    else:
        return {
            "status": "save_direct",
            "candidates": []
        }

    if usage[left_key] <= 0:
        return {
            "status": "exhausted",
            "message": f"Bạn đã dùng hết {star_name}.",
            "candidates": []
        }

    if usage[free_key] > 0:
        return {
            "status": "save_direct",
            "candidates": []
        }

    candidates = get_star_transfer_candidates(
        user_id=user_id,
        target_match_id=match_id,
        star_type=selected_star_type
    )

    if not candidates:
        return {
            "status": "exhausted",
            "message": f"Hiện không còn {star_name} trống để dùng cho trận này.",
            "candidates": []
        }

    return {
        "status": "transfer_required",
        "candidates": candidates
    }

def save_prediction(
    user_id: int,
    match_id: int,
    predicted_home_score: int,
    predicted_away_score: int,
    predicted_winner_team_id: int | None,
    star_type: str = STAR_TYPE_NONE
):
    star_type = normalize_star_type(star_type)

    predicted_home_score = int(predicted_home_score)
    predicted_away_score = int(predicted_away_score)

    if predicted_winner_team_id is not None:
        predicted_winner_team_id = int(predicted_winner_team_id)

    match = get_match_by_id(match_id)

    if match is None:
        raise ValueError("Không tìm thấy trận đấu.")

    if not can_edit_prediction(match["kickoff_time_utc"]):
        raise ValueError("Trận đấu đã khóa dự đoán.")

    is_knockout = to_bool(match.get("is_knockout"))

    if is_knockout:
        home_team_id = to_optional_int(match.get("home_team_id"))
        away_team_id = to_optional_int(match.get("away_team_id"))

        if predicted_home_score > predicted_away_score:
            predicted_winner_team_id = home_team_id

        elif predicted_away_score > predicted_home_score:
            predicted_winner_team_id = away_team_id

        else:
            valid_winner_ids = [
                home_team_id,
                away_team_id
            ]

            if predicted_winner_team_id not in valid_winner_ids:
                raise ValueError(
                    "Trận knockout hòa. Bạn cần chọn đội thắng chung cuộc."
                )

    validate_star_quota(
        user_id=user_id,
        match_id=match_id,
        star_type=star_type
    )

    existing = get_user_prediction_from_db(user_id, match_id)
    now_text = now_utc_iso()

    with get_engine().begin() as conn:
        if existing is None:
            conn.execute(
                text(
                    """
                    INSERT INTO predictions (
                        user_id,
                        match_id,
                        predicted_home_score,
                        predicted_away_score,
                        predicted_winner_team_id,
                        star_type,
                        base_points,
                        star_bonus_points,
                        points,
                        submitted_at,
                        updated_at
                    )
                    VALUES (
                        :user_id,
                        :match_id,
                        :predicted_home_score,
                        :predicted_away_score,
                        :predicted_winner_team_id,
                        :star_type,
                        NULL,
                        NULL,
                        NULL,
                        :submitted_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "user_id": user_id,
                    "match_id": match_id,
                    "predicted_home_score": predicted_home_score,
                    "predicted_away_score": predicted_away_score,
                    "predicted_winner_team_id": predicted_winner_team_id,
                    "star_type": star_type,
                    "submitted_at": now_text,
                    "updated_at": now_text
                }
            )

        else:
            prediction_id = existing["prediction_id"]

            conn.execute(
                text(
                    """
                    INSERT INTO prediction_history (
                        prediction_id,
                        old_home_score,
                        old_away_score,
                        old_winner_team_id,
                        new_home_score,
                        new_away_score,
                        new_winner_team_id,
                        changed_at
                    )
                    VALUES (
                        :prediction_id,
                        :old_home_score,
                        :old_away_score,
                        :old_winner_team_id,
                        :new_home_score,
                        :new_away_score,
                        :new_winner_team_id,
                        :changed_at
                    )
                    """
                ),
                {
                    "prediction_id": prediction_id,
                    "old_home_score": existing["predicted_home_score"],
                    "old_away_score": existing["predicted_away_score"],
                    "old_winner_team_id": existing["predicted_winner_team_id"],
                    "new_home_score": predicted_home_score,
                    "new_away_score": predicted_away_score,
                    "new_winner_team_id": predicted_winner_team_id,
                    "changed_at": now_text
                }
            )

            conn.execute(
                text(
                    """
                    UPDATE predictions
                    SET
                        predicted_home_score = :predicted_home_score,
                        predicted_away_score = :predicted_away_score,
                        predicted_winner_team_id = :predicted_winner_team_id,
                        star_type = :star_type,
                        updated_at = :updated_at,
                        base_points = NULL,
                        star_bonus_points = NULL,
                        points = NULL
                    WHERE prediction_id = :prediction_id
                    """
                ),
                {
                    "predicted_home_score": predicted_home_score,
                    "predicted_away_score": predicted_away_score,
                    "predicted_winner_team_id": predicted_winner_team_id,
                    "star_type": star_type,
                    "updated_at": now_text,
                    "prediction_id": prediction_id
                }
            )

    clear_data_cache()

def transfer_star_and_save_prediction(
    user_id: int,
    source_match_id: int,
    target_match_id: int,
    predicted_home_score: int,
    predicted_away_score: int,
    predicted_winner_team_id: int | None,
    star_type: str
):
    """
    Gỡ sao khỏi trận nguồn rồi lưu sao cho trận đích.
    Chỉ cho chuyển từ trận còn mở dự đoán.
    """
    star_type = normalize_star_type(star_type)

    if star_type == STAR_TYPE_NONE:
        raise ValueError("Không có bổ trợ nào cần chuyển.")

    source_match = get_match_by_id(source_match_id)

    if source_match is None:
        raise ValueError("Không tìm thấy trận đang giữ sao.")

    if not can_edit_prediction(source_match["kickoff_time_utc"]):
        raise ValueError("Trận đang giữ sao đã khóa, không thể chuyển sao nữa.")

    source_prediction = get_user_prediction_from_db(
        user_id=user_id,
        match_id=source_match_id
    )

    if source_prediction is None:
        raise ValueError("Trận được chọn không còn giữ bổ trợ này.")

    if normalize_star_type(source_prediction.get("star_type")) != star_type:
        raise ValueError("Trận được chọn không còn giữ đúng loại bổ trợ này.")

    execute_sql(
        """
        UPDATE predictions
        SET
            star_type = 'none',
            base_points = NULL,
            star_bonus_points = NULL,
            points = NULL,
            updated_at = :updated_at
        WHERE user_id = :user_id
          AND match_id = :source_match_id
          AND star_type = :star_type
        """,
        {
            "updated_at": now_utc_iso(),
            "user_id": int(user_id),
            "source_match_id": int(source_match_id),
            "star_type": star_type
        }
    )

    clear_data_cache()

    save_prediction(
        user_id=user_id,
        match_id=target_match_id,
        predicted_home_score=predicted_home_score,
        predicted_away_score=predicted_away_score,
        predicted_winner_team_id=predicted_winner_team_id,
        star_type=star_type
    )

def delete_prediction(user_id: int, match_id: int):
    """
    Xóa dự đoán đã lưu của user cho một trận.

    Chỉ cho xóa khi trận vẫn còn mở dự đoán.
    Khi xóa:
    - Xóa prediction_history liên quan nếu có.
    - Xóa prediction chính.
    - Clear cache để UI quay về trạng thái chưa dự đoán.
    """
    match = get_match_by_id(match_id)

    if match is None:
        raise ValueError("Không tìm thấy trận đấu.")

    if not can_edit_prediction(match["kickoff_time_utc"]):
        raise ValueError("Trận đấu đã khóa dự đoán, bạn không thể hủy dự đoán nữa.")

    existing = get_user_prediction_from_db(
        user_id=user_id,
        match_id=match_id
    )

    if existing is None:
        clear_data_cache()
        return

    prediction_id = int(existing["prediction_id"])

    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM prediction_history
                WHERE prediction_id = :prediction_id
                """
            ),
            {
                "prediction_id": prediction_id
            }
        )

        conn.execute(
            text(
                """
                DELETE FROM predictions
                WHERE prediction_id = :prediction_id
                  AND user_id = :user_id
                  AND match_id = :match_id
                """
            ),
            {
                "prediction_id": prediction_id,
                "user_id": user_id,
                "match_id": match_id
            }
        )

    clear_data_cache()

def score_all_predictions():
    """
    Chấm điểm lại toàn bộ dự đoán đã có kết quả.

    Tối ưu:
    - Vẫn giữ nguyên logic tính điểm hiện tại.
    - Vẫn kiểm tra toàn bộ prediction đã có kết quả.
    - Chỉ UPDATE database khi điểm mới khác điểm đang lưu.
    - Nếu không có gì thay đổi thì KHÔNG clear cache, giúp Bảng xếp hạng load nhanh hơn nhiều.
    """
    matches = load_matches()
    predictions = load_predictions()

    if predictions.empty:
        return

    df = predictions.merge(
        matches,
        on="match_id",
        how="left"
    )

    scored_rows = []

    for _, row in df.iterrows():
        is_finished = to_bool(row.get("is_finished"))

        actual_home = to_optional_int(row.get("home_score_for_prediction"))
        actual_away = to_optional_int(row.get("away_score_for_prediction"))

        if not is_finished or actual_home is None or actual_away is None:
            continue

        base_points = calculate_total_points(row)

        point_info = calculate_points_with_star(
            base_points=base_points,
            star_type=row.get("star_type")
        )

        new_base_points = int(point_info["base_points"])
        new_star_bonus_points = int(point_info["star_bonus_points"])
        new_points = int(point_info["points"])

        current_base_points = to_optional_int(row.get("base_points"))
        current_star_bonus_points = to_optional_int(row.get("star_bonus_points"))
        current_points = to_optional_int(row.get("points"))

        # Chỉ ghi DB nếu điểm thật sự thay đổi.
        # Đây là phần giúp giảm loading mạnh nhất.
        if (
            current_base_points == new_base_points
            and current_star_bonus_points == new_star_bonus_points
            and current_points == new_points
        ):
            continue

        scored_rows.append(
            {
                "base_points": new_base_points,
                "star_bonus_points": new_star_bonus_points,
                "points": new_points,
                "prediction_id": int(row["prediction_id"])
            }
        )

    if not scored_rows:
        return

    execute_many(
        """
        UPDATE predictions
        SET
            base_points = :base_points,
            star_bonus_points = :star_bonus_points,
            points = :points
        WHERE prediction_id = :prediction_id
        """,
        scored_rows
    )

    clear_data_cache()


def update_match_result(
    match_id: int,
    score_ft_home: int,
    score_ft_away: int,
    score_et_home: int | None,
    score_et_away: int | None,
    score_pen_home: int | None,
    score_pen_away: int | None,
    winner_team_id: int | None
):
    match = get_match_by_id(match_id)

    if match is None:
        raise ValueError("Không tìm thấy trận đấu.")

    is_knockout = to_bool(match.get("is_knockout"))

    home_team_id = to_optional_int(match.get("home_team_id"))
    away_team_id = to_optional_int(match.get("away_team_id"))

    home_team_name = match.get("home_team_name")
    away_team_name = match.get("away_team_name")

    if score_et_home is not None and score_et_away is not None:
        home_score_for_prediction = score_et_home
        away_score_for_prediction = score_et_away
    else:
        home_score_for_prediction = score_ft_home
        away_score_for_prediction = score_ft_away

    if not is_knockout:
        if home_score_for_prediction > away_score_for_prediction:
            winner_team_id = home_team_id
        elif away_score_for_prediction > home_score_for_prediction:
            winner_team_id = away_team_id
        else:
            winner_team_id = None

    if is_knockout:
        if home_score_for_prediction > away_score_for_prediction:
            winner_team_id = home_team_id
        elif away_score_for_prediction > home_score_for_prediction:
            winner_team_id = away_team_id
        else:
            if winner_team_id is None:
                raise ValueError(
                    "Trận knockout hòa sau thời gian thi đấu. "
                    "Bạn cần chọn đội thắng chung cuộc."
                )

    winner_team_name = None

    if winner_team_id == home_team_id:
        winner_team_name = home_team_name
    elif winner_team_id == away_team_id:
        winner_team_name = away_team_name

    execute_sql(
        """
        UPDATE matches
        SET
            score_ft_home = :score_ft_home,
            score_ft_away = :score_ft_away,
            score_et_home = :score_et_home,
            score_et_away = :score_et_away,
            score_pen_home = :score_pen_home,
            score_pen_away = :score_pen_away,
            home_score_for_prediction = :home_score_for_prediction,
            away_score_for_prediction = :away_score_for_prediction,
            winner_team_id = :winner_team_id,
            winner_team_name = :winner_team_name,
            is_finished = TRUE
        WHERE match_id = :match_id
        """,
        {
            "score_ft_home": score_ft_home,
            "score_ft_away": score_ft_away,
            "score_et_home": score_et_home,
            "score_et_away": score_et_away,
            "score_pen_home": score_pen_home,
            "score_pen_away": score_pen_away,
            "home_score_for_prediction": home_score_for_prediction,
            "away_score_for_prediction": away_score_for_prediction,
            "winner_team_id": winner_team_id,
            "winner_team_name": winner_team_name,
            "match_id": match_id
        }
    )

    clear_data_cache()
    score_all_predictions()


# ============================================================
# 8. AUTH UI
# ============================================================
def render_auth_page():
    render_app_hero()

    with stylable_container(
        key="auth_card",
        css_styles="""
        {
            background: rgba(255,255,255,0.94);
            border: 1px solid rgba(15,23,42,0.08);
            border-radius: 24px;
            padding: 22px;
            box-shadow: 0 18px 42px rgba(15,23,42,0.10);
        }
        """
    ):
        render_page_title(
            "Đăng nhập",
            "Tạo tài khoản để lưu dự đoán, theo dõi điểm và cạnh tranh cùng bạn bè."
        )

        tab_login, tab_register = st.tabs(["Đăng nhập", "Đăng ký"])

        with tab_login:
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Mật khẩu", type="password")

                submitted = st.form_submit_button("Đăng nhập")

                if submitted:
                    user = login_user(username, password)

                    if user is None:
                        st.error("Sai username hoặc mật khẩu.")
                    else:
                        clear_filter_state()

                        session_token = create_login_session(user["user_id"])

                        cookie_controller.set(
                            COOKIE_NAME,
                            session_token,
                            max_age=SESSION_DAYS * 24 * 60 * 60
                        )

                        st.session_state["user"] = user
                        st.session_state["selected_page"] = "Lịch thi đấu & dự đoán"
                        set_login_cookie_and_reload(session_token)

        with tab_register:
            st.info("Mật khẩu phải có ít nhất 8 ký tự.")

            with st.form("register_form"):
                username = st.text_input("Username", key="register_username")
                display_name = st.text_input("Tên hiển thị")
                password = st.text_input("Mật khẩu", type="password", key="register_password")
                password_confirm = st.text_input("Nhập lại mật khẩu", type="password")

                submitted = st.form_submit_button("Tạo tài khoản")

                if submitted:
                    if password != password_confirm:
                        st.error("Mật khẩu nhập lại không khớp.")
                    else:
                        try:
                            role = create_user(username, display_name, password)
                            st.success(f"Tạo tài khoản thành công. Role của bạn: {role}. Hãy đăng nhập.")
                        except ValueError as e:
                            st.error(str(e))


# ============================================================
# 9. MATCH CARD UI
# ============================================================
def render_match_title(home_name, away_name, match_id: int):
    home_display = "TBD" if home_name is None or pd.isna(home_name) else str(home_name)
    away_display = "TBD" if away_name is None or pd.isna(away_name) else str(away_name)

    safe_home = html.escape(home_display)
    safe_away = html.escape(away_display)

    # Desktop: giữ nguyên st.subheader như cũ, chỉ ẩn nó trên mobile
    with stylable_container(
        key=f"match_title_desktop_{match_id}",
        css_styles="""
        {
            display: block;
        }

        @media (max-width: 768px) {
            {
                display: none !important;
            }
        }
        """
    ):
        st.subheader(f"{home_display} vs {away_display}")

    # Mobile: title riêng, mỗi đội đúng 1 dòng
    st.markdown(
        f"""
        <div class="wc-match-title-mobile" aria-label="{safe_home} vs {safe_away}">
            <div class="wc-match-team">{safe_home}</div>
            <div class="wc-match-vs">vs</div>
            <div class="wc-match-team">{safe_away}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

def render_match_title(home_name, away_name, match_id: int):
    home_display = "TBD" if home_name is None or pd.isna(home_name) else str(home_name)
    away_display = "TBD" if away_name is None or pd.isna(away_name) else str(away_name)

    safe_home = html.escape(home_display)
    safe_away = html.escape(away_display)

    # Desktop: giữ nguyên kiểu st.subheader cũ
    with stylable_container(
        key=f"match_title_desktop_{match_id}",
        css_styles="""
        {
            display: block;
        }
        """
    ):
        st.subheader(f"{home_display} vs {away_display}")

    # Mobile: hiển thị dạng 3 dòng
    st.markdown(
        f"""
        <div class="wc-match-title-mobile" aria-label="{safe_home} vs {safe_away}">
            <div class="wc-match-team">{safe_home}</div>
            <div class="wc-match-vs">vs</div>
            <div class="wc-match-team">{safe_away}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

def normalize_venue_text(value) -> str:
    """
    Chuẩn hóa tên SVĐ/địa điểm để hiển thị ở cuối card.
    """
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass

    return str(value).strip()


def render_match_venue_footer(row, match_id: int):
    """
    Hiển thị thông tin sân vận động/địa điểm ở cuối card trận đấu.

    Chỉ hiển thị dạng:
    Icon: Tên sân vận động

    Không nằm trong form dự đoán.
    Không ảnh hưởng logic lưu/cập nhật/xóa dự đoán.
    """
    venue = normalize_venue_text(row.get("venue"))

    if not venue:
        return

    safe_venue = html.escape(venue)

    soccer_field_icon_svg = """
    <svg xmlns="http://www.w3.org/2000/svg"
         width="24"
         height="24"
         viewBox="0 0 24 24"
         fill="none"
         stroke="currentColor"
         stroke-width="1"
         stroke-linecap="round"
         stroke-linejoin="round"
         style="display:inline-block; vertical-align:-6px;">
      <path stroke="none" d="M0 0h24v24H0z" fill="none"/>
      <path d="M9 12a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"/>
      <path d="M3 9h3v6h-3l0 -6"/>
      <path d="M18 9h3v6h-3l0 -6"/>
      <path d="M3 7a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v10a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-10"/>
      <path d="M12 5l0 14"/>
    </svg>
    """

    st.markdown(
        f"""
        <div style="
            margin-top: 20px;
            margin-bottom: 0;
            color: #64748B;
            font-size: 14.5px;
            font-weight: 700;
            line-height: 1.35;
        ">
            <span style="
                color: #64748B;
                margin-right: 6px;
            ">
                {soccer_field_icon_svg}:
            </span>
            <span style="
                color: #64748B;
                font-style: italic;
            ">{safe_venue}</span>
        </div>
        """,
        unsafe_allow_html=True
    )

def render_pending_star_transfer_box(user_id: int, match_id: int):
    pending = st.session_state.get("pending_star_transfer")

    if not pending:
        return

    if int(pending.get("target_match_id")) != int(match_id):
        return

    star_type = normalize_star_type(pending.get("star_type"))
    star_label = format_star_short(star_type)
    candidates = pending.get("candidates", [])

    if not candidates:
        st.session_state.pop("pending_star_transfer", None)
        return

    candidate_options = {
        candidate["label"]: candidate
        for candidate in candidates
    }

    with stylable_container(
        key=f"star_transfer_confirm_box_{match_id}",
        css_styles="""
        {
            margin-top: 18px;
            margin-bottom: 18px;
            padding: 18px 20px;
            border-radius: 20px;
            border: 1px solid rgba(245, 158, 11, 0.42);
            background:
                radial-gradient(circle at top left, rgba(245, 197, 66, 0.18), transparent 34%),
                linear-gradient(135deg, rgba(255, 251, 235, 0.98), rgba(255, 255, 255, 0.96));
            box-shadow: 0 18px 42px rgba(15, 23, 42, 0.12);
        }

        div[data-testid="stSelectbox"] label {
            color: #07111F !important;
            font-weight: 850 !important;
        }
        """
    ):
        st.markdown(
            f"""
            <div style="
                color:#07111F;
                font-weight:950;
                font-size:18px;
                margin-bottom:6px;
            ">
                Xác nhận chuyển bổ trợ
            </div>

            <div style="
                color:#475569;
                font-size:14px;
                line-height:1.55;
                margin-bottom:14px;
            ">
                Bạn đang muốn dùng <b>{html.escape(star_label)}</b> cho trận
                <b>{html.escape(str(pending.get("target_label")))}</b>.
                Tuy nhiên bổ trợ còn lại này đang được đặt ở trận khác chưa diễn ra.
                Hãy chọn trận muốn gỡ sao để chuyển sang trận hiện tại.
            </div>
            """,
            unsafe_allow_html=True
        )

        selected_source_label = st.selectbox(
            "Chọn trận muốn chuyển sao từ:",
            options=list(candidate_options.keys()),
            key=f"star_transfer_source_{match_id}"
        )

        confirm_col, cancel_col = st.columns([1, 1])

        with confirm_col:
            confirm_transfer = st.button(
                "Xác nhận chuyển sao",
                key=f"confirm_star_transfer_{match_id}",
                use_container_width=True
            )

        with cancel_col:
            cancel_transfer = st.button(
                "Hủy",
                key=f"cancel_star_transfer_{match_id}",
                use_container_width=True
            )

        if confirm_transfer:
            selected_candidate = candidate_options[selected_source_label]

            try:
                transfer_star_and_save_prediction(
                    user_id=user_id,
                    source_match_id=int(selected_candidate["match_id"]),
                    target_match_id=int(pending["target_match_id"]),
                    predicted_home_score=int(pending["predicted_home_score"]),
                    predicted_away_score=int(pending["predicted_away_score"]),
                    predicted_winner_team_id=pending["predicted_winner_team_id"],
                    star_type=star_type
                )

                st.session_state.pop("pending_star_transfer", None)
                st.success("Đã chuyển bổ trợ và lưu dự đoán.")
                st.rerun()

            except ValueError as e:
                st.error(str(e))

        if cancel_transfer:
            st.session_state.pop("pending_star_transfer", None)
            st.rerun()

@st.dialog("Xác nhận chuyển bổ trợ")
def render_star_transfer_dialog(user_id: int):
    pending = st.session_state.get("pending_star_transfer")

    if not pending:
        st.write("Không có bổ trợ nào cần chuyển.")
        if st.button("Đóng", use_container_width=True):
            st.rerun()
        return

    star_type = normalize_star_type(pending.get("star_type"))
    star_label = format_star_short(star_type)
    target_label = str(pending.get("target_label", "trận hiện tại"))

    candidates = pending.get("candidates", [])

    if not candidates:
        st.session_state.pop("pending_star_transfer", None)
        st.warning("Không còn trận hợp lệ để chuyển bổ trợ.")
        if st.button("Đóng", use_container_width=True):
            st.rerun()
        return

    candidate_options = {
        candidate["label"]: candidate
        for candidate in candidates
    }

    st.markdown(
        f"""
        <div style="
            color:#475569;
            font-size:14px;
            line-height:1.5;
            margin-bottom:14px;
        ">
            <b>{html.escape(star_label)}</b> đã được đặt hết.
            Chọn trận muốn gỡ sao để chuyển sang
            <b>{html.escape(target_label)}</b>.
        </div>
        """,
        unsafe_allow_html=True
    )

    selected_source_label = st.selectbox(
        "Chuyển từ trận:",
        options=list(candidate_options.keys()),
        key="star_transfer_source_modal"
    )

    col_confirm, col_cancel = st.columns([1, 1])

    with col_confirm:
        confirm_transfer = st.button(
            "Chuyển sao",
            type="primary",
            use_container_width=True,
            key="confirm_star_transfer_modal"
        )

    with col_cancel:
        cancel_transfer = st.button(
            "Hủy",
            use_container_width=True,
            key="cancel_star_transfer_modal"
        )

    if cancel_transfer:
        st.session_state.pop("pending_star_transfer", None)
        st.rerun()

    if confirm_transfer:
        selected_candidate = candidate_options[selected_source_label]
        source_match_id = int(selected_candidate["match_id"])
        target_match_id = int(pending["target_match_id"])

        try:
            source_match = get_match_by_id(source_match_id)

            if source_match is None:
                raise ValueError("Không tìm thấy trận đang giữ bổ trợ.")

            if not can_edit_prediction(source_match["kickoff_time_utc"]):
                raise ValueError(
                    "Trận đang giữ bổ trợ đã khóa, không thể chuyển sao."
                )

            target_match = get_match_by_id(target_match_id)

            if target_match is None:
                raise ValueError("Không tìm thấy trận cần chuyển bổ trợ sang.")

            if not can_edit_prediction(target_match["kickoff_time_utc"]):
                raise ValueError(
                    "Trận này vừa khóa dự đoán, không thể chuyển sao."
                )

            source_prediction = get_user_prediction_from_db(
                user_id=user_id,
                match_id=source_match_id
            )

            if source_prediction is None:
                raise ValueError("Trận được chọn không còn giữ bổ trợ này.")

            if normalize_star_type(source_prediction.get("star_type")) != star_type:
                raise ValueError("Trận được chọn không còn giữ đúng loại bổ trợ này.")

            execute_sql(
                """
                UPDATE predictions
                SET
                    star_type = 'none',
                    base_points = NULL,
                    star_bonus_points = NULL,
                    points = NULL,
                    updated_at = :updated_at
                WHERE user_id = :user_id
                  AND match_id = :source_match_id
                  AND star_type = :star_type
                """,
                {
                    "updated_at": now_utc_iso(),
                    "user_id": int(user_id),
                    "source_match_id": source_match_id,
                    "star_type": star_type
                }
            )

            clear_data_cache()

            save_prediction(
                user_id=user_id,
                match_id=target_match_id,
                predicted_home_score=int(pending["predicted_home_score"]),
                predicted_away_score=int(pending["predicted_away_score"]),
                predicted_winner_team_id=pending["predicted_winner_team_id"],
                star_type=star_type
            )

            st.session_state.pop("pending_star_transfer", None)
            st.session_state["star_transfer_success_message"] = (
                "Đã chuyển bổ trợ và lưu dự đoán."
            )

            st.rerun()

        except ValueError as e:
            st.error(str(e))

@st.dialog("AI tổng kết trận đấu")
def render_ai_match_summary_dialog(match_id: int):
    match_id = int(match_id)

    match = get_match_by_id(match_id)

    if match is None:
        st.error("Không tìm thấy trận đấu.")
        if st.button(
            "Đóng",
            use_container_width=True,
            key=f"close_ai_summary_missing_{match_id}"
        ):
            st.session_state.pop("ai_summary_match_id", None)
            st.rerun()
        return

    if not to_bool(match.get("is_finished")):
        st.warning("Chỉ có thể tạo AI tổng kết cho trận đã có kết quả.")
        if st.button(
            "Đóng",
            use_container_width=True,
            key=f"close_ai_summary_unfinished_{match_id}"
        ):
            st.session_state.pop("ai_summary_match_id", None)
            st.rerun()
        return

    home_name = match.get("home_team_name")
    away_name = match.get("away_team_name")

    actual_home = to_optional_int(match.get("home_score_for_prediction"))
    actual_away = to_optional_int(match.get("away_score_for_prediction"))

    score_text = ""
    if actual_home is not None and actual_away is not None:
        score_text = f"{actual_home}-{actual_away}"

    st.markdown(
        f"""
        <div style="
            color:#07111F;
            font-weight:900;
            font-size:18px;
            line-height:1.3;
            margin-bottom:10px;
            letter-spacing:-0.02em;
        ">
            {html.escape(str(home_name))} vs {html.escape(str(away_name))}
        </div>
        """,
        unsafe_allow_html=True
    )

    if score_text:
        st.markdown(
            f"""
            <div style="
                display:inline-flex;
                align-items:center;
                gap:6px;
                margin-bottom:16px;
                padding:7px 12px;
                border-radius:999px;
                background:#F8FAFC;
                border:1px solid rgba(15,23,42,0.08);
                color:#07111F;
                font-size:13px;
                font-weight:850;
            ">
                Kết quả: {html.escape(score_text)}
            </div>
            """,
            unsafe_allow_html=True
        )

    try:
        existing_summary = get_ai_match_summary_from_db(match_id)
    except Exception as e:
        st.error(
            "Chưa đọc được bảng match_ai_summaries. Hãy kiểm tra xem bạn đã tạo bảng trong Supabase chưa."
        )
        st.caption(str(e))
        return

    if existing_summary is not None:
        summary_text = existing_summary.get("summary_text", "")
    else:
        with st.spinner("AI đang tìm kiếm và tổng hợp diễn biến trận đấu..."):
            try:
                summary_text = generate_ai_match_summary(match)

                save_ai_match_summary_to_db(
                    match_id=match_id,
                    summary_text=summary_text,
                    model_name=GEMINI_MODEL_NAME
                )
            except Exception as e:
                st.error("Không tạo được AI summary cho trận này.")
                st.caption(str(e))
                return

    safe_summary = html.escape(str(summary_text)).replace("\n", "<br>")

    st.markdown(
        f"""
        <div style="
            color:#334155;
            font-size:15.5px;
            line-height:1.75;
            font-weight:400;
            margin-bottom:18px;
            white-space:normal;
            word-break:normal;
            overflow-wrap:anywhere;
        ">
            {safe_summary}
        </div>
        """,
        unsafe_allow_html=True
    )

    if st.button(
        "Đóng",
        use_container_width=True,
        key=f"close_ai_summary_{match_id}"
    ):
        st.session_state.pop("ai_summary_match_id", None)
        st.rerun()

def render_match_card(
    row,
    user_id: int,
    user_prediction_map: dict[int, dict] | None = None
):
    match_id = int(row["match_id"])

    home_team_id = to_optional_int(row.get("home_team_id"))
    away_team_id = to_optional_int(row.get("away_team_id"))

    home_name = row.get("home_team_name")
    away_name = row.get("away_team_name")

    is_knockout = to_bool(row.get("is_knockout"))
    is_finished = to_bool(row.get("is_finished"))

    editable = can_edit_prediction(row.get("kickoff_time_utc"))

    if user_prediction_map is None:
        existing = get_user_prediction(user_id, match_id)
    else:
        existing = user_prediction_map.get(match_id)

    status_info = get_match_status_info(row)
    card_css = get_match_card_css(status_info)

    def load_transfer_candidates_for_card(star_type: str) -> list[dict]:
        """
        Lấy các trận đang giữ tạm loại sao này và vẫn còn mở dự đoán,
        để người chơi có thể chọn chuyển sao sang trận hiện tại.
        """
        star_type = normalize_star_type(star_type)

        if star_type == STAR_TYPE_NONE:
            return []

        try:
            df_candidates = read_sql(
                """
                SELECT
                    p.prediction_id,
                    p.match_id,
                    p.star_type,
                    m.home_team_name,
                    m.away_team_name,
                    m.round_name,
                    m.kickoff_date_display_vietnam,
                    m.kickoff_date_vietnam,
                    m.kickoff_time_vietnam,
                    m.kickoff_time_utc,
                    m.is_finished
                FROM predictions p
                JOIN matches m
                  ON p.match_id = m.match_id
                WHERE p.user_id = :user_id
                  AND p.match_id <> :target_match_id
                  AND p.star_type = :star_type
                ORDER BY m.kickoff_time_utc
                """,
                {
                    "user_id": int(user_id),
                    "target_match_id": int(match_id),
                    "star_type": star_type
                }
            )
        except Exception:
            return []

        if df_candidates.empty:
            return []

        candidates = []

        for _, candidate_row in df_candidates.iterrows():
            candidate_match_id = int(candidate_row["match_id"])

            candidate_is_open = (
                not to_bool(candidate_row.get("is_finished"))
                and can_edit_prediction(candidate_row.get("kickoff_time_utc"))
            )

            if not candidate_is_open:
                continue

            date_text = candidate_row.get(
                "kickoff_date_display_vietnam",
                candidate_row.get("kickoff_date_vietnam", "")
            )

            label = (
                f"{candidate_row.get('home_team_name')} vs {candidate_row.get('away_team_name')}"
                f" | {candidate_row.get('round_name')}"
                f" | {date_text} {candidate_row.get('kickoff_time_vietnam', '')}"
            )

            candidates.append({
                "prediction_id": int(candidate_row["prediction_id"]),
                "match_id": candidate_match_id,
                "label": label
            })

        return candidates

    with stylable_container(
        key=f"match_card_{match_id}",
        css_styles=card_css
    ):
        render_status_badge(status_info)

        top_left, top_right = st.columns([3, 1])

        with top_left:
            render_match_title(home_name, away_name, match_id)

            st.caption(
                f"{row.get('round_name')} | "
                f"{row.get('kickoff_weekday_vietnam', '')} "
                f"{row.get('kickoff_date_display_vietnam', row.get('kickoff_date_vietnam', ''))} "
                f"lúc {row.get('kickoff_time_vietnam', '')}"
            )

            if is_finished:
                actual_home_for_goal_button = to_optional_int(
                    row.get("home_score_for_prediction")
                )
                actual_away_for_goal_button = to_optional_int(
                    row.get("away_score_for_prediction")
                )

                has_any_goal = (
                    actual_home_for_goal_button is not None
                    and actual_away_for_goal_button is not None
                    and (actual_home_for_goal_button + actual_away_for_goal_button) > 0
                )

                if has_any_goal:
                    render_goal_scorers_for_match(match_id)

        with top_right:
            actual_home = to_optional_int(row.get("home_score_for_prediction"))
            actual_away = to_optional_int(row.get("away_score_for_prediction"))

            score_et_home = to_optional_int(row.get("score_et_home"))
            score_et_away = to_optional_int(row.get("score_et_away"))

            score_pen_home = to_optional_int(row.get("score_pen_home"))
            score_pen_away = to_optional_int(row.get("score_pen_away"))

            has_extra_time = (
                is_knockout
                and score_et_home is not None
                and score_et_away is not None
            )

            has_penalty = (
                is_knockout
                and score_pen_home is not None
                and score_pen_away is not None
            )
            if is_finished:
                ai_summary_clicked = st.button(
                    "AI tổng kết trận đấu",
                    key=f"ai_summary_button_{match_id}",
                    type="secondary",
                    use_container_width=True
                )

                if ai_summary_clicked:
                    st.session_state["ai_summary_match_id"] = match_id
                    st.rerun()
            if is_finished and actual_home is not None and actual_away is not None:
                result_text = f"{actual_home} - {actual_away}"

                if has_extra_time or has_penalty:
                    result_text = f"{result_text} (a.e.t)"

                penalty_line_html = ""

                if has_penalty:
                    penalty_line_html = (
                        '<div style="'
                        'margin-top:10px;'
                        'padding-top:9px;'
                        'border-top:1px solid rgba(15,23,42,0.08);'
                        'color:#64748B;'
                        'font-size:13px;'
                        'font-weight:750;'
                        'line-height:1.25;'
                        '">'
                        'Penalty:'
                        '<span style="'
                        'color:#07111F;'
                        'font-weight:950;'
                        'margin-left:4px;'
                        '">'
                        f'{score_pen_home} - {score_pen_away}'
                        '</span>'
                        '</div>'
                    )

                result_card_html = (
                    '<div style="'
                    'background:rgba(255,255,255,0.86);'
                    'border:1px solid rgba(15,23,42,0.08);'
                    'border-radius:16px;'
                    'padding:13px 15px;'
                    'box-shadow:0 6px 18px rgba(15,23,42,0.04);'
                    'min-width:180px;'
                    '">'
                    '<div style="'
                    'color:#64748B;'
                    'font-size:12px;'
                    'font-weight:800;'
                    'margin-bottom:6px;'
                    '">'
                    'Kết quả'
                    '</div>'
                    '<div style="'
                    'color:#07111F;'
                    'font-size:32px;'
                    'font-weight:950;'
                    'line-height:1.1;'
                    'letter-spacing:-0.03em;'
                    'white-space:nowrap;'
                    '">'
                    f'{html.escape(result_text)}'
                    '</div>'
                    f'{penalty_line_html}'
                    '</div>'
                )

                st.markdown(
                    result_card_html,
                    unsafe_allow_html=True
                )

                winner_name = row.get("winner_team_name")

                winner_name_is_valid = (
                    winner_name is not None
                    and not pd.isna(winner_name)
                    and str(winner_name).strip().lower() not in ["", "nan", "none"]
                )

                if winner_name_is_valid:
                    final_winner_text = str(winner_name).strip()

                elif not is_knockout and actual_home == actual_away:
                    final_winner_text = "2 đội hòa nhau"

                elif has_penalty and score_pen_home > score_pen_away:
                    final_winner_text = str(home_name)

                elif has_penalty and score_pen_away > score_pen_home:
                    final_winner_text = str(away_name)

                elif actual_home > actual_away:
                    final_winner_text = str(home_name)

                elif actual_away > actual_home:
                    final_winner_text = str(away_name)

                elif is_knockout:
                    final_winner_text = "Chưa xác định"

                else:
                    final_winner_text = "2 đội hòa nhau"

                winner_caption_html = (
                    '<div style="'
                    'margin-top:14px;'
                    'color:#64748B;'
                    'font-size:13px;'
                    'line-height:1.35;'
                    '">'
                    'Thắng chung cuộc: '
                    '<span style="'
                    'color:#475569;'
                    'font-weight:750;'
                    '">'
                    f'{html.escape(final_winner_text)}'
                    '</span>'
                    '</div>'
                )

                st.markdown(
                    winner_caption_html,
                    unsafe_allow_html=True
                )

            else:
                render_match_status_box(status_info)

        if is_unknown_team(home_name) or is_unknown_team(away_name):
            st.info("Chưa xác định đủ đội, tạm thời chưa mở dự đoán.")
            render_match_venue_footer(row, match_id)
            return

        if existing:
            pred_home = int(existing["predicted_home_score"])
            pred_away = int(existing["predicted_away_score"])
            pred_winner_team_id = to_optional_int(existing.get("predicted_winner_team_id"))
            current_star_type = normalize_star_type(existing.get("star_type"))

            knockout_winner_note = ""

            if is_knockout and pred_home == pred_away:
                if pred_winner_team_id == home_team_id:
                    knockout_winner_note = f" ({home_name} thắng chung cuộc)"

                elif pred_winner_team_id == away_team_id:
                    knockout_winner_note = f" ({away_name} thắng chung cuộc)"

                else:
                    knockout_winner_note = " (chưa chọn đội thắng chung cuộc)"

            st.markdown(
                f"Dự đoán hiện tại của bạn: "
                f"**{home_name} {pred_home} - {pred_away} {away_name}{knockout_winner_note}**"
            )

            if current_star_type != STAR_TYPE_NONE:
                st.markdown(f"Bổ trợ: **{format_star_short(current_star_type)}**")
            else:
                st.caption("Bổ trợ: Không dùng sao")

            actual_home_for_result = to_optional_int(row.get("home_score_for_prediction"))
            actual_away_for_result = to_optional_int(row.get("away_score_for_prediction"))

            prediction_result_info = get_prediction_result_info(
                pred_home=pred_home,
                pred_away=pred_away,
                actual_home=actual_home_for_result,
                actual_away=actual_away_for_result,
                is_finished=is_finished,
                is_knockout=is_knockout,
                predicted_winner_team_id=pred_winner_team_id,
                actual_winner_team_id=row.get("winner_team_id")
            )

            render_prediction_result_and_score_row(
                result_info=prediction_result_info,
                existing=existing,
                match_row=row
            )

        else:
            pred_home = 0
            pred_away = 0
            pred_winner_team_id = None
            current_star_type = STAR_TYPE_NONE
            st.caption("Bạn chưa dự đoán trận này.")

        if not editable:
            render_match_venue_footer(row, match_id)
            return

        with st.form(f"prediction_form_{match_id}"):
            col_home, col_mid, col_away = st.columns([2, 1, 2])

            with col_home:
                input_home = st.number_input(
                    home_name,
                    min_value=0,
                    max_value=20,
                    value=pred_home,
                    step=1,
                    key=f"home_score_{match_id}"
                )

            with col_away:
                input_away = st.number_input(
                    away_name,
                    min_value=0,
                    max_value=20,
                    value=pred_away,
                    step=1,
                    key=f"away_score_{match_id}"
                )

            predicted_winner_team_id = None
            predicted_winner_team_name = None

            if is_knockout:
                winner_options = {
                    home_name: home_team_id,
                    away_name: away_team_id
                }

                winner_option_names = list(winner_options.keys())

                if input_home > input_away:
                    default_index = 0
                    winner_radio_key = f"winner_{match_id}_auto_home"

                elif input_away > input_home:
                    default_index = 1
                    winner_radio_key = f"winner_{match_id}_auto_away"

                else:
                    default_index = 0
                    winner_radio_key = f"winner_{match_id}_draw"

                    if pred_winner_team_id == away_team_id:
                        default_index = 1

                with stylable_container(
                    key=f"winner_radio_style_shell_{match_id}",
                    css_styles=get_prediction_radio_css()
                ):
                    selected_winner_name = st.radio(
                        "Nếu dự đoán hòa trong thời gian thi đấu chính thức (tính cả hiệp phụ), chọn đội thắng chung cuộc:",
                        options=winner_option_names,
                        index=default_index,
                        horizontal=True,
                        key=winner_radio_key
                    )

                if input_home > input_away:
                    predicted_winner_team_id = home_team_id
                    predicted_winner_team_name = home_name

                elif input_away > input_home:
                    predicted_winner_team_id = away_team_id
                    predicted_winner_team_name = away_name

                else:
                    predicted_winner_team_id = winner_options[selected_winner_name]
                    predicted_winner_team_name = selected_winner_name

            # Dùng cho HIỂN THỊ label:
            # Không exclude match hiện tại để "Đang dùng" tính cả sao đang gắn
            # ở chính trận này nếu trận đó chưa khóa.
            star_usage_for_display = get_user_star_usage(
                user_id=user_id,
                exclude_match_id=None
            )

            # Dùng cho LOGIC quota khi lưu/cập nhật:
            # Exclude match hiện tại để không tự tính trùng sao đang sửa.
            star_usage_for_quota = get_user_star_usage(
                user_id=user_id,
                exclude_match_id=match_id
            )

            # HIỂN THỊ:
            # Kho còn lại = tổng sao - sao đã khóa/mất.
            # Sao đang dùng ở trận chưa khóa vẫn nằm trong kho này.
            hope_display_left = int(star_usage_for_display.get("hope_left", 0))
            super_display_left = int(star_usage_for_display.get("super_left", 0))

            # Đang dùng = sao đang giữ tạm ở các trận chưa khóa.
            hope_display_using = int(
                star_usage_for_display.get("hope_reserved_used", 0)
            )
            super_display_using = int(
                star_usage_for_display.get("super_reserved_used", 0)
            )

            # QUOTA:
            # Dùng để disable option khi đã hết thật.
            # Vẫn dựa trên dữ liệu đã exclude match hiện tại.
            hope_left_for_quota = int(
                star_usage_for_quota.get("hope_left", 0)
            )
            super_left_for_quota = int(
                star_usage_for_quota.get("super_left", 0)
            )

            star_options = [
                STAR_TYPE_NONE,
                STAR_TYPE_HOPE,
                STAR_TYPE_SUPER
            ]

            star_radio_index = (
                star_options.index(current_star_type)
                if current_star_type in star_options
                else 0
            )

            star_radio_key = f"star_type_{match_id}_{current_star_type}"

            disable_hope_option = (
                hope_left_for_quota <= 0
                and current_star_type != STAR_TYPE_HOPE
            )

            disable_super_option = (
                super_left_for_quota <= 0
                and current_star_type != STAR_TYPE_SUPER
            )

            star_radio_shell_class = f'div[class*="st-key-star_radio_style_shell_{match_id}"]'
            star_radio_css = get_prediction_radio_css()

            if disable_hope_option:
                star_radio_css += f"""
                {star_radio_shell_class} label[data-baseweb="radio"]:nth-of-type(2) {{
                    opacity: 0.46 !important;
                    pointer-events: none !important;
                    color: #94A3B8 !important;
                    background: transparent !important;
                    border-color: transparent !important;
                    box-shadow: none !important;
                }}

                {star_radio_shell_class} label[data-baseweb="radio"]:nth-of-type(2) * {{
                    color: #94A3B8 !important;
                }}

                {star_radio_shell_class} label[data-baseweb="radio"]:nth-of-type(2) > div:first-child {{
                    border-color: #CBD5E1 !important;
                    background: #F8FAFC !important;
                    box-shadow: none !important;
                }}

                {star_radio_shell_class} label[data-baseweb="radio"]:nth-of-type(2):hover {{
                    background: transparent !important;
                    border-color: transparent !important;
                    box-shadow: none !important;
                }}

                {star_radio_shell_class} label[data-baseweb="radio"]:nth-of-type(2):hover > div:first-child {{
                    border-color: #CBD5E1 !important;
                    background: #F8FAFC !important;
                    box-shadow: none !important;
                }}
                """

            if disable_super_option:
                star_radio_css += f"""
                {star_radio_shell_class} label[data-baseweb="radio"]:nth-of-type(3) {{
                    opacity: 0.46 !important;
                    pointer-events: none !important;
                    color: #94A3B8 !important;
                    background: transparent !important;
                    border-color: transparent !important;
                    box-shadow: none !important;
                }}

                {star_radio_shell_class} label[data-baseweb="radio"]:nth-of-type(3) * {{
                    color: #94A3B8 !important;
                }}

                {star_radio_shell_class} label[data-baseweb="radio"]:nth-of-type(3) > div:first-child {{
                    border-color: #CBD5E1 !important;
                    background: #F8FAFC !important;
                    box-shadow: none !important;
                }}

                {star_radio_shell_class} label[data-baseweb="radio"]:nth-of-type(3):hover {{
                    background: transparent !important;
                    border-color: transparent !important;
                    box-shadow: none !important;
                }}

                {star_radio_shell_class} label[data-baseweb="radio"]:nth-of-type(3):hover > div:first-child {{
                    border-color: #CBD5E1 !important;
                    background: #F8FAFC !important;
                    box-shadow: none !important;
                }}
                """

            def format_star_option_label_for_card(star_type):
                star_type = normalize_star_type(star_type)

                if star_type == STAR_TYPE_NONE:
                    return "Không dùng sao"

                if star_type == STAR_TYPE_HOPE:
                    hope_label = STAR_CONFIG[STAR_TYPE_HOPE]["label"]

                    if (
                        hope_left_for_quota <= 0
                        and current_star_type != STAR_TYPE_HOPE
                    ):
                        return f"{hope_label} (đã hết)"

                    return (
                        f"{hope_label} "
                        f"(Kho còn lại: {hope_display_left}/{HOPE_STARS_PER_USER}; "
                        f"Đang dùng: {hope_display_using}/{HOPE_STARS_PER_USER})"
                    )

                if star_type == STAR_TYPE_SUPER:
                    super_label = STAR_CONFIG[STAR_TYPE_SUPER]["label"]

                    if (
                        super_left_for_quota <= 0
                        and current_star_type != STAR_TYPE_SUPER
                    ):
                        return f"{super_label} (đã hết)"

                    return (
                        f"{super_label} "
                        f"(Kho còn lại: {super_display_left}/{SUPER_STARS_PER_USER}; "
                        f"Đang dùng: {super_display_using}/{SUPER_STARS_PER_USER})"
                    )

                return STAR_CONFIG[star_type]["label"]

            with stylable_container(
                key=f"star_radio_style_shell_{match_id}",
                css_styles=star_radio_css
            ):
                selected_star_type = st.radio(
                    "Chọn bổ trợ cho trận này:",
                    options=star_options,
                    index=star_radio_index,
                    format_func=format_star_option_label_for_card,
                    horizontal=False,
                    key=star_radio_key
                )

            submitted = False
            delete_submitted = False

            if existing:
                with stylable_container(
                    key=f"prediction_action_spacing_shell_{match_id}",
                    css_styles=get_prediction_action_spacing_css()
                ):
                    save_col, spacer_col, delete_col = st.columns([1.45, 6.8, 0.85])

                    with save_col:
                        submitted = st.form_submit_button(
                            "Cập nhật dự đoán"
                        )

                    with delete_col:
                        with stylable_container(
                            key=f"delete_prediction_button_shell_{match_id}",
                            css_styles="""
                            button {
                                width: 100% !important;
                                background: rgba(255, 255, 255, 0.66) !important;
                                color: #DC2626 !important;
                                border: 1px solid rgba(220, 38, 38, 0.38) !important;
                                box-shadow: none !important;
                                font-size: 12px !important;
                                font-weight: 750 !important;
                                padding: 5px 9px !important;
                                min-height: 32px !important;
                                border-radius: 999px !important;
                                white-space: nowrap !important;
                            }

                            button:hover {
                                color: #B91C1C !important;
                                border-color: rgba(185, 28, 28, 0.68) !important;
                                background: rgba(254, 226, 226, 0.46) !important;
                                transform: none !important;
                                box-shadow: none !important;
                            }

                            button:active {
                                transform: none !important;
                                box-shadow: none !important;
                            }
                            """
                        ):
                            delete_submitted = st.form_submit_button(
                                "Xóa dự đoán",
                                help="Xóa dự đoán đã lưu cho trận này."
                            )

            else:
                with stylable_container(
                    key=f"prediction_action_spacing_shell_{match_id}",
                    css_styles=get_prediction_action_spacing_css()
                ):
                    submitted = st.form_submit_button(
                        "Lưu dự đoán"
                    )

            if submitted:
                try:
                    selected_star_type = normalize_star_type(selected_star_type)

                    should_save_directly = True

                    if (
                        selected_star_type != STAR_TYPE_NONE
                        and selected_star_type != current_star_type
                    ):
                        latest_usage = get_user_star_usage_from_db(
                            user_id=user_id,
                            exclude_match_id=match_id
                        )

                        if selected_star_type == STAR_TYPE_HOPE:
                            latest_left = int(latest_usage.get("hope_left", 0))
                            latest_free_left = int(
                                latest_usage.get("hope_free_left", latest_left)
                            )
                            star_display_name = "Ngôi sao hy vọng"

                        elif selected_star_type == STAR_TYPE_SUPER:
                            latest_left = int(latest_usage.get("super_left", 0))
                            latest_free_left = int(
                                latest_usage.get("super_free_left", latest_left)
                            )
                            star_display_name = "Siêu sao"

                        else:
                            latest_left = 0
                            latest_free_left = 0
                            star_display_name = "bổ trợ"

                        if latest_left <= 0:
                            should_save_directly = False
                            st.error(f"Bạn đã dùng hết {star_display_name}.")

                        elif latest_free_left <= 0:
                            should_save_directly = False

                            transfer_candidates = load_transfer_candidates_for_card(
                                selected_star_type
                            )

                            if not transfer_candidates:
                                st.error(
                                    f"Hiện không còn {star_display_name} trống để dùng cho trận này."
                                )
                            else:
                                st.session_state["pending_star_transfer"] = {
                                    "target_match_id": match_id,
                                    "target_label": f"{home_name} vs {away_name}",
                                    "predicted_home_score": int(input_home),
                                    "predicted_away_score": int(input_away),
                                    "predicted_winner_team_id": predicted_winner_team_id,
                                    "star_type": selected_star_type,
                                    "candidates": transfer_candidates
                                }

                                st.rerun()

                    if should_save_directly:
                        save_prediction(
                            user_id=user_id,
                            match_id=match_id,
                            predicted_home_score=int(input_home),
                            predicted_away_score=int(input_away),
                            predicted_winner_team_id=predicted_winner_team_id,
                            star_type=selected_star_type
                        )

                        st.session_state.pop("pending_star_transfer", None)

                        st.success(
                            "Đã lưu dự đoán. Bạn vẫn có thể cập nhật dự đoán cho đến trước giờ bóng lăn."
                        )
                        st.rerun()

                except ValueError as e:
                    st.error(str(e))

            if delete_submitted:
                try:
                    delete_prediction(
                        user_id=user_id,
                        match_id=match_id
                    )

                    st.session_state.pop("pending_star_transfer", None)

                    st.success("Đã xóa dự đoán.")
                    st.rerun()

                except ValueError as e:
                    st.error(str(e))

        render_match_venue_footer(row, match_id)

# ============================================================
# 10. PAGES
# ============================================================

def page_matches():
    render_app_hero()

    render_page_title(
        "Lịch thi đấu & dự đoán",
        "Cuộn xuống dưới để xem lịch thi đấu và nhập dự đoán cho từng trận."
    )

    matches = load_matches()

    if matches.empty:
        st.warning("Chưa có dữ liệu trận đấu.")
        return

    render_kpi_tiles(matches)

    user_id = st.session_state["user"]["user_id"]
    success_message = st.session_state.pop(
        "star_transfer_success_message",
        None
    )
    
    if success_message:
        st.success(success_message)
    
    if st.session_state.get("pending_star_transfer"):
        render_star_transfer_dialog(user_id)
    
    if st.session_state.get("ai_summary_match_id"):
        render_ai_match_summary_dialog(
            int(st.session_state["ai_summary_match_id"])
        )
    
    render_star_balance(user_id)
    render_scoring_rules()

    available_dates = sorted(matches["kickoff_date_filter"].dropna().unique())

    today_vn = today_vietnam_date()
    tomorrow_vn = tomorrow_vietnam_date()

    date_options_set = set(available_dates)
    date_options_set.add(today_vn)
    date_options_set.add(tomorrow_vn)

    date_options = sorted(date_options_set)

    if "filter_date" not in st.session_state:
        st.session_state["filter_date"] = today_vn

    if "filter_status" not in st.session_state:
        st.session_state["filter_status"] = "Tất cả"

    if "filter_prediction_status" not in st.session_state:
        st.session_state["filter_prediction_status"] = "Tất cả"

    status_options = [
        "Tất cả",
        "Sắp diễn ra",
        "Đã khóa",
        "Đã có kết quả"
    ]

    prediction_status_options = [
        "Tất cả",
        "Đã dự đoán",
        "Chưa dự đoán"
    ]

    if st.session_state["filter_date"] not in date_options:
        st.session_state["filter_date"] = today_vn

    if st.session_state["filter_status"] not in status_options:
        st.session_state["filter_status"] = "Tất cả"

    if st.session_state["filter_prediction_status"] not in prediction_status_options:
        st.session_state["filter_prediction_status"] = "Tất cả"

    with stylable_container(
        key="match_filter_panel",
        css_styles="""
        {
            background:
                linear-gradient(
                    135deg,
                    rgba(255,255,255,0.97) 0%,
                    rgba(248,250,252,0.97) 72%,
                    rgba(7,17,31,0.04) 100%
                );
            border: 1px solid rgba(15,23,42,0.08);
            border-left: 5px solid #07111F;
            border-radius: 22px;
            padding: 16px 24px 16px 24px;
            box-shadow: 0 16px 40px rgba(15,23,42,0.10);
            margin: 8px 0 28px 0;
            width: 100%;
            box-sizing: border-box;
        }

        div[data-testid="stSelectbox"] {
            margin-bottom: 0 !important;
        }

        div[data-testid="stSelectbox"] label {
            color: #334155 !important;
            font-weight: 850 !important;
            font-size: 13px !important;
            margin-bottom: 6px !important;
        }

        div[data-baseweb="select"] > div {
            background: rgba(248,250,252,0.95) !important;
            border: 1px solid rgba(15,23,42,0.10) !important;
            border-radius: 14px !important;
            min-height: 44px !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.70);
        }

        div[data-baseweb="select"] > div:hover {
            border-color: rgba(7,17,31,0.55) !important;
        }
        """
    ):
        st.markdown(
            """
            <div style="
                color: #07111F;
                font-weight: 950;
                font-size: 16px;
                line-height: 1.2;
                margin-bottom: 18px;
            ">
                Bộ lọc
            </div>
            """,
            unsafe_allow_html=True
        )

        col_filter_1, col_filter_2, col_filter_3 = st.columns([1, 1, 1])

        with col_filter_1:
            selected_date = st.selectbox(
                "Ngày thi đấu",
                options=date_options,
                index=date_options.index(st.session_state["filter_date"]),
                format_func=format_filter_date,
                key="filter_date"
            )

        with col_filter_2:
            status_filter = st.selectbox(
                "Trạng thái",
                options=status_options,
                index=status_options.index(st.session_state["filter_status"]),
                key="filter_status"
            )

        with col_filter_3:
            prediction_status_filter = st.selectbox(
                "Tình trạng dự đoán",
                options=prediction_status_options,
                index=prediction_status_options.index(
                    st.session_state["filter_prediction_status"]
                ),
                key="filter_prediction_status"
            )

    filtered = matches.copy()

    filtered = filtered[
        filtered["kickoff_date_filter"] == selected_date
    ]

    now_utc = pd.Timestamp.now(tz="UTC")

    if status_filter == "Sắp diễn ra":
        filtered = filtered[
            (filtered["kickoff_time_utc_dt"] > now_utc)
            & (~filtered["is_finished"].apply(to_bool))
        ]

    elif status_filter == "Đã khóa":
        filtered = filtered[
            (filtered["kickoff_time_utc_dt"] <= now_utc)
            & (~filtered["is_finished"].apply(to_bool))
        ]

    elif status_filter == "Đã có kết quả":
        filtered = filtered[
            filtered["is_finished"].apply(to_bool)
        ]

    user_predictions = load_predictions()
    user_prediction_map = build_user_prediction_map(
        predictions=user_predictions,
        user_id=user_id
    )
    
    predicted_match_ids = set(user_prediction_map.keys())

    if prediction_status_filter == "Đã dự đoán":
        filtered = filtered[
            filtered["match_id"].astype(int).isin(predicted_match_ids)
        ]

    elif prediction_status_filter == "Chưa dự đoán":
        filtered = filtered[
            ~filtered["match_id"].astype(int).isin(predicted_match_ids)
        ]

    filtered = filtered.sort_values("kickoff_time_utc_dt")

    if filtered.empty:
        st.info("Không có trận nào phù hợp với bộ lọc hiện tại.")
        return

    for match_date, group_df in filtered.groupby("kickoff_date_filter"):
        st.markdown("---")
        st.header(format_filter_date(match_date))

        group_df = group_df.sort_values("kickoff_time_utc_dt")

        for _, row in group_df.iterrows():
            render_match_card(
                row,
                user_id,
                user_prediction_map=user_prediction_map
            )


def page_my_predictions():
    render_page_title(
        "Dự đoán của tôi",
        "Theo dõi toàn bộ dự đoán đã lưu và điểm số từng trận."
    )

    score_all_predictions()

    user_id = st.session_state["user"]["user_id"]

    matches = load_matches()
    predictions = load_predictions()

    if predictions.empty:
        st.info("Bạn chưa có dự đoán nào.")
        return

    my_predictions = predictions[predictions["user_id"] == user_id].copy()

    if my_predictions.empty:
        st.info("Bạn chưa có dự đoán nào.")
        return

    df = my_predictions.merge(
        matches,
        on="match_id",
        how="left"
    )

    df = df.sort_values("kickoff_time_utc_dt")

    display_df = pd.DataFrame({
        "Ngày": df.get("kickoff_date_display_vietnam", df.get("kickoff_date_vietnam")),
        "Giờ": df.get("kickoff_time_vietnam"),
        "Vòng": df.get("round_name"),
        "Trận": df["home_team_name"] + " vs " + df["away_team_name"],
        "Dự đoán": (
            df["predicted_home_score"].astype(str)
            + " - "
            + df["predicted_away_score"].astype(str)
        ),
        "Bổ trợ": df["star_type"].apply(format_star_short),
        "Kết quả": df.apply(
            lambda row: (
                ""
                if pd.isna(row.get("home_score_for_prediction"))
                or pd.isna(row.get("away_score_for_prediction"))
                else f"{int(row['home_score_for_prediction'])} - {int(row['away_score_for_prediction'])}"
            ),
            axis=1
        ),
        "Điểm gốc": df["base_points"].apply(
            lambda x: "" if pd.isna(x) else str(int(round(float(x))))
        ),
        "Thưởng sao": df["star_bonus_points"].apply(
            lambda x: "" if pd.isna(x) else str(int(round(float(x))))
        ),
        "Điểm": df["points"].apply(
            lambda x: "" if pd.isna(x) else str(int(round(float(x))))
        )
    })

    leaderboard = build_leaderboard_df()

    current_user_summary = leaderboard[
        leaderboard["user_id"].astype(int) == int(user_id)
    ]

    if current_user_summary.empty:
        total_points = int(
            pd.to_numeric(df["points"], errors="coerce").fillna(0).sum()
        )
        current_rank = "-"
    else:
        total_points = int(current_user_summary.iloc[0]["total_points"])
        current_rank = int(current_user_summary.iloc[0]["rank"])

    rank_display = "-" if current_rank == "-" else f"#{current_rank}"

    scored_points = pd.to_numeric(df["points"], errors="coerce")
    scored_match_count = int(scored_points.notna().sum())

    if scored_match_count == 0:
        avg_points_per_scored_match = 0.0
    else:
        avg_points_per_scored_match = total_points / scored_match_count

    avg_points_display = f"{avg_points_per_scored_match:.1f}"

    with stylable_container(
        key="my_predictions_table",
        css_styles="""
        {
            background: rgba(255,255,255,0.94);
            border: 1px solid rgba(15,23,42,0.08);
            border-radius: 22px;
            padding: 18px;
            box-shadow: 0 14px 34px rgba(15,23,42,0.08);
        }
        """
    ):
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        summary_col_1, summary_col_2, summary_col_3 = st.columns(3)

        with summary_col_1:
            st.markdown(
                (
                    '<div style="text-align:center;padding:0 0 2px 0;">'
                    '<div style="color:#07111F;font-weight:900;font-size:15px;margin-bottom:8px;">'
                    'Điểm TB/trận'
                    '</div>'
                    f'<div style="color:#F5C542;font-weight:950;font-size:34px;line-height:1;">{avg_points_display}</div>'
                    '</div>'
                ),
                unsafe_allow_html=True
            )

        with summary_col_2:
            st.markdown(
                (
                    '<div style="text-align:center;padding:0 0 2px 0;">'
                    '<div style="color:#07111F;font-weight:900;font-size:15px;margin-bottom:8px;">'
                    'Tổng điểm'
                    '</div>'
                    f'<div style="color:#F5C542;font-weight:950;font-size:34px;line-height:1;">{total_points}</div>'
                    '</div>'
                ),
                unsafe_allow_html=True
            )

        with summary_col_3:
            st.markdown(
                (
                    '<div style="text-align:center;padding:0 0 2px 0;">'
                    '<div style="color:#07111F;font-weight:900;font-size:15px;margin-bottom:8px;">'
                    'Hạng'
                    '</div>'
                    f'<div style="color:#F5C542;font-weight:950;font-size:34px;line-height:1;">{rank_display}</div>'
                    '</div>'
                ),
                unsafe_allow_html=True
            )

        st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

@st.cache_data(ttl=10, show_spinner=False)
def build_leaderboard_df():
    users = load_users()
    predictions = load_predictions()
    matches = load_matches()

    if users.empty:
        return pd.DataFrame()

    if predictions.empty:
        result = users.copy()
        result["total_points"] = 0
        result["base_points"] = 0
        result["star_bonus_points"] = 0
        result["hope_stars_used"] = 0
        result["super_stars_used"] = 0
        result["num_predictions"] = 0
        result["num_scored"] = 0
        result["exact_score_count"] = 0
        result["correct_outcome_count"] = 0
        result["knockout_winner_checkable"] = 0
        result["knockout_winner_correct"] = 0
        result["exact_score_rate"] = 0.0
        result["outcome_rate"] = 0.0
        result["knockout_winner_rate"] = 0.0
        result["result_prediction_checkable"] = 0
        result["result_prediction_correct"] = 0
        result["result_prediction_rate"] = 0.0

        if "avatar_key" not in result.columns:
            result["avatar_key"] = DEFAULT_AVATAR_KEY

        result = result.sort_values("display_name").reset_index(drop=True)
        result["rank"] = range(1, len(result) + 1)

        return result

    df = predictions.merge(users, on="user_id", how="left")
    df = df.merge(matches, on="match_id", how="left")

    if "avatar_key" not in df.columns:
        df["avatar_key"] = DEFAULT_AVATAR_KEY

    metrics = []

    for _, row in df.iterrows():
        pred_home = to_optional_int(row.get("predicted_home_score"))
        pred_away = to_optional_int(row.get("predicted_away_score"))

        actual_home = to_optional_int(row.get("home_score_for_prediction"))
        actual_away = to_optional_int(row.get("away_score_for_prediction"))

        is_scored = (
            pred_home is not None
            and pred_away is not None
            and actual_home is not None
            and actual_away is not None
            and to_bool(row.get("is_finished"))
        )

        exact = False
        correct_outcome = False

        if is_scored:
            exact = pred_home == actual_home and pred_away == actual_away
            correct_outcome = (
                get_outcome(pred_home, pred_away)
                == get_outcome(actual_home, actual_away)
            )

        is_knockout = to_bool(row.get("is_knockout"))

        knockout_winner_checkable = (
            is_scored
            and is_knockout
            and to_optional_int(row.get("winner_team_id")) is not None
        )

        knockout_winner_correct = False

        if knockout_winner_checkable:
            knockout_winner_correct = (
                to_optional_int(row.get("predicted_winner_team_id"))
                == to_optional_int(row.get("winner_team_id"))
            )

        metrics.append({
            "is_scored": is_scored,
            "exact_score": exact,
            "correct_outcome": correct_outcome,
            "knockout_winner_checkable": knockout_winner_checkable,
            "knockout_winner_correct": knockout_winner_correct
        })

    metrics_df = pd.DataFrame(metrics)

    df = pd.concat(
        [
            df.reset_index(drop=True),
            metrics_df.reset_index(drop=True)
        ],
        axis=1
    )

    df["points"] = pd.to_numeric(
        df["points"],
        errors="coerce"
    ).fillna(0)

    df["base_points"] = pd.to_numeric(
        df["base_points"],
        errors="coerce"
    ).fillna(0)

    df["star_bonus_points"] = pd.to_numeric(
        df["star_bonus_points"],
        errors="coerce"
    ).fillna(0)

    df["star_type"] = df["star_type"].apply(normalize_star_type)
    
    # Chỉ tính sao là đã dùng thật khi trận đã khóa dự đoán.
    # Sao đang đặt ở trận chưa diễn ra không bị trừ khỏi kho sao thực tế.
    df["is_star_locked_for_usage"] = df.apply(
        lambda row: is_match_locked_for_star(
            row.get("kickoff_time_utc"),
            row.get("is_finished")
        ),
        axis=1
    )
    
    df["hope_star_used"] = (
        (df["star_type"] == STAR_TYPE_HOPE)
        & df["is_star_locked_for_usage"]
    )
    
    df["super_star_used"] = (
        (df["star_type"] == STAR_TYPE_SUPER)
        & df["is_star_locked_for_usage"]
    )

    summary = (
        df
        .groupby(
            ["user_id", "username", "display_name", "role", "avatar_key"],
            as_index=False
        )
        .agg(
            total_points=("points", "sum"),
            base_points=("base_points", "sum"),
            star_bonus_points=("star_bonus_points", "sum"),
            hope_stars_used=("hope_star_used", "sum"),
            super_stars_used=("super_star_used", "sum"),
            num_predictions=("prediction_id", "count"),
            num_scored=("is_scored", "sum"),
            exact_score_count=("exact_score", "sum"),
            correct_outcome_count=("correct_outcome", "sum"),
            knockout_winner_checkable=("knockout_winner_checkable", "sum"),
            knockout_winner_correct=("knockout_winner_correct", "sum")
        )
    )

    numeric_cols = [
        "total_points",
        "base_points",
        "star_bonus_points",
        "hope_stars_used",
        "super_stars_used",
        "num_predictions",
        "num_scored",
        "exact_score_count",
        "correct_outcome_count",
        "knockout_winner_checkable",
        "knockout_winner_correct"
    ]

    for col in numeric_cols:
        summary[col] = summary[col].fillna(0).astype(int)

    summary["exact_score_rate"] = summary.apply(
        lambda row: row["exact_score_count"] / row["num_scored"]
        if row["num_scored"] else 0,
        axis=1
    )

    summary["result_prediction_checkable"] = (
        summary["num_scored"] + summary["knockout_winner_checkable"]
    )

    summary["result_prediction_correct"] = (
        summary["correct_outcome_count"] + summary["knockout_winner_correct"]
    )

    summary["result_prediction_rate"] = summary.apply(
        lambda row: row["result_prediction_correct"] / row["result_prediction_checkable"]
        if row["result_prediction_checkable"] else 0,
        axis=1
    )

    summary = summary.sort_values(
        ["total_points", "exact_score_count", "correct_outcome_count"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    summary["rank"] = range(1, len(summary) + 1)

    return summary

def page_leaderboard():
    render_page_title(
        "Bảng xếp hạng",
        "Xem ai đang dẫn đầu cuộc đua dự đoán."
    )

    score_all_predictions()

    leaderboard = build_leaderboard_df()

    if leaderboard.empty:
        st.info("Chưa có dữ liệu người chơi.")
        return

    current_display_name = str(st.session_state["user"]["display_name"]).strip()

    if "avatar_key" not in leaderboard.columns:
        leaderboard["avatar_key"] = DEFAULT_AVATAR_KEY

    leaderboard["hope_star_display"] = leaderboard["hope_stars_used"].apply(
        lambda x: f"{max(0, HOPE_STARS_PER_USER - int(x))}/{HOPE_STARS_PER_USER}"
    )

    leaderboard["super_star_display"] = leaderboard["super_stars_used"].apply(
        lambda x: f"{max(0, SUPER_STARS_PER_USER - int(x))}/{SUPER_STARS_PER_USER}"
    )

    display_df = leaderboard[
        [
            "rank",
            "display_name",
            "total_points",
            "base_points",
            "star_bonus_points",
            "hope_star_display",
            "super_star_display",
            "num_predictions",
            "num_scored",
            "exact_score_count",
            "correct_outcome_count",
            "exact_score_rate",
            "result_prediction_rate"
        ]
    ].copy()

    display_df = display_df.rename(columns={
        "rank": "Hạng",
        "display_name": "Người chơi",
        "total_points": "Điểm",
        "base_points": "Điểm gốc",
        "star_bonus_points": "Thưởng sao",
        "hope_star_display": "⭐",
        "super_star_display": "✨",
        "num_predictions": "Số dự đoán",
        "num_scored": "Số trận đã chấm",
        "exact_score_count": "Đúng tỉ số",
        "correct_outcome_count": "Đúng kết quả",
        "exact_score_rate": "% Đúng tỉ số",
        "result_prediction_rate": "% Đúng kết quả"
    })

    percent_cols = [
        "% Đúng tỉ số",
        "% Đúng kết quả"
    ]

    for col in percent_cols:
        display_df[col] = display_df[col].apply(lambda x: f"{x * 100:.1f}%")

    avatar_row_styles = []

    for row_position, avatar_key in enumerate(leaderboard["avatar_key"].tolist(), start=1):
        avatar_src = get_avatar_src(avatar_key)

        if not avatar_src:
            continue

        avatar_row_styles.append(
            {
                "selector": f"tbody tr:nth-child({row_position}) td:nth-child(2)::before",
                "props": [
                    ("content", '""'),
                    ("display", "inline-block"),
                    ("width", "28px"),
                    ("height", "28px"),
                    ("border-radius", "999px"),
                    ("background-image", f'url("{avatar_src}")'),
                    ("background-size", "cover"),
                    ("background-position", "center"),
                    ("background-repeat", "no-repeat"),
                    ("vertical-align", "middle"),
                    ("margin-right", "10px"),
                    ("border", "2px solid #FFFFFF"),
                    ("box-shadow", "0 3px 8px rgba(15,23,42,0.16)")
                ]
            }
        )

    def style_leaderboard_row(row):
        styles = []

        is_current_user = str(row["Người chơi"]).strip() == current_display_name
        rank_value = int(row["Hạng"])

        for col in row.index:
            style = ""

            if is_current_user:
                style += (
                    "background-color: #E0F2FE !important; "
                    "font-weight: 800 !important; "
                )

            if col == "Điểm":
                style += (
                    "font-weight: 1390 !important; "
                    "color: #07111F !important; "
                )

            if col == "Thưởng sao":
                style += (
                    "font-weight: 900 !important; "
                    "color: #B45309 !important; "
                )

            if col in ["⭐", "✨"]:
                style += (
                    "text-align: center !important; "
                    "font-weight: 900 !important; "
                    "color: #78350F !important; "
                )

            if col == "Hạng":
                style += (
                    "font-weight: 950 !important; "
                    "text-align: center !important; "
                )

                if rank_value == 1:
                    style += (
                        "background-color: #F5C542 !important; "
                        "color: #78350F !important; "
                    )

                elif rank_value == 2:
                    style += (
                        "background-color: #CBD5E1 !important; "
                        "color: #334155 !important; "
                    )

                elif rank_value == 3:
                    style += (
                        "background-color: #CD7F32 !important; "
                        "color: #431407 !important; "
                    )

            styles.append(style)

        return styles

    styled_df = (
        display_df
        .style
        .apply(style_leaderboard_row, axis=1)
        .set_properties(
            subset=["Điểm"],
            **{
                "font-weight": "1390 !important",
                "color": "#07111F !important"
            }
        )
        .set_properties(
            subset=["Thưởng sao"],
            **{
                "font-weight": "900 !important",
                "color": "#B45309 !important"
            }
        )
        .set_properties(
            subset=["⭐", "✨"],
            **{
                "text-align": "center !important",
                "font-weight": "900 !important",
                "color": "#78350F !important"
            }
        )
        .set_table_styles(
            [
                {
                    "selector": "thead th",
                    "props": [
                        ("background-color", "#07111F"),
                        ("color", "#F8FAFC"),
                        ("font-weight", "900"),
                        ("text-align", "left"),
                        ("border-bottom", "1px solid rgba(255,255,255,0.16)"),
                        ("padding", "11px 12px")
                    ]
                },
                {
                    "selector": "thead th:nth-child(6)",
                    "props": [
                        ("text-align", "center"),
                        ("font-size", "18px")
                    ]
                },
                {
                    "selector": "thead th:nth-child(7)",
                    "props": [
                        ("text-align", "center"),
                        ("font-size", "18px")
                    ]
                },
                {
                    "selector": "tbody td",
                    "props": [
                        ("border-bottom", "1px solid rgba(15,23,42,0.08)"),
                        ("padding", "10px 12px")
                    ]
                },
                {
                    "selector": "tbody td:nth-child(2)",
                    "props": [
                        ("white-space", "nowrap")
                    ]
                },
                {
                    "selector": "tbody td:nth-child(6)",
                    "props": [
                        ("text-align", "center"),
                        ("font-weight", "900"),
                        ("color", "#78350F")
                    ]
                },
                {
                    "selector": "tbody td:nth-child(7)",
                    "props": [
                        ("text-align", "center"),
                        ("font-weight", "900"),
                        ("color", "#78350F")
                    ]
                },
                {
                    "selector": "table",
                    "props": [
                        ("width", "100%"),
                        ("border-collapse", "collapse"),
                        ("font-size", "14px")
                    ]
                }
            ] + avatar_row_styles
        )
    )

    st.table(styled_df)

def page_dashboard():
    render_page_title(
        "Bảng phân tích tổng quan",
        "Phân tích tổng quan hiệu suất dự đoán, điểm số và độ chính xác của tất cả người chơi."
    )

    score_all_predictions()

    leaderboard = build_leaderboard_df()
    predictions = load_predictions()
    matches = load_matches()

    if leaderboard.empty:
        st.info("Chưa đủ dữ liệu để vẽ dashboard.")
        return

    # =========================
    # KPI calculations
    # =========================
    total_players = len(leaderboard)

    highest_score = int(leaderboard["total_points"].max()) if total_players > 0 else 0

    avg_total_points = (
        float(leaderboard["total_points"].mean())
        if total_players > 0 else 0.0
    )

    scored_points = pd.to_numeric(
        predictions.get("points", pd.Series(dtype="float")),
        errors="coerce"
    )

    scored_prediction_count = int(scored_points.notna().sum())

    if scored_prediction_count == 0:
        avg_points_per_match_all = 0.0
    else:
        avg_points_per_match_all = float(
            scored_points.fillna(0).sum() / scored_prediction_count
        )

    total_result_checkable = int(leaderboard["result_prediction_checkable"].sum())
    total_result_correct = int(leaderboard["result_prediction_correct"].sum())

    if total_result_checkable == 0:
        overall_result_rate = 0.0
    else:
        overall_result_rate = total_result_correct / total_result_checkable

    total_exact_checkable = int(leaderboard["num_scored"].sum())
    total_exact_correct = int(leaderboard["exact_score_count"].sum())

    if total_exact_checkable == 0:
        overall_exact_rate = 0.0
    else:
        overall_exact_rate = total_exact_correct / total_exact_checkable

    # =========================
    # KPI cards: 2 rows x 3 cards
    # =========================
    row1_col1, row1_col2, row1_col3 = st.columns(3)
    row2_col1, row2_col2, row2_col3 = st.columns(3)

    with row1_col1:
        st.metric("Tổng số người chơi", total_players)

    with row1_col2:
        st.metric("Điểm cao nhất", highest_score)

    with row1_col3:
        st.metric("Điểm trung bình", f"{avg_total_points:.1f}")

    with row2_col1:
        st.metric("Điểm trung bình/trận", f"{avg_points_per_match_all:.1f}")

    with row2_col2:
        st.metric("% Đúng kết quả TB", f"{overall_result_rate * 100:.1f}%")

    with row2_col3:
        st.metric("% Đúng tỉ số TB", f"{overall_exact_rate * 100:.1f}%")

    st.markdown("---")

    # =========================
    # Charts
    # =========================
    score_max = int(leaderboard["total_points"].max())

    if score_max <= 0:
        score_max = 1

    custom_score_scale = [
        [0.00, "#DC2626"],   # đỏ
        [0.45, "#2563EB"],   # xanh dương
        [1.00, "#07111F"]    # xanh đậm giống sidebar
    ]

    plotly_chart_config = {
        "displayModeBar": False,
        "displaylogo": False,
        "responsive": True
    }
    
    points_scope = st.radio(
        "Hiển thị biểu đồ điểm",
        options=["Top 10", "Tất cả"],
        index=0,
        horizontal=True,
        key="dashboard_points_scope"
    )
    
    top_points = leaderboard.sort_values(
        ["total_points", "exact_score_count", "correct_outcome_count"],
        ascending=[False, False, False]
    ).copy()
    
    if points_scope == "Top 10":
        top_points = top_points.head(10)
    
    def get_rank_bar_color(rank_value: int) -> str:
        if rank_value == 1:
            return "#F5C542"   # Top 1 - vàng
        if rank_value == 2:
            return "#CBD5E1"   # Top 2 - bạc
        if rank_value == 3:
            return "#CD7F32"   # Top 3 - đồng
        return "#2563EB"       # Người chơi còn lại
    
    def get_rank_name_color(rank_value: int) -> str:
        if rank_value == 1:
            return "#78350F"
        if rank_value == 2:
            return "#334155"
        if rank_value == 3:
            return "#431407"
        return "#334155"
    
    top_points["bar_color"] = top_points["rank"].apply(
        lambda rank: get_rank_bar_color(int(rank))
    )
    
    points_chart_height = max(
        430,
        135 + len(top_points) * 42
    )
    
    points_chart_title = (
        "Top 10 điểm theo người chơi"
        if points_scope == "Top 10"
        else "Tổng điểm theo người chơi"
    )
    
    fig_points = px.bar(
        top_points,
        x="total_points",
        y="display_name",
        orientation="h",
        title=points_chart_title,
        labels={
            "display_name": "Người chơi",
            "total_points": "Điểm"
        },
        text="total_points",
        custom_data=[
            "rank",
            "base_points",
            "star_bonus_points",
            "hope_stars_used",
            "super_stars_used"
        ]
    )
    
    fig_points.update_traces(
        marker_color=top_points["bar_color"].tolist(),
        marker_line_width=0,
        opacity=0.94,
        textposition="outside",
        textfont=dict(
            color="#07111F",
            size=12
        ),
        cliponaxis=False,
        hovertemplate=(
            "<b>#%{customdata[0]} %{y}</b><br>"
            "Tổng điểm = %{x}<br>"
            "Điểm gốc = %{customdata[1]}<br>"
            "Thưởng sao = %{customdata[2]}<br>"
            "⭐ Ngôi sao hy vọng đã dùng = %{customdata[3]}<br>"
            "✨ Siêu sao đã dùng = %{customdata[4]}"
            "<extra></extra>"
        )
    )
    
    fig_points.update_layout(
        height=points_chart_height,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(
            color="#07111F"
        ),
        title=dict(
            font=dict(
                size=17,
                color="#07111F"
            )
        ),
        xaxis_title="Điểm",
        yaxis_title="",
        showlegend=False,
        hovermode="closest",
        dragmode=False,
        bargap=0.28,
        margin=dict(
            l=230,
            r=80,
            t=76,
            b=46
        )
    )
    
    fig_points.update_xaxes(
        showgrid=True,
        gridcolor="rgba(15,23,42,0.08)",
        zeroline=False,
        range=[0, max(1, score_max * 1.16)]
    )
    
    fig_points.update_yaxes(
        showticklabels=False,
        autorange="reversed"
    )
    
    for _, player_row in top_points.iterrows():
        rank_value = int(player_row["rank"])
        player_name = html.escape(str(player_row["display_name"]))
        name_color = get_rank_name_color(rank_value)
    
        fig_points.add_annotation(
            x=0,
            y=player_row["display_name"],
            xref="paper",
            yref="y",
            text=f"<b>#{rank_value} {player_name}</b>",
            showarrow=False,
            xanchor="right",
            xshift=-12,
            align="right",
            font=dict(
                color=name_color,
                size=13
            )
        )
    
    st.caption(
        "Di chuột vào từng thanh để xem chi tiết điểm. Chọn “Tất cả” để xem toàn bộ người chơi và cuộn xuống dưới nếu danh sách dài."
    )
    
    st.plotly_chart(
        fig_points,
        use_container_width=True,
        config=plotly_chart_config
    )

    fig_accuracy = px.scatter(
        leaderboard,
        x="result_prediction_rate",
        y="exact_score_rate",
        size="total_points",
        hover_name="display_name",
        custom_data=[
            "total_points",
            "base_points",
            "star_bonus_points",
            "hope_stars_used",
            "super_stars_used"
        ],
        title="Độ chính xác kết quả vs độ chính xác tỉ số",
        labels={
            "result_prediction_rate": "% Đúng kết quả",
            "exact_score_rate": "% Đúng hoàn toàn tỉ số",
            "total_points": "Điểm"
        },
        color="total_points",
        color_continuous_scale=custom_score_scale,
        range_color=(0, score_max)
    )

    fig_accuracy.update_xaxes(tickformat=".1%")
    fig_accuracy.update_yaxes(tickformat=".1%")

    fig_accuracy.update_traces(
        hovertemplate=(
            "<b>%{hovertext}</b><br>"
            "% Đúng kết quả = %{x:.1%}<br>"
            "% Đúng hoàn toàn tỉ số = %{y:.1%}<br>"
            "Tổng điểm = %{customdata[0]}<br>"
            "Điểm gốc = %{customdata[1]}<br>"
            "Thưởng sao = %{customdata[2]}<br>"
            "⭐ Ngôi sao hy vọng đã dùng = %{customdata[3]}<br>"
            "✨ Siêu sao đã dùng = %{customdata[4]}"
            "<extra></extra>"
        ),
        marker=dict(
            line=dict(
                width=1,
                color="rgba(7,17,31,0.28)"
            )
        ),
        opacity=0.88
    )

    fig_accuracy.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#07111F"),
        coloraxis_colorbar=dict(
            title="Điểm",
            tickfont=dict(color="#64748B")
        )
    )

    fig_accuracy.update_layout(
        dragmode=False
    )
    
    st.plotly_chart(
        fig_accuracy,
        use_container_width=True,
        config=plotly_chart_config
    )


def page_admin():
    render_page_title(
        "Admin",
        "Cập nhật kết quả trận đấu và chấm điểm lại toàn bộ dự đoán."
    )

    user = st.session_state["user"]

    if user["role"] != "admin":
        st.error("Bạn không có quyền truy cập trang này.")
        return

    matches = load_matches()
    users = load_users()
    predictions = load_predictions()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Matches", len(matches))

    with col2:
        st.metric("Users", len(users))

    with col3:
        st.metric("Predictions", len(predictions))

    st.markdown("---")

    with stylable_container(
        key="admin_update_card",
        css_styles="""
        {
            background: rgba(255,255,255,0.94);
            border: 1px solid rgba(15,23,42,0.08);
            border-radius: 22px;
            padding: 20px;
            box-shadow: 0 14px 34px rgba(15,23,42,0.08);
        }
        """
    ):
        st.subheader("Cập nhật kết quả trận đấu")

        if matches.empty:
            st.warning("Chưa có dữ liệu trận đấu.")
            return

        matches = matches.sort_values("kickoff_time_utc_dt")

        matches["match_label"] = matches.apply(
            lambda row: (
                f"#{row['match_id']} | "
                f"{row.get('kickoff_date_display_vietnam', row.get('kickoff_date_vietnam', ''))} "
                f"{row.get('kickoff_time_vietnam', '')} | "
                f"{row['home_team_name']} vs {row['away_team_name']} | "
                f"{row['round_name']}"
            ),
            axis=1
        )

        selected_label = st.selectbox(
            "Chọn trận cần cập nhật kết quả",
            matches["match_label"].tolist()
        )

        selected_match = matches[matches["match_label"] == selected_label].iloc[0]

        match_id = int(selected_match["match_id"])

        home_name = selected_match["home_team_name"]
        away_name = selected_match["away_team_name"]

        home_team_id = to_optional_int(selected_match.get("home_team_id"))
        away_team_id = to_optional_int(selected_match.get("away_team_id"))

        is_knockout = to_bool(selected_match.get("is_knockout"))

        st.markdown(f"### {home_name} vs {away_name}")

        st.caption(
            f"{selected_match.get('round_name')} | "
            f"{selected_match.get('kickoff_date_display_vietnam', selected_match.get('kickoff_date_vietnam', ''))} "
            f"{selected_match.get('kickoff_time_vietnam', '')}"
        )

        current_ft_home = to_optional_int(selected_match.get("score_ft_home"))
        current_ft_away = to_optional_int(selected_match.get("score_ft_away"))

        current_et_home = to_optional_int(selected_match.get("score_et_home"))
        current_et_away = to_optional_int(selected_match.get("score_et_away"))

        current_pen_home = to_optional_int(selected_match.get("score_pen_home"))
        current_pen_away = to_optional_int(selected_match.get("score_pen_away"))

        with st.form("update_match_result_form"):
            st.markdown("#### Tỉ số full-time")

            col_ft_home, col_ft_away = st.columns(2)

            with col_ft_home:
                score_ft_home = st.number_input(
                    f"FT - {home_name}",
                    min_value=0,
                    max_value=30,
                    value=current_ft_home if current_ft_home is not None else 0,
                    step=1
                )

            with col_ft_away:
                score_ft_away = st.number_input(
                    f"FT - {away_name}",
                    min_value=0,
                    max_value=30,
                    value=current_ft_away if current_ft_away is not None else 0,
                    step=1
                )

            score_et_home = None
            score_et_away = None
            score_pen_home = None
            score_pen_away = None
            winner_team_id = None

            if is_knockout:
                st.markdown("#### Knockout options")

                use_extra_time = st.checkbox(
                    "Trận có hiệp phụ",
                    value=current_et_home is not None and current_et_away is not None
                )

                if use_extra_time:
                    col_et_home, col_et_away = st.columns(2)

                    with col_et_home:
                        score_et_home = st.number_input(
                            f"ET - {home_name}",
                            min_value=0,
                            max_value=30,
                            value=current_et_home if current_et_home is not None else int(score_ft_home),
                            step=1
                        )

                    with col_et_away:
                        score_et_away = st.number_input(
                            f"ET - {away_name}",
                            min_value=0,
                            max_value=30,
                            value=current_et_away if current_et_away is not None else int(score_ft_away),
                            step=1
                        )

                final_home_for_game = score_et_home if score_et_home is not None else score_ft_home
                final_away_for_game = score_et_away if score_et_away is not None else score_ft_away

                if final_home_for_game == final_away_for_game:
                    use_penalties = st.checkbox(
                        "Trận phân định bằng penalty",
                        value=current_pen_home is not None and current_pen_away is not None
                    )

                    if use_penalties:
                        col_pen_home, col_pen_away = st.columns(2)

                        with col_pen_home:
                            score_pen_home = st.number_input(
                                f"Penalty - {home_name}",
                                min_value=0,
                                max_value=30,
                                value=current_pen_home if current_pen_home is not None else 0,
                                step=1
                            )

                        with col_pen_away:
                            score_pen_away = st.number_input(
                                f"Penalty - {away_name}",
                                min_value=0,
                                max_value=30,
                                value=current_pen_away if current_pen_away is not None else 0,
                                step=1
                            )

                    winner_options = {
                        home_name: home_team_id,
                        away_name: away_team_id
                    }

                    current_winner_team_id = to_optional_int(selected_match.get("winner_team_id"))
                    default_index = 0

                    if current_winner_team_id == away_team_id:
                        default_index = 1

                    selected_winner = st.radio(
                        "Chọn đội thắng chung cuộc",
                        options=list(winner_options.keys()),
                        index=default_index,
                        horizontal=True
                    )

                    winner_team_id = winner_options[selected_winner]

            submitted = st.form_submit_button("Lưu kết quả và chấm điểm")

            if submitted:
                try:
                    update_match_result(
                        match_id=match_id,
                        score_ft_home=int(score_ft_home),
                        score_ft_away=int(score_ft_away),
                        score_et_home=int(score_et_home) if score_et_home is not None else None,
                        score_et_away=int(score_et_away) if score_et_away is not None else None,
                        score_pen_home=int(score_pen_home) if score_pen_home is not None else None,
                        score_pen_away=int(score_pen_away) if score_pen_away is not None else None,
                        winner_team_id=winner_team_id
                    )

                    st.success("Đã cập nhật kết quả và chấm điểm lại dự đoán.")
                    st.rerun()

                except ValueError as e:
                    st.error(str(e))

    st.markdown("---")

    if st.button("Chấm điểm lại toàn bộ dự đoán", use_container_width=True):
        score_all_predictions()
        st.success("Đã chấm điểm lại toàn bộ dự đoán.")


def render_footer():
    if FOOTER_PROJECT_URL:
        footer_link = f'<a href="{FOOTER_PROJECT_URL}" target="_blank">Project repo / portfolio</a>'
    else:
        footer_link = "World Cup Prediction Arena"

    st.markdown(
        f"""
        <div class="wc-footer">
            © 2026 Prediction Arena. {footer_link}
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# 11. MAIN APP
# ============================================================

def main():
    try:
        initialize_app_once()
    except Exception as e:
        st.error("App không khởi động được ở bước kết nối/khởi tạo database.")
        st.caption(
            "Hãy kiểm tra DATABASE_URL, trạng thái Supabase và log trong Streamlit Cloud."
        )
        st.exception(e)
        st.stop()

    try:
        restore_user_from_cookie()
    except Exception:
        # Không để lỗi cookie làm sập app.
        st.session_state.pop("user", None)

    # Nếu chưa đăng nhập, hiển thị trang đăng nhập.
    # Sau khi đăng nhập thành công, render_auth_page() sẽ set st.session_state["user"].
    # Khi đó app không stop nữa mà render tiếp màn hình chính trong cùng lượt chạy.
    if "user" not in st.session_state:
        render_auth_page()

        if "user" not in st.session_state:
            render_footer()
            st.stop()

    user = st.session_state["user"]

    render_avatar_popover(user)

    with st.sidebar:
        render_sidebar_brand()

        st.markdown(f"Xin chào, **{user['display_name']}**")
        st.caption(f"Role: {user['role']}")
        render_sidebar_star_balance(user["user_id"])

        if st.button("Đăng xuất", use_container_width=True):
            logout_user()

        st.markdown("---")

        pages = [
            "Lịch thi đấu & dự đoán",
            "Dự đoán của tôi",
            "Bảng xếp hạng",
            "Phân tích tổng quan"
        ]

        if user["role"] == "admin":
            pages.append("Admin")

        avatar_restore_page = st.session_state.pop(
            "_selected_page_after_avatar_change",
            None
        )
        
        if avatar_restore_page in pages:
            st.session_state["selected_page"] = avatar_restore_page
        
        if "selected_page" not in st.session_state:
            st.session_state["selected_page"] = "Lịch thi đấu & dự đoán"
        
        if st.session_state["selected_page"] not in pages:
            st.session_state["selected_page"] = "Lịch thi đấu & dự đoán"
        
        selected_page = st.radio(
            "Menu",
            pages,
            key="selected_page"
        )

        render_sidebar_footer()

    if selected_page == "Lịch thi đấu & dự đoán":
        page_matches()

    elif selected_page == "Dự đoán của tôi":
        page_my_predictions()

    elif selected_page == "Bảng xếp hạng":
        page_leaderboard()

    elif selected_page == "Phân tích tổng quan":
        page_dashboard()

    elif selected_page == "Admin":
        page_admin()

    render_footer()

if __name__ == "__main__":
    main()
