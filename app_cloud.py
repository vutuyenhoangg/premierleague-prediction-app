# ============================================================
# EPL PREDICTION ARENA
# Safe refactor: duplicate overwritten helper definitions removed; runtime behavior intentionally preserved.
# Stack: Streamlit + Supabase/PostgreSQL
# Database input: Supabase via DATABASE_URL
# ============================================================

import streamlit.components.v1 as components
import html
import json
import os
import logging
import threading
import hmac
import hashlib
import base64
import mimetypes
from sqlalchemy import create_engine, text
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    OperationalError,
    TimeoutError as SQLAlchemyTimeoutError
)
from sqlalchemy.engine import Engine
from pathlib import Path
from datetime import datetime, timezone, timedelta, date
import pandas as pd
import streamlit as st
from streamlit_extras.stylable_container import stylable_container
import secrets
from streamlit_cookies_controller import CookieController
import re
import textwrap

LOGGER = logging.getLogger("epl_prediction_arena")

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

APP_NAME = "EPL Prediction Arena"
APP_SHORT_NAME = "EPL 2026/27"
APP_SEASON_LABEL = "2026/27"
DEFAULT_SEASON_SLUG = "2026-27"
SEASON_OPTIONS = [
    {
        "slug": "2026-27",
        "label": "2026/27",
        "title": "Mùa giải 2026/27",
        "subtitle": "Mùa giải hiện tại",
        "badge": "Mặc định"
    },
    {
        "slug": "2025-26",
        "label": "2025/26",
        "title": "Mùa giải 2025/26",
        "subtitle": "Dữ liệu mùa trước",
        "badge": "Lưu trữ"
    }
]
SEASON_LABEL_BY_SLUG = {
    season["slug"]: season["label"]
    for season in SEASON_OPTIONS
}
SEASON_TITLE_BY_SLUG = {
    season["slug"]: season["title"]
    for season in SEASON_OPTIONS
}
APP_TAGLINE = "Dự đoán tỉ số Ngoại hạng Anh, tích điểm và tranh tài cùng bạn bè."
COOKIE_NAME = "epl_session_token"
SESSION_DAYS = 30
DISPLAY_NAME_CHANGE_COOLDOWN_DAYS = 30
DISPLAY_NAME_MAX_LENGTH = 50
HOPE_STARS_PER_USER = 5
SUPER_STARS_PER_USER = 1

NORMAL_MATCH_EXACT_POINTS = 3
NORMAL_MATCH_OUTCOME_POINTS = 1

BIG_MATCH_EXACT_POINTS = 4
BIG_MATCH_OUTCOME_POINTS = 2

ROUND_CHAMPION_BONUS_POINTS = 5
EPL_MATCHES_PER_ROUND = 10
LEADERBOARD_PAGE_SIZE = 10

CHECKIN_CYCLE_DAYS = 7
CHECKIN_HOPE_REWARD_DAY = 5
CHECKIN_SUPER_REWARD_DAY = 7
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME = st.secrets.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")
ENABLE_FINAL_POSTER = False
ENABLE_AI_FEATURES = True
AI_SUGGESTION_MAX_DAYS = 3

NEWS_TICKER_ENABLED = True

# Ticker quá thời gian này sẽ tự ẩn.
NEWS_TICKER_MAX_AGE_HOURS = 48

# Streamlit kiểm tra dữ liệu mới sau mỗi 2 phút.
NEWS_TICKER_REFRESH_INTERVAL = "2m"

MOBILE_TEAM_NAME_OVERRIDES = {
    "arsenal fc": "Arsenal",
    "aston villa fc": "Aston Villa",
    "afc bournemouth": "Bournemouth",
    "bournemouth afc": "Bournemouth",
    "brighton & hove albion": "Brighton",
    "brighton & hove albion fc": "Brighton",
    "brighton and hove albion": "Brighton",
    "brighton and hove albion fc": "Brighton",
    "brentford fc": "Brentford",
    "burnley fc": "Burnley",
    "chelsea fc": "Chelsea",
    "coventry city": "Coventry",
    "coventry city fc": "Coventry",
    "crystal palace fc": "Crystal Palace",
    "everton fc": "Everton",
    "fulham fc": "Fulham",
    "hull city": "Hull City",
    "hull city afc": "Hull City",
    "ipswich town": "Ipswich",
    "ipswich town fc": "Ipswich",
    "leeds united": "Leeds",
    "leeds united fc": "Leeds",
    "leicester city": "Leicester",
    "leicester city fc": "Leicester",
    "liverpool fc": "Liverpool",
    "luton town": "Luton",
    "luton town fc": "Luton",
    "manchester city": "Man City",
    "manchester city fc": "Man City",
    "manchester united": "Man United",
    "manchester united fc": "Man United",
    "newcastle united": "Newcastle",
    "newcastle united fc": "Newcastle",
    "norwich city": "Norwich",
    "norwich city fc": "Norwich",
    "nottingham forest": "Nottingham Forest",
    "nottingham forest fc": "Nottingham Forest",
    "sheffield united": "Sheffield Utd",
    "sheffield united fc": "Sheffield Utd",
    "southampton fc": "Southampton",
    "sunderland afc": "Sunderland",
    "tottenham hotspur": "Tottenham",
    "tottenham hotspur fc": "Tottenham",
    "watford fc": "Watford",
    "west bromwich albion": "West Brom",
    "west bromwich albion fc": "West Brom",
    "west ham united": "West Ham",
    "west ham united fc": "West Ham",
    "wolverhampton wanderers": "Wolves",
    "wolverhampton wanderers fc": "Wolves",
}

AVATAR_FOLDER = "data/static/avatars"
DEFAULT_AVATAR_KEY = "avatar_01.png"
AVATAR_EXTENSIONS = {".png"}
# Avatar lớn nhất hiển thị 82px; 168px đủ sắc nét cho màn hình HiDPI 2x
# nhưng nhẹ hơn đáng kể so với việc giữ bản 192px cho cả 80 ảnh.
AVATAR_RENDER_SIZE_PX = 168
# Kho chọn avatar dùng một sprite WebP chung thay vì 80 ảnh Base64 riêng.
# Kích thước 128px vẫn lớn hơn ảnh hiển thị tối đa 82px và giảm đáng kể
# RAM, kích thước WebSocket delta và thời gian dựng DOM.
AVATAR_SPRITE_CELL_PX = 128
AVATAR_SPRITE_COLUMNS = 8
AVATAR_ORDER = [
    "avatar_01.png",
    "avatar_02.png",
    "avatar_03.png",
    "avatar_04.png",
    "avatar_05.png",
    "avatar_06.png",
    "avatar_07.png",
    "avatar_08.png",
    "avatar_09.png",
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
    "avatar_30.png",
    "avatar_31.png",
    "avatar_32.png",
    "avatar_33.png",
    "avatar_34.png",
    "avatar_35.png",
    "avatar_36.png",
    "avatar_37.png",
    "avatar_38.png",
    "avatar_39.png",
    "avatar_40.png",
    "avatar_41.png",
    "avatar_42.png",
    "avatar_43.png",
    "avatar_44.png",
    "avatar_45.png",
    "avatar_46.png",
    "avatar_47.png",
    "avatar_48.png",
    "avatar_49.png",
    "avatar_50.png",
    "avatar_51.png",
    "avatar_52.png",
    "avatar_53.png",
    "avatar_54.png",
    "avatar_55.png",
    "avatar_56.png",
    "avatar_57.png",
    "avatar_58.png",
    "avatar_59.png",
    "avatar_60.png",
    "avatar_61.png",
    "avatar_62.png",
    "avatar_63.png",
    "avatar_64.png",
    "avatar_65.png",
    "avatar_66.png",
    "avatar_67.png",
    "avatar_68.png",
    "avatar_69.png",
    "avatar_70.png",
    "avatar_71.png",
    "avatar_72.png",
    "avatar_73.png",
    "avatar_74.png",
    "avatar_75.png",
    "avatar_76.png",
    "avatar_77.png",
    "avatar_78.png",
    "avatar_79.png",
    "avatar_80.png"
]

STAR_TYPE_NONE = "none"
STAR_TYPE_HOPE = "hope"
STAR_TYPE_SUPER = "super"

STAR_CONFIG = {
    STAR_TYPE_NONE: {
        "label": "Không dùng sao",
        "short_label": "Không dùng sao",
        "multiplier": 1,
        "wrong_penalty_normal": 0,
        "wrong_penalty_big": 0
    },
    STAR_TYPE_HOPE: {
        "label": "⭐ Ngôi sao hy vọng x2",
        "short_label": "⭐ Ngôi sao hy vọng",
        "multiplier": 2,
        "wrong_penalty_normal": -1,
        "wrong_penalty_big": -2
    },
    STAR_TYPE_SUPER: {
        "label": "✨ Siêu sao x3",
        "short_label": "✨ Siêu sao",
        "multiplier": 3,
        "wrong_penalty_normal": -2,
        "wrong_penalty_big": -4
    }
}

# ============================================================
# TODO LINK AREA
# ============================================================

APP_LOGO_URL = "data/static/epl-prediction-arena.png"

HERO_BACKGROUND_URL = "data/static/epl-banner.png"

HERO_TROPHY_IMAGE_URL = "data/static/logo-epl.png"

SIDEBAR_DECORATION_URL = "data/static/epl-sidebar.png"

FINAL_POSTER_IMAGE_URL = ""

FINAL_BACKGROUND_IMAGE_URL = ""

EPL_MATCH_BACKGROUND_IMAGE_URL = "data/static/epl-match-background.png"

FINAL_POSTER_END_DATE = date(2026, 7, 20)

FOOTER_PROJECT_URL = ""

@st.cache_resource(show_spinner=False, max_entries=128)
def resolve_asset_src(asset_path: str) -> str:
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


def get_selected_season_slug() -> str:
    selected = st.session_state.get(
        "selected_season_slug",
        DEFAULT_SEASON_SLUG
    )

    valid_slugs = {
        season["slug"]
        for season in SEASON_OPTIONS
    }

    if selected not in valid_slugs:
        selected = DEFAULT_SEASON_SLUG
        st.session_state["selected_season_slug"] = selected

    return selected


def get_selected_season_label() -> str:
    return SEASON_LABEL_BY_SLUG.get(
        get_selected_season_slug(),
        APP_SEASON_LABEL
    )


def get_selected_season_title() -> str:
    return SEASON_TITLE_BY_SLUG.get(
        get_selected_season_slug(),
        f"Mùa giải {get_selected_season_label()}"
    )


def set_selected_season(season_slug: str):
    if st.session_state.get("selected_season_slug") == season_slug:
        return

    st.session_state["selected_season_slug"] = season_slug

    for key in [
        "filter_date",
        "filter_status",
        "filter_prediction_status",
        "pending_star_transfer",
        "ai_summary_match_id",
        "ai_suggestion_match_id"
    ]:
        st.session_state.pop(key, None)

    # Mọi cache dữ liệu đều có season_slug trong cache key.
    # Không xóa cache của cả hai mùa khi đổi bộ lọc; nhờ vậy quay lại mùa
    # vừa xem không phải tải lại toàn bộ matches/predictions từ database.


def render_season_selector():
    selected_slug = get_selected_season_slug()

    # Luôn xếp mùa mới nhất lên trước.
    season_options = sorted(
        SEASON_OPTIONS,
        key=lambda season: season["slug"],
        reverse=True
    )

    active_key = selected_slug.replace("-", "_")
    first_key = season_options[0]["slug"].replace("-", "_")
    last_key = season_options[-1]["slug"].replace("-", "_")

    season_selector_css = """
    <style>
    /* =========================================================
       KHUNG CHỌN MÙA GIẢI
       Toàn bộ CSS được giới hạn trong season_selector_shell.
       ========================================================= */

    div[class*="st-key-season_selector_shell"] {
        width: min(600px, 100%) !important;
        max-width: 600px !important;
    
        height: 82px !important;
        min-height: 82px !important;
    
        margin: 0 0 14px 0 !important;
        padding: 0 18px 0 16px !important;
    
        box-sizing: border-box !important;
    
        display: flex !important;
        flex-direction: column !important;
        justify-content: center !important;
    
        background:
            linear-gradient(
                135deg,
                rgba(255, 255, 255, 0.98) 0%,
                rgba(252, 250, 255, 0.96) 100%
            ) !important;
    
        border: 1px solid rgba(79, 38, 133, 0.24) !important;
        border-left: 4px solid #A100FF !important;
        border-radius: 14px !important;
    
        box-shadow:
            0 10px 28px rgba(35, 14, 65, 0.08),
            inset 0 1px 0 rgba(255, 255, 255, 0.92) !important;
    }

    /*
     * Hỗ trợ cả cấu trúc DOM Streamlit cũ và mới.
     * Wrapper của container phải chiếm đủ chiều ngang.
     */
    div[class*="st-key-season_selector_shell"]
    > :is(
        div[data-testid="stVerticalBlock"],
        div[data-testid="stVerticalBlockBorderWrapper"]
    ) {
        width: 100% !important;
        margin: 0 !important;
    }
    
    div[class*="st-key-season_selector_shell"]
    > div[data-testid="stVerticalBlock"],
    div[class*="st-key-season_selector_shell"]
    > div[data-testid="stVerticalBlockBorderWrapper"]
    > div[data-testid="stVerticalBlock"] {
        width: 100% !important;
        margin: 0 !important;
        gap: 0 !important;
    }
    
    /* Loại bỏ khoảng lệch do wrapper của từng Streamlit element. */
    div[class*="st-key-season_selector_shell"]
    div[data-testid="stElementContainer"] {
        margin-top: 0 !important;
        margin-bottom: 0 !important;
    }
    
    /* Căn icon, chữ, mũi tên và các nút trên cùng một trục giữa. */
    div[class*="st-key-season_selector_shell"]
    div[data-testid="stHorizontalBlock"] {
        width: 100% !important;
        min-height: 44px !important;
    
        margin: 0 !important;
    
        align-items: center !important;
        gap: 0 !important;
    }

    div[class*="st-key-season_selector_shell"]
    div[data-testid="stColumn"],
    div[class*="st-key-season_selector_shell"]
    div[data-testid="column"] {
        min-width: 0 !important;
        padding-left: 0 !important;
        padding-right: 0 !important;
    }

    div[class*="st-key-season_selector_shell"]
    [data-testid="stMarkdownContainer"] p {
        margin: 0 !important;
    }

    /* =========================================================
       PHẦN BIỂU TƯỢNG VÀ THÔNG TIN
       ========================================================= */

    .epl-season-info {
        height: 44px;

        display: flex;
        align-items: center;
        gap: 13px;

        min-width: 0;
    }

    .epl-season-icon {
        width: 44px;
        height: 44px;
        min-width: 44px;

        display: inline-flex;
        align-items: center;
        justify-content: center;

        border-radius: 50%;

        background:
            linear-gradient(
                145deg,
                #5A1A96 0%,
                #321066 100%
            );

        border: 1px solid rgba(255, 255, 255, 0.18);

        box-shadow:
            0 7px 16px rgba(64, 18, 112, 0.22),
            inset 0 1px 0 rgba(255, 255, 255, 0.18);

        color: #FFFFFF;
        flex: 0 0 auto;
    }

    .epl-season-icon svg {
        width: 22px;
        height: 22px;

        fill: none;
        stroke: currentColor;
        stroke-width: 1.8;
        stroke-linecap: round;
        stroke-linejoin: round;
    }

    .epl-season-copy {
        display: flex;
        flex-direction: column;
        justify-content: center;
        gap: 5px;

        min-width: 0;
    }

    .epl-season-heading {
        color: #23132F;
        font-size: 13px;
        font-weight: 950;
        letter-spacing: 0.08em;
        line-height: 1;
        text-transform: uppercase;
        white-space: nowrap;
    }

    .epl-season-subtitle {
        color: #70647D;
        font-size: 13.5px;
        font-weight: 500;
        line-height: 1.2;
        white-space: nowrap;
    }

    /* =========================================================
       DẤU MŨI TÊN
       ========================================================= */

    .epl-season-chevron-wrap {
        height: 44px;

        display: flex;
        align-items: center;
        justify-content: center;
    }

    .epl-season-chevron {
        width: 8px;
        height: 8px;

        border-top: 1.7px solid #8B8096;
        border-right: 1.7px solid #8B8096;

        transform: rotate(45deg);
    }

    /* =========================================================
       SEGMENTED CONTROL
       ========================================================= */

    div[class*="st-key-season_selector_shell"]
    div[class*="st-key-season_switch_"] {
        width: 100% !important;
        min-width: 0 !important;
        margin: 0 !important;
    }

    div[class*="st-key-season_selector_shell"]
    div[class*="st-key-season_switch_"]
    div[data-testid="stButton"] {
        width: 100% !important;
    }

    div[class*="st-key-season_selector_shell"]
    div[class*="st-key-season_switch_"] button {
        position: relative !important;

        width: 100% !important;
        min-width: 0 !important;
        height: 44px !important;
        min-height: 44px !important;

        margin: 0 !important;
        padding: 0 12px !important;

        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;

        border: 1px solid #D9CFE3 !important;
        border-radius: 0 !important;

        background: rgba(255, 255, 255, 0.96) !important;
        color: #4A2B60 !important;

        box-shadow: none !important;

        font-size: 13px !important;
        font-weight: 800 !important;
        line-height: 1 !important;

        opacity: 1 !important;
        overflow: hidden !important;
        transform: none !important;

        transition:
            background 0.16s ease,
            border-color 0.16s ease,
            color 0.16s ease,
            box-shadow 0.16s ease !important;
    }

    div[class*="st-key-season_selector_shell"]
    div[class*="st-key-season_switch_"] button * {
        color: inherit !important;
        font-size: inherit !important;
        font-weight: inherit !important;
        line-height: inherit !important;
        opacity: 1 !important;
    }

    /* Bo góc đầu và cuối của segmented control. */
    div[class*="st-key-season_switch___FIRST_KEY__"] button {
        border-radius: 8px 0 0 8px !important;
    }

    div[class*="st-key-season_switch___LAST_KEY__"] button {
        width: calc(100% + 1px) !important;
        margin-left: -1px !important;
        border-radius: 0 8px 8px 0 !important;
    }

    /* Trạng thái chưa được chọn. */
    div[class*="st-key-season_selector_shell"]
    div[class*="st-key-season_switch_"] button:not(:disabled):hover {
        z-index: 2 !important;

        background: #FAF7FF !important;
        border-color: #8B5CF6 !important;
        color: #32105F !important;

        box-shadow: 0 5px 14px rgba(72, 24, 120, 0.10) !important;
        transform: none !important;
    }

    /* Trạng thái mùa đang được chọn. */
    div[class*="st-key-season_selector_shell"]
    div[class*="st-key-season_switch___ACTIVE_KEY__"] button,
    div[class*="st-key-season_selector_shell"]
    div[class*="st-key-season_switch___ACTIVE_KEY__"] button:disabled {
        z-index: 3 !important;

        background:
            linear-gradient(
                135deg,
                #301060 0%,
                #4B148C 100%
            ) !important;

        border-color: #3A0F70 !important;
        color: #FFFFFF !important;

        opacity: 1 !important;
        cursor: default !important;

        box-shadow:
            0 7px 16px rgba(56, 15, 105, 0.20),
            inset 0 1px 0 rgba(255, 255, 255, 0.14) !important;
    }

    div[class*="st-key-season_selector_shell"]
    div[class*="st-key-season_switch___ACTIVE_KEY__"] button *,
    div[class*="st-key-season_selector_shell"]
    div[class*="st-key-season_switch___ACTIVE_KEY__"] button:disabled * {
        color: #FFFFFF !important;
        opacity: 1 !important;
    }

    /* Vạch vàng dưới mùa đang chọn giống mockup. */
    div[class*="st-key-season_selector_shell"]
    div[class*="st-key-season_switch___ACTIVE_KEY__"] button::after {
        content: "";

        position: absolute;
        left: 29%;
        right: 29%;
        bottom: 0;

        height: 3px;

        border-radius: 3px 3px 0 0;
        background: #F5C542;

        box-shadow: 0 -1px 5px rgba(245, 197, 66, 0.30);
    }

    div[class*="st-key-season_selector_shell"]
    div[class*="st-key-season_switch_"] button:focus-visible {
        z-index: 4 !important;

        outline: 3px solid rgba(161, 0, 255, 0.20) !important;
        outline-offset: 2px !important;
    }

    /* Nâng riêng phần thông tin và mũi tên để căn giữa box trên desktop. */
    @media (min-width: 769px) {
        div[class*="st-key-season_selector_shell"] .epl-season-info,
        div[class*="st-key-season_selector_shell"] .epl-season-chevron-wrap {
            transform: translateY(-8px) !important;
        }
    }

    /* =========================================================
       GIAO DIỆN ĐIỆN THOẠI
       ========================================================= */

    @media (max-width: 768px) {
        div[class*="st-key-season_selector_shell"] {
            width: 100% !important;
            max-width: none !important;
        
            height: 126px !important;
            min-height: 126px !important;
        
            margin-bottom: 14px !important;
            padding: 13px 14px !important;
        
            justify-content: flex-start !important;
        
            border-radius: 13px !important;
        }

        /*
         * Mobile:
         * - Hàng 1: biểu tượng và thông tin
         * - Hàng 2: hai nút mùa giải
         */
        div[class*="st-key-season_selector_shell"]
        div[data-testid="stHorizontalBlock"] {
            display: grid !important;
        
            grid-template-columns:
                repeat(2, minmax(0, 1fr)) !important;
            grid-template-rows: 42px 40px !important;
        
            width: 100% !important;
            height: 98px !important;
            min-height: 98px !important;
        
            column-gap: 0 !important;
            row-gap: 16px !important;
        
            margin: 0 !important;
            align-items: start !important;
        }
        
        div[class*="st-key-season_selector_shell"]
        div[data-testid="stHorizontalBlock"]
        > :is(
            div[data-testid="stColumn"],
            div[data-testid="column"]
        ) {
            width: 100% !important;
            min-width: 0 !important;
        
            margin: 0 !important;
            padding: 0 !important;
        
            flex: unset !important;
            align-self: start !important;
        }
        
        /* Thông tin mùa giải nằm ở hàng đầu tiên. */
        div[class*="st-key-season_selector_shell"]
        div[data-testid="stHorizontalBlock"]
        > :is(
            div[data-testid="stColumn"],
            div[data-testid="column"]
        ):nth-child(1) {
            grid-column: 1 / -1 !important;
            grid-row: 1 !important;
        }
        
        /* Ẩn mũi tên trên điện thoại. */
        div[class*="st-key-season_selector_shell"]
        div[data-testid="stHorizontalBlock"]
        > :is(
            div[data-testid="stColumn"],
            div[data-testid="column"]
        ):nth-child(2) {
            display: none !important;
        }
        
        /* Nút mùa giải mới nằm bên trái hàng thứ hai. */
        div[class*="st-key-season_selector_shell"]
        div[data-testid="stHorizontalBlock"]
        > :is(
            div[data-testid="stColumn"],
            div[data-testid="column"]
        ):nth-child(3) {
            grid-column: 1 !important;
            grid-row: 2 !important;
        }
        
        /* Nút mùa giải cũ nằm bên phải hàng thứ hai. */
        div[class*="st-key-season_selector_shell"]
        div[data-testid="stHorizontalBlock"]
        > :is(
            div[data-testid="stColumn"],
            div[data-testid="column"]
        ):nth-child(4) {
            grid-column: 2 !important;
            grid-row: 2 !important;
        }

        .epl-season-info {
            height: 42px;
            gap: 11px;
        }

        .epl-season-icon {
            width: 42px;
            height: 42px;
            min-width: 42px;
        }

        .epl-season-icon svg {
            width: 21px;
            height: 21px;
        }

        .epl-season-heading {
            font-size: 12.5px;
        }

        .epl-season-subtitle {
            font-size: 12.5px;
            white-space: normal;
        }

        div[class*="st-key-season_selector_shell"]
        div[class*="st-key-season_switch_"] button {
            height: 40px !important;
            min-height: 40px !important;
            font-size: 12.5px !important;
        }
    }
    </style>
    """

    season_selector_css = (
        season_selector_css
        .replace("__ACTIVE_KEY__", active_key)
        .replace("__FIRST_KEY__", first_key)
        .replace("__LAST_KEY__", last_key)
    )

    st.markdown(
        season_selector_css,
        unsafe_allow_html=True
    )

    # Container riêng giúp CSS không tác động đến các nút khác trong app.
    with st.container(key="season_selector_shell"):
        column_spec = (
            [0.50, 0.06]
            + [0.22] * len(season_options)
        )

        selector_columns = st.columns(
            column_spec,
            gap=None
        )

        info_col = selector_columns[0]
        chevron_col = selector_columns[1]
        season_columns = selector_columns[2:]

        with info_col:
            season_info_html = (
                '<div class="epl-season-info">'
                    '<span class="epl-season-icon" aria-hidden="true">'
                        '<svg viewBox="0 0 24 24">'
                            '<rect x="3.5" y="5.5" width="17" height="15" rx="2.5"></rect>'
                            '<path d="M8 3.5V7.5"></path>'
                            '<path d="M16 3.5V7.5"></path>'
                            '<path d="M3.5 9.5H20.5"></path>'
                            '<path d="M8 13H8.01"></path>'
                            '<path d="M12 13H12.01"></path>'
                            '<path d="M16 13H16.01"></path>'
                            '<path d="M8 17H8.01"></path>'
                            '<path d="M12 17H12.01"></path>'
                        '</svg>'
                    '</span>'
                    '<span class="epl-season-copy">'
                        '<span class="epl-season-heading">Mùa giải</span>'
                        '<span class="epl-season-subtitle">'
                            'Chọn mùa giải'
                        '</span>'
                    '</span>'
                '</div>'
            )
        
            st.markdown(
                season_info_html,
                unsafe_allow_html=True
            )

        with chevron_col:
            st.markdown(
                (
                    '<div class="epl-season-chevron-wrap">'
                        '<span class="epl-season-chevron" '
                        'aria-hidden="true"></span>'
                    '</div>'
                ),
                unsafe_allow_html=True
            )

        for col, season in zip(
            season_columns,
            season_options
        ):
            is_active = season["slug"] == selected_slug

            button_key = (
                "season_switch_"
                + season["slug"].replace("-", "_")
            )

            with col:
                if st.button(
                    season["label"],
                    key=button_key,
                    use_container_width=True,
                    disabled=is_active
                ):
                    set_selected_season(season["slug"])
                    st.rerun()

def get_default_filter_date_for_season(available_dates: list[date]) -> date:
    if not available_dates:
        return today_vietnam_date()

    today_vn = today_vietnam_date()

    if today_vn in available_dates:
        return today_vn

    future_dates = [
        match_date
        for match_date in available_dates
        if match_date >= today_vn
    ]

    if future_dates:
        return future_dates[0]

    return available_dates[-1]


st.set_page_config(
    page_title="EPL Prediction Arena",
    page_icon="static/epl-app-icon.png",
    layout="wide",
    initial_sidebar_state="collapsed"
)

def enforce_embed_url():
    """
    Giữ query parameter embed=true nhưng không tạo một iframe JavaScript mới
    ở mọi lượt rerun khi Streamlit hỗ trợ st.query_params.
    """
    query_params_supported = True

    try:
        current_embed_value = st.query_params.get(
            "embed"
        )
    except Exception:
        query_params_supported = False
        current_embed_value = None

    if query_params_supported:
        if str(current_embed_value).lower() != "true":
            try:
                st.query_params["embed"] = "true"
            except Exception:
                query_params_supported = False
            else:
                st.rerun()

        if query_params_supported:
            return

    # Fallback cho Streamlit cũ.
    components.html(
        """
        <script>
        (function() {
            const url = new URL(window.parent.location.href);
            const hasEmbed = url.searchParams.get("embed") === "true";

            if (!hasEmbed) {
                url.searchParams.set("embed", "true");
                window.parent.location.replace(url.toString());
            }
        })();
        </script>
        """,
        height=0,
    )

cookie_controller = CookieController()

def get_avatar_dir() -> Path:
    """
    Xác định đúng thư mục avatar.
    Ưu tiên data/static/avatars.
    """
    primary_dir = BASE_DIR / "data" / "static" / "avatars"
    fallback_dir = BASE_DIR / "static" / "avatars"

    if primary_dir.exists() and primary_dir.is_dir():
        return primary_dir

    if fallback_dir.exists() and fallback_dir.is_dir():
        return fallback_dir

    return primary_dir


@st.cache_resource(ttl=60, show_spinner=False, max_entries=4)
def _load_avatar_keys_cached(avatar_dir_str: str) -> list[str]:
    """
    Cache danh sách avatar trong thời gian ngắn.
    Avatar mới sẽ được nhận sau tối đa 60 giây.
    """
    avatar_dir = Path(avatar_dir_str)

    if not avatar_dir.exists() or not avatar_dir.is_dir():
        return []

    avatar_keys = [
        file_path.name
        for file_path in avatar_dir.iterdir()
        if (
            file_path.is_file()
            and file_path.suffix.lower() in AVATAR_EXTENSIONS
        )
    ]

    available_avatar_keys = set(avatar_keys)

    ordered_avatar_keys = [
        avatar_key
        for avatar_key in AVATAR_ORDER
        if avatar_key in available_avatar_keys
    ]

    ordered_avatar_set = set(ordered_avatar_keys)

    remaining_avatar_keys = sorted(
        avatar_key
        for avatar_key in avatar_keys
        if avatar_key not in ordered_avatar_set
    )

    return ordered_avatar_keys + remaining_avatar_keys


def load_avatar_keys() -> list[str]:
    avatar_dir = get_avatar_dir()
    return _load_avatar_keys_cached(str(avatar_dir))


def normalize_avatar_key(
    avatar_key,
    avatar_keys: list[str] | None = None
) -> str:
    if avatar_keys is None:
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


@st.cache_resource(
    show_spinner=False,
    max_entries=256
)
def _read_avatar_src_cached(
    avatar_path_str: str,
    modified_time_ns: int,
    file_size: int,
    render_size_px: int
) -> str:
    """
    modified_time_ns và file_size là cache version.
    Khi nội dung ảnh thay đổi, Streamlit tự đọc lại ảnh.

    Chỉ giữ bản ảnh đã thu nhỏ đúng nhu cầu hiển thị trong RAM/cache.
    Avatar lớn vẫn giữ nguyên trên ổ đĩa, nhưng không còn bị nhúng nguyên
    kích thước vào UI ở mỗi card chọn avatar.
    """
    avatar_path = Path(avatar_path_str)

    if not avatar_path.exists() or not avatar_path.is_file():
        return ""

    try:
        from io import BytesIO
        from PIL import Image, ImageOps

        with Image.open(avatar_path) as source_image:
            avatar_image = ImageOps.exif_transpose(source_image)
            avatar_image.thumbnail(
                (render_size_px, render_size_px),
                Image.Resampling.LANCZOS,
                reducing_gap=3.0
            )

            if avatar_image.mode not in {"RGB", "RGBA"}:
                avatar_image = avatar_image.convert(
                    "RGBA" if "transparency" in avatar_image.info else "RGB"
                )

            output_buffer = BytesIO()
            avatar_image.save(
                output_buffer,
                format="WEBP",
                quality=88,
                lossless=False,
                method=4
            )

        encoded = base64.b64encode(
            output_buffer.getvalue()
        ).decode("ascii")

        return f"data:image/webp;base64,{encoded}"

    except Exception:
        # Fallback tương thích nếu môi trường thiếu codec WebP/Pillow.
        mime_type, _ = mimetypes.guess_type(str(avatar_path))
        mime_type = mime_type or "image/png"

        encoded = base64.b64encode(
            avatar_path.read_bytes()
        ).decode("ascii")

        return f"data:{mime_type};base64,{encoded}"


def get_avatar_src(
    avatar_key: str,
    avatar_keys: list[str] | None = None
) -> str:
    avatar_key = normalize_avatar_key(
        avatar_key,
        avatar_keys=avatar_keys
    )

    if not avatar_key:
        return ""

    avatar_path = get_avatar_dir() / avatar_key

    if not avatar_path.exists() or not avatar_path.is_file():
        return ""

    file_stat = avatar_path.stat()

    return _read_avatar_src_cached(
        str(avatar_path),
        file_stat.st_mtime_ns,
        file_stat.st_size,
        AVATAR_RENDER_SIZE_PX
    )


def get_avatar_button_key(avatar_key: str) -> str:
    """
    Tạo widget key ổn định cho từng avatar.
    """
    safe_avatar_key = (
        str(avatar_key)
        .replace(".", "_")
        .replace("-", "_")
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    return f"avatar_pick_{safe_avatar_key}"


def load_avatar_catalog() -> tuple[str, ...]:
    """
    Catalog nhẹ chỉ chứa tên file.

    Bản cũ giữ đồng thời 80 chuỗi Base64 riêng trong RAM và gửi lại toàn bộ
    chuỗi đó ở mỗi rerun. Ảnh của catalog giờ được gộp thành một sprite chung.
    """
    return tuple(load_avatar_keys())


@st.cache_resource(show_spinner=False, max_entries=2)
def build_avatar_sprite_payload() -> tuple[str, int, int]:
    """
    Tạo một sprite WebP dùng chung cho toàn bộ avatar.

    Trả về:
    - data URI của sprite;
    - số cột;
    - số hàng.

    Hàm chạy một lần cho mỗi app process. Khi deploy bộ ảnh mới, process mới
    sẽ tự tạo sprite mới; không giữ 80 ảnh Base64 độc lập trong cache.
    """
    avatar_keys = load_avatar_catalog()

    if not avatar_keys:
        return "", AVATAR_SPRITE_COLUMNS, 0

    try:
        from io import BytesIO
        from PIL import Image, ImageOps

        columns = min(
            AVATAR_SPRITE_COLUMNS,
            len(avatar_keys)
        )
        rows = (
            len(avatar_keys)
            + columns
            - 1
        ) // columns

        sprite = Image.new(
            "RGB",
            (
                columns * AVATAR_SPRITE_CELL_PX,
                rows * AVATAR_SPRITE_CELL_PX
            ),
            color=(255, 255, 255)
        )

        avatar_dir = get_avatar_dir()

        for index, avatar_key in enumerate(avatar_keys):
            avatar_path = avatar_dir / avatar_key

            if not avatar_path.exists() or not avatar_path.is_file():
                continue

            with Image.open(avatar_path) as source_image:
                avatar_image = ImageOps.exif_transpose(
                    source_image
                ).convert("RGB")

                avatar_image = ImageOps.fit(
                    avatar_image,
                    (
                        AVATAR_SPRITE_CELL_PX,
                        AVATAR_SPRITE_CELL_PX
                    ),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5)
                )

                column_index = index % columns
                row_index = index // columns

                sprite.paste(
                    avatar_image,
                    (
                        column_index * AVATAR_SPRITE_CELL_PX,
                        row_index * AVATAR_SPRITE_CELL_PX
                    )
                )

        output_buffer = BytesIO()
        output_mime_type = "image/webp"

        try:
            sprite.save(
                output_buffer,
                format="WEBP",
                quality=84,
                lossless=False,
                method=4
            )

        except Exception:
            # Một số bản Pillow không có codec WebP.
            output_buffer = BytesIO()
            output_mime_type = "image/png"
            sprite.save(
                output_buffer,
                format="PNG",
                optimize=True
            )

        encoded = base64.b64encode(
            output_buffer.getvalue()
        ).decode("ascii")

        return (
            f"data:{output_mime_type};base64,{encoded}",
            columns,
            rows
        )

    except Exception:
        # Fallback an toàn: vẫn giữ app hoạt động nếu Pillow/WebP gặp lỗi.
        # Chỉ dùng ảnh hiện tại ở nút avatar; grid sẽ không có ảnh nền thay
        # vì làm sập toàn bộ ứng dụng.
        LOGGER.warning(
            "Could not build avatar sprite; using image fallback.",
            exc_info=True
        )
        return "", AVATAR_SPRITE_COLUMNS, 0


def get_avatar_sprite_position(
    avatar_key: str,
    avatar_keys: tuple[str, ...] | None = None
) -> tuple[float, float] | None:
    """
    Trả về background-position theo phần trăm cho một avatar trong sprite.
    """
    avatar_keys = avatar_keys or load_avatar_catalog()

    if not avatar_keys:
        return None

    normalized_avatar_key = normalize_avatar_key(
        avatar_key,
        avatar_keys=list(avatar_keys)
    )

    try:
        index = avatar_keys.index(normalized_avatar_key)
    except ValueError:
        return None

    _, columns, rows = build_avatar_sprite_payload()

    if columns <= 0 or rows <= 0:
        return None

    column_index = index % columns
    row_index = index // columns

    x_position = (
        0.0
        if columns <= 1
        else column_index * 100.0 / (columns - 1)
    )
    y_position = (
        0.0
        if rows <= 1
        else row_index * 100.0 / (rows - 1)
    )

    return x_position, y_position


@st.cache_resource(show_spinner=False, max_entries=2)
def build_avatar_background_css() -> str:
    """
    Tạo CSS cho grid avatar dạng button từ đúng một sprite Base64.

    Cơ chế tương tác dùng st.button giống dự án World Cup. Sprite chỉ chịu
    trách nhiệm hiển thị ảnh, không tham gia xác định lựa chọn hoặc callback.
    Vì vậy code không còn phụ thuộc vào DOM nội bộ của st.radio/nth-of-type.
    """
    avatar_keys = load_avatar_catalog()
    sprite_src, columns, rows = build_avatar_sprite_payload()

    if not avatar_keys:
        return ""

    sprite_available = bool(
        sprite_src
        and columns > 0
        and rows > 0
    )

    if not sprite_available:
        # Pixel trong suốt; từng avatar sẽ được gắn riêng ở fallback bên dưới.
        sprite_src = (
            "data:image/gif;base64,"
            "R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="
        )
        columns = 1
        rows = 1

    css_parts = [
        """
        :root {
            --epl-avatar-sprite-image:
                url("__AVATAR_SPRITE_SRC__");
        }

        div[class*="st-key-avatar_pick_"] {
            width: 100% !important;
            min-width: 0 !important;
        }

        div[class*="st-key-avatar_pick_"] [data-testid="stButton"] {
            width: 100% !important;
        }

        div[class*="st-key-avatar_pick_"] button {
            position: relative !important;
            width: 100% !important;
            height: 88px !important;
            min-height: 88px !important;
            padding: 0 !important;
            margin: 0 0 8px 0 !important;
            border: 2px solid rgba(15,23,42,0.10) !important;
            border-radius: 18px !important;
            background: #FFFFFF !important;
            box-shadow: 0 8px 20px rgba(15,23,42,0.06) !important;
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
        }

        div[class*="st-key-avatar_pick_"] button:hover {
            border-color: #F5C542 !important;
            background: #FFF7ED !important;
            transform: translateY(-1px) !important;
            box-shadow:
                0 0 0 4px rgba(245,197,66,0.18),
                0 12px 28px rgba(15,23,42,0.13) !important;
        }

        div[class*="st-key-avatar_pick_"] button:active {
            transform: translateY(0) scale(0.98) !important;
        }

        div[class*="st-key-avatar_pick_"] button::before {
            content: "";
            position: absolute;
            left: 50%;
            top: 50%;
            width: 64px;
            height: 64px;
            transform: translate(-50%, -50%);
            border: 3px solid #FFFFFF;
            border-radius: 999px;
            background-image:
                var(--epl-avatar-sprite-image);
            background-size:
                __AVATAR_SPRITE_WIDTH__% __AVATAR_SPRITE_HEIGHT__%;
            background-repeat: no-repeat;
            box-shadow: 0 7px 18px rgba(15,23,42,0.16);
            pointer-events: none;
        }

        div[class*="st-key-avatar_pick_"] button::after {
            content: "✓";
            position: absolute;
            right: 13px;
            bottom: 13px;
            width: 22px;
            height: 22px;
            display: none;
            align-items: center;
            justify-content: center;
            border: 2px solid #FFFFFF;
            border-radius: 999px;
            background: #F5C542;
            color: #07111F;
            font-size: 13px;
            font-weight: 950;
            line-height: 1;
            box-shadow: 0 5px 12px rgba(15,23,42,0.18);
            pointer-events: none;
        }

        div[class*="st-key-avatar_pick_"] button * {
            display: none !important;
            visibility: hidden !important;
            color: transparent !important;
            font-size: 0 !important;
            line-height: 0 !important;
        }

        /*
        Trạng thái avatar đang dùng được gắn trực tiếp vào thuộc tính disabled
        của đúng button. Cách này không phụ thuộc vào thứ tự các thẻ <style>
        sau fragment rerun và không cần đoán DOM bằng nth-of-type.
        */
        div[class*="st-key-avatar_pick_"]:has(button:disabled) {
            opacity: 1 !important;
        }

        div[class*="st-key-avatar_pick_"] button:disabled,
        div[class*="st-key-avatar_pick_"] button:disabled:hover {
            opacity: 1 !important;
            border-color: #F5C542 !important;
            background: #FFF7ED !important;
            transform: none !important;
            box-shadow:
                0 0 0 4px rgba(245,197,66,0.20),
                0 10px 24px rgba(15,23,42,0.10) !important;
            cursor: default !important;
        }

        div[class*="st-key-avatar_pick_"] button:disabled::after {
            content: "✓" !important;
            display: flex !important;
        }

        @media (max-width: 768px) {
            div[class*="st-key-avatar_pick_"] button {
                height: 112px !important;
                min-height: 112px !important;
                margin-bottom: 10px !important;
            }

            div[class*="st-key-avatar_pick_"] button::before {
                width: 82px;
                height: 82px;
            }

            div[class*="st-key-avatar_pick_"] button::after {
                right: 12px;
                bottom: 12px;
            }
        }

        @media (max-width: 390px) {
            div[class*="st-key-avatar_pick_"] button {
                height: 104px !important;
                min-height: 104px !important;
                border-radius: 16px !important;
            }

            div[class*="st-key-avatar_pick_"] button::before {
                width: 76px;
                height: 76px;
            }
        }
        """
        .replace("__AVATAR_SPRITE_SRC__", sprite_src)
        .replace(
            "__AVATAR_SPRITE_WIDTH__",
            str(columns * 100)
        )
        .replace(
            "__AVATAR_SPRITE_HEIGHT__",
            str(rows * 100)
        )
    ]

    for avatar_key in avatar_keys:
        avatar_button_key = get_avatar_button_key(
            avatar_key
        )

        if not sprite_available:
            avatar_src = get_avatar_src(
                avatar_key,
                avatar_keys=list(avatar_keys)
            )

            if avatar_src:
                css_parts.append(
                    f"""
                    .st-key-{avatar_button_key} button::before {{
                        background-image: url("{avatar_src}");
                        background-size: cover;
                        background-position: center;
                    }}
                    """
                )

            continue

        position = get_avatar_sprite_position(
            avatar_key,
            avatar_keys=avatar_keys
        )

        if position is None:
            continue

        x_position, y_position = position

        css_parts.append(
            f"""
            .st-key-{avatar_button_key} button::before {{
                background-position:
                    {x_position:.6f}% {y_position:.6f}%;
            }}
            """
        )

    return (
        "<style>"
        + "\n".join(css_parts)
        + "</style>"
    )


# ============================================================
# 2. THEME + UI HELPERS
# ============================================================

def inject_epl_theme():
    hero_background_src = resolve_asset_src(HERO_BACKGROUND_URL)

    if hero_background_src:
        hero_background_css = f"""
            background-image:
                linear-gradient(
                    90deg,
                    rgba(7, 17, 31, 0.96),
                    rgba(11, 31, 58, 0.88),
                    rgba(18, 60, 105, 0.70)
                ),
                url("{hero_background_src}");
            background-size: cover;
            background-position: center;
        """
    else:
        hero_background_css = """
            background:
                radial-gradient(
                    circle at 12% 18%,
                    rgba(0, 180, 216, 0.32),
                    transparent 24%
                ),
                radial-gradient(
                    circle at 82% 16%,
                    rgba(245, 197, 66, 0.30),
                    transparent 22%
                ),
                linear-gradient(
                    135deg,
                    #07111F 0%,
                    #0B1F3A 52%,
                    #123C69 100%
                );
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
                radial-gradient(
                    circle at top left,
                    rgba(0, 180, 216, 0.14),
                    transparent 28%
                ),
                radial-gradient(
                    circle at top right,
                    rgba(245, 197, 66, 0.18),
                    transparent 24%
                ),
                linear-gradient(
                    180deg,
                    #F8FAFC 0%,
                    #EEF4FA 100%
                );
            color: var(--wc-ink);
        }}

        .block-container {{
            padding-top: 0rem !important;
            padding-bottom: 2.4rem;
            max-width: 1440px;
        }}
        
        @media (max-width: 768px) {{
            .block-container {{
                padding-top: 4rem !important;
            }}
        }}

        section[data-testid="stSidebar"] {{
            background:
                radial-gradient(
                    circle at 30% 15%,
                    rgba(0, 180, 216, 0.20),
                    transparent 24%
                ),
                linear-gradient(
                    180deg,
                    #07111F 0%,
                    #0B1F3A 66%,
                    #04101F 100%
                );
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }}

        section[data-testid="stSidebar"] * {{
            color: #F8FAFC;
        }}

        section[data-testid="stSidebar"] .stRadio > div {{
            gap: 8px;
        }}

        section[data-testid="stSidebar"]
        label[data-baseweb="radio"] {{
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            padding: 10px 12px;
            margin-bottom: 6px;
        }}

        section[data-testid="stSidebar"]
        label[data-baseweb="radio"]:has(input:checked) {{
            background: linear-gradient(
                90deg,
                rgba(245, 197, 66, 0.28),
                rgba(0, 180, 216, 0.14)
            );
            border: 1px solid rgba(245, 197, 66, 0.66);
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
                radial-gradient(
                    circle at 32% 28%,
                    #F5C542 0%,
                    #F5C542 22%,
                    transparent 23%
                ),
                linear-gradient(
                    135deg,
                    #123C69,
                    #00B4D8
                );
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
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.10);
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
            border: 1px solid rgba(255, 255, 255, 0.20);
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
            background: radial-gradient(
                circle,
                rgba(245, 197, 66, 0.26),
                transparent 62%
            );
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
            background: rgba(255, 255, 255, 0.10);
            border: 1px solid rgba(255, 255, 255, 0.20);
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
            border: 1px solid rgba(255, 255, 255, 0.18);
            background: rgba(255, 255, 255, 0.08);
            color: #E2E8F0;
            font-size: 13px;
            font-weight: 700;
        }}

        .wc-hero-orb {{
            width: 142px;
            height: 142px;
            border-radius: 36px;
            background:
                radial-gradient(
                    circle at 35% 25%,
                    #FFF7CC,
                    #F5C542 38%,
                    #B45309 100%
                );
            color: #07111F;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 950;
            font-size: 32px;
            box-shadow: 0 18px 38px rgba(245, 197, 66, 0.24);
            transform: rotate(-6deg);
        }}

        .wc-hero-img {{
            width: 270px;
            max-height: 270px;
            object-fit: contain;
            filter: drop-shadow(
                0 16px 32px rgba(0, 0, 0, 0.34)
            );
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
            background: rgba(255, 255, 255, 0.90);
            border: 1px solid rgba(15, 23, 42, 0.08);
            border-radius: 22px;
            padding: 18px;
            box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
            margin-bottom: 18px;
        }}

        .wc-section-card {{
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid rgba(15, 23, 42, 0.08);
            border-radius: 22px;
            padding: 18px;
            box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
            margin-bottom: 18px;
        }}

        .wc-kpi-grid {{
            display: grid;
            grid-template-columns: repeat(
                4,
                minmax(0, 1fr)
            );
            gap: 14px;
            margin-bottom: 18px;
        }}

        .wc-kpi-tile {{
            border-radius: 20px;
            padding: 16px 17px;
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid rgba(15, 23, 42, 0.08);
            box-shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
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
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid rgba(15, 23, 42, 0.08);
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
            background: rgba(255, 255, 255, 0.76);
            border: 1px solid rgba(15, 23, 42, 0.08);
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

        /*
         * Chỉ style đúng nút Đăng xuất bằng key riêng.
         * Không dùng selector vị trí như :first-of-type vì có thể bắt nhầm
         * các nút hệ thống của Streamlit trên vùng header.
         */
        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_logout_button"],
        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_logout_button"] .stButton {{
            width: 100% !important;
        }}

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_logout_button"]
        .stButton > button {{
            width: 100% !important;
            min-height: 40px !important;
            padding: 0 16px !important;
            background: rgba(255, 255, 255, 0.96) !important;
            color: #07111F !important;
            border: 1px solid rgba(245, 197, 66, 0.35) !important;
            border-radius: 12px !important;
            box-shadow: none !important;
            white-space: nowrap !important;
        }}

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_logout_button"]
        .stButton > button *,
        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_logout_button"]
        .stButton > button p {{
            color: #07111F !important;
            white-space: nowrap !important;
        }}

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_logout_button"]
        .stButton > button:hover {{
            background: #F5C542 !important;
            color: #07111F !important;
            border-color: #F5C542 !important;
            transform: none !important;
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

        /* =====================================================
           ẨN BIỂU TƯỢNG ANCHOR CỦA TIÊU ĐỀ STREAMLIT
           ===================================================== */

        [data-testid="stHeaderActionElements"],
        [data-testid="stHeaderActionElements"] *,
        a.anchor-link,
        a[data-testid="stAnchorLink"],
        h1 > a[href^="#"],
        h2 > a[href^="#"],
        h3 > a[href^="#"],
        h4 > a[href^="#"],
        h5 > a[href^="#"],
        h6 > a[href^="#"] {{
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;

            width: 0 !important;
            min-width: 0 !important;
            max-width: 0 !important;

            height: 0 !important;
            min-height: 0 !important;
            max-height: 0 !important;

            margin: 0 !important;
            padding: 0 !important;
            border: none !important;
            overflow: hidden !important;
        }}

        /*
         * Một số phiên bản Streamlit đặt nút anchor
         * bên trong wrapper của heading.
         */
        div[data-testid="stMarkdownContainer"]
        h1 button,

        div[data-testid="stMarkdownContainer"]
        h2 button,

        div[data-testid="stMarkdownContainer"]
        h3 button,

        div[data-testid="stMarkdownContainer"]
        h4 button,

        div[data-testid="stMarkdownContainer"]
        h5 button,

        div[data-testid="stMarkdownContainer"]
        h6 button {{
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
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
                grid-template-columns: repeat(
                    2,
                    minmax(0, 1fr)
                );
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_hide_streamlit_embed_footer_css():
    st.markdown(
        """
        <style>
        footer {
            display: none !important;
            visibility: hidden !important;
            height: 0 !important;
        }

        [data-testid="stFooter"] {
            display: none !important;
            visibility: hidden !important;
            height: 0 !important;
        }

        a[href*="streamlit.app"][target="_blank"],
        a[title*="Fullscreen"],
        a[aria-label*="Fullscreen"],
        button[title*="Fullscreen"],
        button[aria-label*="Fullscreen"] {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
        }

        a[href*="streamlit.io"],
        div:has(> a[href*="streamlit.io"]) {
            display: none !important;
            visibility: hidden !important;
        }

        .stApp {
            padding-bottom: 0 !important;
            margin-bottom: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_match_card_border_animation_css():
    """
    Phần hiệu ứng được đặt trên pseudo-element của card,
    không nằm trong background và không phủ lên giữa card.
    """
    st.markdown(
        """
        <style>
        /*
         * Biến góc được trình duyệt nội suy từ 0deg đến 360deg.
         * Đây là phần tạo chuyển động chạy quanh viền.
         */
        @property --wc-match-card-shimmer-angle {
            syntax: "<angle>";
            initial-value: 0deg;
            inherits: false;
        }

        @keyframes wcMatchCardShimmerClockwise {
            0% {
                --wc-match-card-shimmer-angle: 0deg;
            }

            100% {
                --wc-match-card-shimmer-angle: 360deg;
            }
        }

        /*
         * Chọn trực tiếp container card theo key:
         * match_card_{match_id}
         *
         * Dùng class* thay vì class chính xác để tương thích
         * với cả các phiên bản Streamlit/stylable_container khác nhau.
         */
        div[class*="st-key-match_card_"] {
            position: relative !important;
            isolation: isolate !important;
        }

        /*
         * Vệt sáng riêng biệt nằm trên đúng vùng đường viền.
         */
        div[class*="st-key-match_card_"]::before {
            content: "";

            position: absolute !important;
            inset: -1px !important;

            border-radius: 21px !important;
            padding: 3px !important;

            pointer-events: none !important;
            z-index: 50 !important;

            /*
             * Card ngoài 3 trạng thái chính có opacity = 0.
             */
            opacity: var(
                --wc-match-card-shimmer-opacity,
                0
            ) !important;

            /*
             * Chỉ một đoạn rất nhỏ của conic-gradient có màu.
             * Phần còn lại hoàn toàn trong suốt.
             *
             * Khi biến góc quay, đoạn sáng sẽ chạy theo
             * chiều kim đồng hồ quanh card.
             */
            background:
                conic-gradient(
                    from var(--wc-match-card-shimmer-angle),

                    transparent 0deg,
                    transparent 326deg,

                    rgba(255, 255, 255, 0.00) 330deg,

                    var(
                        --wc-match-card-shimmer-soft,
                        rgba(255, 255, 255, 0.45)
                    ) 334deg,

                    rgba(255, 255, 255, 0.92) 338deg,

                    #FFFFFF 341deg,

                    #FFFFFF 344deg,

                    var(
                        --wc-match-card-shimmer-color,
                        #FFFFFF
                    ) 348deg,

                    rgba(255, 255, 255, 0.35) 352deg,

                    transparent 356deg,
                    transparent 360deg
                ) !important;

            /*
             * Hai lớp mask loại bỏ toàn bộ phần giữa.
             * Chỉ giữ lại một vòng viền dày 3px.
             */
            -webkit-mask:
                linear-gradient(#000 0 0) content-box,
                linear-gradient(#000 0 0) !important;

            -webkit-mask-composite: xor !important;

            mask:
                linear-gradient(#000 0 0) content-box,
                linear-gradient(#000 0 0) !important;

            mask-composite: exclude !important;

            /*
             * Ánh sáng lan nhẹ quanh đầu vệt sáng,
             * tạo cảm giác lấp lánh như hình minh họa.
             */
            filter:
                drop-shadow(
                    0 0 2px
                    rgba(255, 255, 255, 1)
                )
                drop-shadow(
                    0 0 5px
                    var(
                        --wc-match-card-shimmer-color,
                        #FFFFFF
                    )
                )
                drop-shadow(
                    0 0 10px
                    var(
                        --wc-match-card-shimmer-soft,
                        rgba(255, 255, 255, 0.50)
                    )
                ) !important;

            animation:
                wcMatchCardShimmerClockwise
                var(--wc-match-card-shimmer-speed, 4.2s)
                linear
                infinite !important;

            will-change:
                --wc-match-card-shimmer-angle;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_epl_premium_match_card_css():
    """
    CSS dùng chung cho phong cách Premier League cao cấp.

    Hàm này chỉ thay đổi trình bày:
    - Match title
    - Băng rôn Premier League
    - Khoảng cách và typography bên trong card
    - Responsive desktop/mobile

    Không đụng đến dữ liệu, prediction, AI, sao hoặc kết quả.
    """
    st.markdown(
        """
        <style>
        div[class*="st-key-match_card_"] {
            isolation: isolate !important;
        }

        div[class*="st-key-match_card_"]
        > div {
            position: relative;
            z-index: 2;
        }

        div[class*="st-key-match_title_desktop_"] h3 {
            margin:
                0 0 8px 0 !important;

            color:
                #190021 !important;

            font-size:
                clamp(24px, 2.15vw, 32px) !important;

            font-weight:
                950 !important;

            line-height:
                1.08 !important;

            letter-spacing:
                -0.042em !important;

            text-shadow:
                0 1px 0 rgba(255, 255, 255, 0.82);
        }

        div[class*="st-key-match_title_desktop_"] h3 strong {
            color:
                #37003C !important;
        }

        .epl-premier-league-ribbon {
            position: relative;

            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 11px;

            min-width: 250px;
            min-height: 34px;

            padding:
                7px 24px 8px 24px;

            margin:
                0 0 13px 0;

            border-radius:
                7px 7px 11px 11px;

            background:
                linear-gradient(
                    135deg,
                    #24002A 0%,
                    #37003C 44%,
                    #5B0F63 100%
                );

            border:
                1px solid rgba(232, 201, 106, 0.68);

            box-shadow:
                0 9px 20px rgba(55, 0, 60, 0.20),
                inset 0 1px 0 rgba(255, 255, 255, 0.14);

            color:
                #FFF9E8;

            overflow:
                hidden;

            box-sizing:
                border-box;
        }

        .epl-premier-league-ribbon::before {
            content: "";

            position: absolute;
            left: 0;
            right: 0;
            top: 0;

            height: 2px;

            background:
                linear-gradient(
                    90deg,
                    transparent,
                    #FF2882 24%,
                    #00FF85 76%,
                    transparent
                );
        }

        .epl-premier-league-ribbon::after {
            content: "";

            position: absolute;
            left: 50%;
            bottom: -9px;

            width: 34px;
            height: 18px;

            transform:
                translateX(-50%)
                rotate(45deg);

            background:
                #37003C;

            border-right:
                1px solid rgba(232, 201, 106, 0.55);

            border-bottom:
                1px solid rgba(232, 201, 106, 0.55);

            z-index:
                -1;
        }

        .epl-premier-league-ribbon-text {
            color:
                #FFF9E8;

            font-size:
                12px;

            font-weight:
                950;

            line-height:
                1;

            letter-spacing:
                0.13em;

            text-transform:
                uppercase;

            white-space:
                nowrap;
        }

        .epl-premier-league-ribbon-diamond {
            color:
                #00FF85;

            font-size:
                8px;

            line-height:
                1;

            filter:
                drop-shadow(
                    0 0 6px rgba(0, 255, 133, 0.42)
                );
        }

        div[class*="st-key-match_card_"]
        div[data-testid="stCaptionContainer"] {
            color:
                #5B4B67 !important;

            font-weight:
                650 !important;
        }

        div[class*="st-key-match_card_"]
        div[data-testid="stCaptionContainer"] p {
            color:
                #5B4B67 !important;
        }

        div[class*="st-key-match_card_"]
        div[data-testid="stNumberInput"] input {
            background:
                rgba(255, 255, 255, 0.88) !important;

            border-color:
                rgba(55, 0, 60, 0.18) !important;
        }

        div[class*="st-key-match_card_"]
        div[data-testid="stNumberInput"]:focus-within {
            box-shadow:
                0 0 0 3px rgba(255, 40, 130, 0.10) !important;
        }

        @media (max-width: 768px) {
            div[class*="st-key-match_title_desktop_"] {
                display:
                    none !important;
            }

            .wc-match-title-mobile {
                margin:
                    2px 0 11px 0 !important;
            }

            .wc-match-title-mobile
            .wc-match-team {
                color:
                    #190021 !important;

                font-weight:
                    950 !important;
            }

            .wc-match-title-mobile
            .wc-match-vs {
                color:
                    #FF2882 !important;

                font-size:
                    15px !important;

                font-weight:
                    950 !important;

                line-height:
                    1.05 !important;

                text-transform:
                    uppercase;
            }

            .wc-match-title-mobile
            .epl-premier-league-ribbon {
                display:
                    inline-flex;

                min-width:
                    210px;

                min-height:
                    31px;

                padding:
                    6px 18px 7px 18px;

                margin:
                    10px 0 8px 0;

                gap:
                    9px;
            }

            .wc-match-title-mobile
            .epl-premier-league-ribbon-text {
                font-size:
                    10.5px;

                letter-spacing:
                    0.11em;
            }

            .wc-match-title-mobile
            .epl-premier-league-ribbon-diamond {
                font-size:
                    7px;
            }
        }

        @media (max-width: 390px) {
            .wc-match-title-mobile
            .epl-premier-league-ribbon {
                min-width:
                    196px;

                padding-left:
                    15px;

                padding-right:
                    15px;
            }
        }

        /* =====================================================
           RIBBON PREMIER LEAGUE GỌN HƠN
           ===================================================== */
        
        .epl-premier-league-ribbon {
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
        
            width: fit-content !important;
            min-width: 0 !important;
            max-width: 100% !important;
            min-height: 30px !important;
        
            padding:
                6px 15px 7px 15px !important;
        
            margin:
                3px 0 8px 0 !important;
        
            gap: 6px !important;
        
            box-sizing: border-box !important;
        
            white-space: nowrap !important;
            overflow: hidden !important;
        }
        
        .epl-premier-league-ribbon-text,
        .epl-premier-league-ribbon-round {
            display: inline-block;
        
            min-width: 0;
        
            color: #FFFFFF;
        
            font-size: 10.5px;
            font-weight: 950;
            line-height: 1;
        
            letter-spacing: 0.075em;
            text-transform: uppercase;
        
            white-space: nowrap;
        }
        
        .epl-premier-league-ribbon-separator {
            display: inline-block;
        
            color: #00FF85;
        
            font-size: 10px;
            font-weight: 950;
            line-height: 1;
        
            flex: 0 0 auto;
        
            text-shadow:
                0 0 7px
                rgba(0, 255, 133, 0.55);
        }
        
        /* Điện thoại */
        @media (max-width: 768px) {
            .wc-match-title-mobile
            .epl-premier-league-ribbon {
                width: fit-content !important;
                min-width: 0 !important;
                max-width: 100% !important;
        
                min-height: 25px !important;
        
                padding:
                    5px 8px 6px 8px !important;
        
                margin:
                    8px 0 6px 0 !important;
        
                gap: 4px !important;
        
                overflow: hidden !important;
            }
        
            .wc-match-title-mobile
            .epl-premier-league-ribbon-text,
        
            .wc-match-title-mobile
            .epl-premier-league-ribbon-round {
                font-size: 8px !important;
                letter-spacing: 0.045em !important;
            }
        
            .wc-match-title-mobile
            .epl-premier-league-ribbon-separator {
                font-size: 7.5px !important;
            }
        }
        
        /* Điện thoại rất nhỏ */
        @media (max-width: 390px) {
            .wc-match-title-mobile
            .epl-premier-league-ribbon {
                width: fit-content !important;
                min-width: 0 !important;
                max-width: 100% !important;
        
                min-height: 24px !important;
        
                padding-left: 7px !important;
                padding-right: 7px !important;
        
                gap: 3px !important;
            }
        
            .wc-match-title-mobile
            .epl-premier-league-ribbon-text,
        
            .wc-match-title-mobile
            .epl-premier-league-ribbon-round {
                font-size: 7.5px !important;
                letter-spacing: 0.035em !important;
            }
        
            .wc-match-title-mobile
            .epl-premier-league-ribbon-separator {
                font-size: 7px !important;
            }
        }
        /* Ngày giờ thi đấu trên tất cả card. */
        div[class*="st-key-match_card_"]
        .epl-match-kickoff {
            display: block;
        
            width: fit-content;
            max-width: 100%;
        
            margin:
                8px 0 13px 0;
        
            color:
                #493653;
        
            font-size:
                15px;
        
            font-weight:
                850;
        
            line-height:
                1.25;
        
            letter-spacing:
                0.005em;
        
            font-variant-numeric:
                tabular-nums;
        
            text-shadow:
                0 1px 0 rgba(255, 255, 255, 0.82);
        }
        
        @media (max-width: 768px) {
            div[class*="st-key-match_card_"]
            .epl-match-kickoff {
                margin:
                    7px 0 12px 0;
        
                font-size:
                    14px;
        
                font-weight:
                    850;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_epl_match_card_background_css():
    """
    Thêm ảnh nền chìm cho toàn bộ card trận đấu.
    Ảnh nằm ở lớp dưới content/nút/input, không làm thay đổi layout.
    """
    match_background_src = resolve_asset_src(EPL_MATCH_BACKGROUND_IMAGE_URL)

    if not match_background_src:
        return

    safe_match_background_src = html.escape(
        match_background_src,
        quote=True
    )

    st.markdown(
        f"""
        <style>
        div[class*="st-key-match_card_"] {{
            position: relative !important;
            overflow: hidden !important;
            isolation: isolate !important;
        }}

        div[class*="st-key-match_card_"]::after {{
            content: "";

            position: absolute !important;
            inset: 0 !important;

            border-radius: inherit !important;

            pointer-events: none !important;
            z-index: 0 !important;

            background-image:
                linear-gradient(
                    135deg,
                    rgba(255, 251, 254, 0.72),
                    rgba(255, 255, 255, 0.58) 46%,
                    rgba(247, 255, 252, 0.72)
                ),
                url("{safe_match_background_src}");

            background-size: cover !important;
            background-position: center center !important;
            background-repeat: no-repeat !important;

            opacity: 0.18 !important;

            filter:
                saturate(0.95)
                contrast(1.04) !important;

            transform: scale(1.02) !important;
        }}

        div[class*="st-key-match_card_"] > div {{
            position: relative !important;
            z-index: 2 !important;
        }}

        @media (max-width: 768px) {{
            div[class*="st-key-match_card_"]::after {{
                opacity: 0.14 !important;
                background-position: center center !important;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_epl_big_match_card_css():
    """
    Giao diện riêng cho Big Match.

    Chỉ thay đổi phong cách hiển thị:
    - Ánh vàng nhẹ trên ảnh background
    - Tiêu đề và chữ VS
    - Ribbon Big Match

    Khung, viền trạng thái, kích thước và bố cục
    kế thừa hoàn toàn từ card thường.
    """
    st.markdown(
        """
        <style>
        /*
         * Các mảng sáng di chuyển lệch nhau,
         * mô phỏng bề mặt lá vàng không hoàn toàn phẳng.
         */
        @keyframes eplGoldLeafTextureDrift {
            0%,
            100% {
                background-position:
                    0 0,
                    0 0,
                    0% 50%;
            }
        
            50% {
                background-position:
                    31px 13px,
                    -23px 9px,
                    100% 50%;
            }
        }
        
        @keyframes eplGoldLeafEdgeSweep {
            0%,
            38% {
                background-position:
                    180% 0;
            }
        
            100% {
                background-position:
                    -80% 0;
            }
        }

        /* =====================================================
           ÁNH VÀNG BACKGROUND BIG MATCH
        
           ::before tiếp tục kế thừa viền trạng thái của card thường.
           ::after tiếp tục sử dụng chính ảnh nền dùng chung,
           chỉ bổ sung sắc vàng nhẹ.
           ===================================================== */
        
        div[class*="st-key-match_card_big_"]::after {
            /*
             * Không khai báo lại background-image.
             * Ảnh nền vẫn được lấy từ
             * inject_epl_match_card_background_css().
             */
            background-color:
                rgba(215, 165, 46, 0.58) !important;
        
            /*
             * CSS nền chung hiện có hai lớp:
             * 1. Linear gradient sáng
             * 2. Ảnh background
             */
            background-blend-mode:
                soft-light,
                soft-light
                !important;
        
            /*
             * Giữ nguyên độ mờ desktop của card thường.
             */
            opacity:
                0.18 !important;
        
            filter:
                sepia(0.26)
                saturate(1.15)
                brightness(1.03)
                contrast(1.02)
                !important;
        
            /*
             * Ánh vàng tập trung nhẹ ở mép và trung tâm,
             * không tạo thêm đường viền ngoài card.
             */
            box-shadow:
                inset 0 0 120px rgba(179, 118, 12, 0.28),
                inset 0 0 36px rgba(255, 244, 194, 0.18)
                !important;
        }

        /* =====================================================
           TIÊU ĐỀ
           ===================================================== */

        div[class*="st-key-match_card_big_"]
        div[class*="st-key-match_title_desktop_"]
        h3 {
            color:
                #230027 !important;

            text-shadow:
                0 1px 0 rgba(255, 255, 255, 0.96),
                0 4px 16px rgba(55, 0, 60, 0.18),
                0 0 22px rgba(232, 201, 106, 0.10)
                !important;
        }

        div[class*="st-key-match_card_big_"]
        div[class*="st-key-match_title_desktop_"]
        h3
        .epl-desktop-vs-only {
            color:
                #B77A16 !important;

            text-shadow:
                0 0 8px rgba(232, 201, 106, 0.48),
                0 1px 0 rgba(255, 255, 255, 0.85)
                !important;
        }

        /* =====================================================
           RIBBON BIG MATCH
           Giữ nguyên vị trí ribbon hiện tại.
           ===================================================== */

        div[class*="st-key-match_card_big_"]
        .epl-big-match-ribbon {
            background:
                radial-gradient(
                    circle at 30% 35%,
                    rgba(255, 226, 126, 0.17) 0 1px,
                    transparent 1.5px
                )
                0 0 / 19px 19px,
        
                linear-gradient(
                    132deg,
                    #120014 0%,
                    #310035 32%,
                    #5B0F49 68%,
                    #27002D 100%
                )
                !important;
        
            border-color:
                #D6A83F !important;
        
            box-shadow:
                0 0 0 1px rgba(255, 240, 175, 0.74),
                0 0 0 2px rgba(113, 65, 7, 0.82),
                0 9px 24px rgba(55, 0, 60, 0.34),
                0 0 18px rgba(222, 177, 67, 0.22),
                inset 0 1px 0 rgba(255, 255, 255, 0.17)
                !important;
        }

        div[class*="st-key-match_card_big_"]
        .epl-big-match-ribbon::before {
            height:
                2px !important;
        
            background:
                linear-gradient(
                    90deg,
                    transparent 0%,
                    #724306 15%,
                    #D8A83D 31%,
                    #FFF5BD 48%,
                    #C48921 64%,
                    #FFF0A2 75%,
                    transparent 100%
                )
                !important;
        
            background-size:
                240% 100% !important;
        
            animation:
                eplGoldLeafEdgeSweep
                4.8s
                ease-in-out
                infinite
                !important;
        }

        div[class*="st-key-match_card_big_"]
        .epl-big-match-ribbon::after {
            background:
                #2B002F !important;

            border-color:
                rgba(255, 226, 138, 0.72) !important;
        }

        div[class*="st-key-match_card_big_"]
        .epl-premier-league-ribbon-text,

        div[class*="st-key-match_card_big_"]
        .epl-premier-league-ribbon-round {
            color:
                #FFF9E8 !important;
        }

        div[class*="st-key-match_card_big_"]
        .epl-premier-league-ribbon-separator {
            color:
                #F2D477 !important;

            text-shadow:
                0 0 8px rgba(242, 212, 119, 0.60)
                !important;
        }

        /* Nhãn vàng nằm ngay trong ribbon cũ. */
        .epl-big-match-label {
            display:
                inline-flex;

            align-items:
                center;

            justify-content:
                center;

            gap:
                5px;

            min-height:
                20px;

            padding:
                4px 8px 5px 8px;

            margin:
                -1px 1px -1px -7px;

            border:
                1px solid rgba(255, 250, 224, 0.84);

            border-radius:
                5px;

            background:
                radial-gradient(
                    circle at 20% 28%,
                    rgba(255, 255, 255, 0.80) 0 1px,
                    transparent 1.7px
                )
                0 0 / 17px 15px,
            
                repeating-linear-gradient(
                    128deg,
                    rgba(102, 57, 5, 0.13) 0 2px,
                    transparent 2px 7px,
                    rgba(255, 250, 210, 0.25) 7px 9px,
                    transparent 9px 15px
                )
                0 0 / 31px 27px,
            
                linear-gradient(
                    112deg,
                    #7D4B08 0%,
                    #D9A93E 14%,
                    #FFF5BA 26%,
                    #B87818 38%,
                    #F0D675 50%,
                    #FFF9D6 61%,
                    #A96810 74%,
                    #E2B74E 87%,
                    #845009 100%
                )
                0 0 / 260% 100%;

            color:
                #2B082F;

            font-size:
                8.5px;

            font-weight:
                950;

            line-height:
                1;

            letter-spacing:
                0.085em;

            white-space:
                nowrap;

            text-transform:
                uppercase;

            box-shadow:
                0 5px 12px rgba(0, 0, 0, 0.22),
                inset 0 1px 0 rgba(255, 255, 255, 0.70);

            animation:
                eplGoldLeafTextureDrift
                8.5s
                ease-in-out
                infinite;
        }

        .epl-big-match-label::before,
        .epl-big-match-label::after {
            content:
                "";

            width:
                4px;

            height:
                4px;

            flex:
                0 0 4px;

            background:
                linear-gradient(
                    135deg,
                    #6E4107 0%,
                    #FFF2A9 47%,
                    #A56810 100%
                );

            transform:
                rotate(45deg);

            box-shadow:
                0 0 5px rgba(255, 224, 121, 0.46);
        }

        /* =====================================================
           MOBILE
           Không thay đổi bố cục hoặc độ mờ ảnh nền.
           ===================================================== */

        @media (max-width: 768px) {
            div[class*="st-key-match_card_big_"]::after {
                /*
                 * Giữ đúng độ mờ background mobile của card thường.
                 */
                opacity:
                    0.14 !important;
            
                background-color:
                    rgba(215, 165, 46, 0.60) !important;
            
                background-blend-mode:
                    soft-light,
                    soft-light
                    !important;
            
                filter:
                    sepia(0.24)
                    saturate(1.13)
                    brightness(1.025)
                    contrast(1.015)
                    !important;
            
                box-shadow:
                    inset 0 0 72px rgba(179, 118, 12, 0.25),
                    inset 0 0 24px rgba(255, 244, 194, 0.16)
                    !important;
            }

            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .wc-match-team {
                color:
                    #230027 !important;

                text-shadow:
                    0 1px 0 rgba(255, 255, 255, 0.94),
                    0 4px 13px rgba(55, 0, 60, 0.15)
                    !important;
            }

            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .wc-match-vs {
                color:
                    #B77A16 !important;

                text-shadow:
                    0 0 8px rgba(232, 201, 106, 0.46)
                    !important;
            }

            /* =====================================================
               RIBBON BIG MATCH — CHỈ DÀNH CHO MOBILE
               Hiển thị: BIG MATCH • EPL • VÒNG ...
               ===================================================== */
            
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-big-match-ribbon {
                display: inline-flex !important;
                align-items: center !important;
                justify-content: flex-start !important;
            
                width: fit-content !important;
                min-width: 0 !important;
                max-width: 100% !important;
                min-height: 24px !important;
            
                padding:
                    4px 6px 5px 6px !important;
            
                margin:
                    8px 0 6px 0 !important;
            
                gap:
                    3px !important;
            
                white-space:
                    nowrap !important;
            
                overflow:
                    hidden !important;
            
                box-sizing:
                    border-box !important;
            }
            
            /* Không cho các thành phần bị ép hoặc chồng lên nhau */
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-big-match-ribbon > span {
                flex:
                    0 0 auto !important;
            
                min-width:
                    0 !important;
            
                white-space:
                    nowrap !important;
            }
            
            /* Nhãn BIG MATCH vàng */
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-big-match-label {
                min-height:
                    16px !important;
            
                padding:
                    3px 5px 4px 5px !important;
            
                margin:
                    -1px 0 -1px -1px !important;
            
                gap:
                    3px !important;
            
                font-size:
                    6.4px !important;
            
                line-height:
                    1 !important;
            
                letter-spacing:
                    0.035em !important;
            }
            
            /* Thu nhỏ hai họa tiết kim cương */
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-big-match-label::before,
            
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-big-match-label::after {
                width:
                    3px !important;
            
                height:
                    3px !important;
            
                flex:
                    0 0 3px !important;
            }
            
            /*
             * Chỉ trên mobile Big Match:
             * thay PREMIER LEAGUE bằng EPL mà không sửa HTML/Python.
             */
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-premier-league-ribbon-text {
                font-size:
                    0 !important;
            
                letter-spacing:
                    0 !important;
            }
            
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-premier-league-ribbon-text::after {
                content:
                    "EPL";
            
                display:
                    inline-block;
            
                color:
                    #FFF9E8;
            
                font-size:
                    7.5px;
            
                font-weight:
                    950;
            
                line-height:
                    1;
            
                letter-spacing:
                    0.06em;
            }
            
            /* Hai dấu phân cách */
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-premier-league-ribbon-separator {
                font-size:
                    6.5px !important;
            
                line-height:
                    1 !important;
            }
            
            /* Phần VÒNG 3 */
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-premier-league-ribbon-round {
                font-size:
                    7.5px !important;
            
                line-height:
                    1 !important;
            
                letter-spacing:
                    0.045em !important;
            }
        }

        @media (max-width: 390px) {
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-big-match-ribbon {
                min-height:
                    23px !important;
        
                padding:
                    3px 5px 4px 5px !important;
        
                gap:
                    2px !important;
            }
        
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-big-match-label {
                min-height:
                    15px !important;
        
                padding:
                    2px 4px 3px 4px !important;
        
                gap:
                    2px !important;
        
                font-size:
                    6px !important;
            }
        
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-premier-league-ribbon-text::after,
        
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-premier-league-ribbon-round {
                font-size:
                    7px !important;
            }
        
            div[class*="st-key-match_card_big_"]
            .wc-match-title-mobile
            .epl-premier-league-ribbon-separator {
                font-size:
                    6px !important;
            }
        }

        @media (prefers-reduced-motion: reduce) {
            div[class*="st-key-match_card_big_"]
            .epl-big-match-ribbon::before,
        
            .epl-big-match-label {
                animation:
                    none !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_main_page_lift_css():
    """
    Loại bỏ diện tích rỗng do các phần tử chèn CSS/JavaScript
    và giữ nội dung tất cả các trang sát phía dưới header.
    """
    st.markdown(
        """
        <style>
        /*
         * Container này chỉ chứa CSS và JavaScript.
         * Đưa nó ra khỏi luồng bố cục để không tạo khoảng trống.
         */
        div[class*="st-key-global_ui_bootstrap"],
        div[class*="st-key-matches_page_ui_bootstrap"] {
            position: absolute !important;

            top: 0 !important;
            left: 0 !important;

            width: 1px !important;
            min-width: 0 !important;
            max-width: 1px !important;

            height: 1px !important;
            min-height: 0 !important;
            max-height: 1px !important;

            margin: 0 !important;
            padding: 0 !important;

            overflow: hidden !important;
        }

        /*
         * Xóa diện tích của wrapper Streamlit bên ngoài.
         */
        div[data-testid="stElementContainer"]:has(
            div[class*="st-key-global_ui_bootstrap"]
        ),
        div[data-testid="stElementContainer"]:has(
            div[class*="st-key-matches_page_ui_bootstrap"]
        ) {
            position: absolute !important;

            top: 0 !important;
            left: 0 !important;

            width: 1px !important;
            min-width: 0 !important;

            height: 1px !important;
            min-height: 0 !important;

            margin: 0 !important;
            padding: 0 !important;

            overflow: hidden !important;
        }

        /*
         * Không để khoảng cách giữa các phần tử CSS/JavaScript
         * bên trong container tiếp tục cộng dồn.
         */
        div[class*="st-key-global_ui_bootstrap"]
        div[data-testid="stVerticalBlock"],
        div[class*="st-key-matches_page_ui_bootstrap"]
        div[data-testid="stVerticalBlock"] {
            min-height: 0 !important;

            gap: 0 !important;

            margin: 0 !important;
            padding: 0 !important;
        }

        /*
         * Bỏ hoàn toàn cách kéo nội dung bằng số âm.
         */
        div[class*="st-key-main_page_content_shell"] {
            position: relative !important;

            margin-top: 0 !important;
            padding-top: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_mobile_prediction_score_row_css():
    """
    Chỉ chỉnh hàng nhập tỉ số trên giao diện điện thoại.

    - Desktop giữ nguyên tuyệt đối bố cục [2, 1, 2].
    - Mobile hiển thị đội nhà và đội khách trên cùng một hàng.
    - Chỉ ẩn cột trống ở giữa.
    - Không thay đổi widget, key, dữ liệu hoặc logic dự đoán.
    """
    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            /*
             * Chuyển riêng hàng nhập tỉ số thành grid 2 cột.
             * Selector chỉ tác động tới prediction_score_row_*.
             */
            div[class*="st-key-prediction_score_row_"]
            div[data-testid="stHorizontalBlock"]:has(
                div[class*="st-key-home_score_shell_"]
            ):has(
                div[class*="st-key-away_score_shell_"]
            ) {
                display: grid !important;

                grid-template-columns:
                    minmax(0, 1fr)
                    minmax(0, 1fr) !important;

                column-gap: 8px !important;
                row-gap: 0 !important;

                width: 100% !important;
                max-width: 100% !important;

                align-items: start !important;
            }

            /*
             * Hỗ trợ cả hai tên data-testid của cột Streamlit:
             * - stColumn
             * - column
             *
             * Chỉ ẩn cột không chứa home_score_shell
             * và cũng không chứa away_score_shell.
             * Đây chính là cột trống ở giữa.
             */
            div[class*="st-key-prediction_score_row_"]
            div[data-testid="stHorizontalBlock"]
            > :is(
                div[data-testid="stColumn"],
                div[data-testid="column"]
            ):not(
                :has(div[class*="st-key-home_score_shell_"])
            ):not(
                :has(div[class*="st-key-away_score_shell_"])
            ) {
                display: none !important;
            }

            /*
             * Cột đội nhà luôn nằm bên trái.
             */
            div[class*="st-key-prediction_score_row_"]
            div[data-testid="stHorizontalBlock"]
            > :is(
                div[data-testid="stColumn"],
                div[data-testid="column"]
            ):has(
                div[class*="st-key-home_score_shell_"]
            ) {
                display: block !important;

                grid-column: 1 !important;

                width: 100% !important;
                min-width: 0 !important;
                max-width: 100% !important;

                flex: none !important;

                margin: 0 !important;
                padding-left: 0 !important;
                padding-right: 0 !important;
            }

            /*
             * Cột đội khách luôn nằm bên phải.
             */
            div[class*="st-key-prediction_score_row_"]
            div[data-testid="stHorizontalBlock"]
            > :is(
                div[data-testid="stColumn"],
                div[data-testid="column"]
            ):has(
                div[class*="st-key-away_score_shell_"]
            ) {
                display: block !important;

                grid-column: 2 !important;

                width: 100% !important;
                min-width: 0 !important;
                max-width: 100% !important;

                flex: none !important;

                margin: 0 !important;
                padding-left: 0 !important;
                padding-right: 0 !important;
            }

            /*
             * Cho hai shell và number input co vừa từng nửa hàng.
             */
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"],
            div[class*="st-key-home_score_shell_"]
            div[data-testid="stNumberInput"],
            div[class*="st-key-away_score_shell_"]
            div[data-testid="stNumberInput"],
            div[class*="st-key-home_score_shell_"]
            div[data-baseweb="input"],
            div[class*="st-key-away_score_shell_"]
            div[data-baseweb="input"] {
                width: 100% !important;
                min-width: 0 !important;
                max-width: 100% !important;

                box-sizing: border-box !important;
            }

            /*
             * Tên đội dài không được làm cột bung rộng.
             */
            div[class*="st-key-home_score_shell_"]
            div[data-testid="stNumberInput"] label,
            div[class*="st-key-away_score_shell_"]
            div[data-testid="stNumberInput"] label,
            div[class*="st-key-home_score_shell_"]
            div[data-testid="stNumberInput"] label p,
            div[class*="st-key-away_score_shell_"]
            div[data-testid="stNumberInput"] label p {
                width: 100% !important;
                min-width: 0 !important;
                max-width: 100% !important;

                white-space: nowrap !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
            }

            /*
             * Không cho các nút trừ và cộng bị co hoặc biến mất.
             */
            div[class*="st-key-home_score_shell_"]
            div[data-testid="stNumberInput"] button,
            div[class*="st-key-away_score_shell_"]
            div[data-testid="stNumberInput"] button {
                flex: 0 0 auto !important;
            }
        }

        @media (max-width: 390px) {
            div[class*="st-key-prediction_score_row_"]
            div[data-testid="stHorizontalBlock"]:has(
                div[class*="st-key-home_score_shell_"]
            ):has(
                div[class*="st-key-away_score_shell_"]
            ) {
                column-gap: 6px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_prediction_score_stepper_css():
    """
    Thiết kế bộ chọn tỉ số dạng dọc:

        mũi tên tăng
             số
        mũi tên giảm

    Chỉ áp dụng cho hai ô dự đoán trong card trận đấu.
    """
    st.markdown(
        """
        <style>
        /* =====================================================
           SCORE STEPPER DỌC — CHỈ TRONG CARD DỰ ĐOÁN
           ===================================================== */

        div[class*="st-key-prediction_score_row_"] {
            --epl-score-purple: #37003C;
            --epl-score-pink: #FF2882;
            --epl-score-pink-soft: rgba(255, 40, 130, 0.075);
            --epl-score-border: rgba(55, 0, 60, 0.24);
            --epl-score-disabled: rgba(55, 0, 60, 0.25);
        }

        /* Chỉ chọn hai ô tỉ số đội nhà và đội khách */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] {
            width: 100% !important;
            min-width: 0 !important;
            max-width: 100% !important;

            margin: 0 !important;

            box-shadow: none !important;
        }

        /* Tên đội được căn giữa phía trên */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] > label {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;

            width: 100% !important;
            min-width: 0 !important;
            min-height: 24px !important;

            margin: 0 0 5px 0 !important;
            padding: 0 6px !important;

            box-sizing: border-box !important;

            text-align: center !important;
        }

        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] > label p {
            width: 100% !important;
            min-width: 0 !important;
            max-width: 100% !important;

            margin: 0 !important;

            color: var(--epl-score-purple) !important;

            font-size: 13px !important;
            font-weight: 750 !important;
            line-height: 1.2 !important;
            text-align: center !important;

            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }

        /* Vùng chứa ba phần: tăng – số – giảm */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"]
        div[data-baseweb="input"] {
            position: relative !important;
            display: block !important;

            width: 82px !important;
            min-width: 82px !important;
            max-width: 82px !important;

            height: 122px !important;
            min-height: 122px !important;

            margin: 0 auto !important;
            padding: 0 !important;

            overflow: visible !important;
            box-sizing: border-box !important;

            background: transparent !important;

            border: 0 !important;
            border-radius: 0 !important;
            outline: 0 !important;

            box-shadow: none !important;
            filter: none !important;
        }

        /* Hỗ trợ cấu trúc Streamlit mới */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInputContainer"] {
            position: relative !important;
            display: block !important;

            width: 82px !important;
            min-width: 82px !important;
            max-width: 82px !important;

            height: 122px !important;
            min-height: 122px !important;

            margin: 0 !important;
            padding: 0 !important;

            overflow: visible !important;
            box-sizing: border-box !important;

            background: transparent !important;

            border: 0 !important;
            border-radius: 0 !important;
            outline: 0 !important;

            box-shadow: none !important;
            filter: none !important;
        }

        /*
         * Bỏ bố cục ngang mặc định của wrapper hai nút.
         * Hai button gốc của Streamlit vẫn được giữ nguyên.
         */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInputContainer"]
        div:has(
            > button[data-testid="stNumberInputStepDown"]
        ):has(
            > button[data-testid="stNumberInputStepUp"]
        ) {
            position: static !important;
            display: contents !important;
        }

        /* =====================================================
           Ô HIỂN THỊ TỈ SỐ
           ===================================================== */

        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] input {
            position: absolute !important;

            top: 35px !important;
            left: 0 !important;
            right: auto !important;

            width: 82px !important;
            min-width: 82px !important;
            max-width: 82px !important;

            height: 52px !important;
            min-height: 52px !important;

            margin: 0 !important;
            padding: 0 8px !important;

            box-sizing: border-box !important;

            background: rgba(255, 255, 255, 0.94) !important;
            color: #17001C !important;

            border:
                1px solid var(--epl-score-border) !important;

            border-radius: 9px !important;
            outline: 0 !important;

            box-shadow: none !important;
            filter: none !important;

            font-family: inherit !important;
            font-size: 23px !important;
            font-weight: 850 !important;
            line-height: 50px !important;
            text-align: center !important;

            appearance: textfield !important;
            -moz-appearance: textfield !important;

            z-index: 1 !important;

            transition:
                border-color 130ms ease,
                background-color 130ms ease !important;
        }

        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] input:hover {
            border-color:
                rgba(55, 0, 60, 0.42) !important;
        }

        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] input:focus {
            background: #FFFFFF !important;

            border-color:
                var(--epl-score-pink) !important;

            outline:
                2px solid rgba(255, 40, 130, 0.14) !important;

            outline-offset: 1px !important;

            box-shadow: none !important;
        }

        /* Ẩn spinner mặc định của trình duyệt */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"]
        input::-webkit-inner-spin-button,

        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"]
        input::-webkit-outer-spin-button {
            margin: 0 !important;
            -webkit-appearance: none !important;
        }

        /* =====================================================
           HAI NÚT MŨI TÊN 2D
           ===================================================== */

        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        :is(
            button[data-testid="stNumberInputStepUp"],
            button[data-testid="stNumberInputStepDown"]
        ) {
            position: absolute !important;

            left: 50% !important;
            right: auto !important;

            width: 64px !important;
            min-width: 64px !important;
            max-width: 64px !important;

            height: 30px !important;
            min-height: 30px !important;
            max-height: 30px !important;

            margin: 0 !important;
            padding: 0 !important;

            box-sizing: border-box !important;
            overflow: hidden !important;

            background:
                var(--epl-score-pink-soft) !important;

            color:
                var(--epl-score-pink) !important;

            border:
                1px solid rgba(255, 40, 130, 0.60) !important;

            border-radius: 8px !important;
            outline: 0 !important;

            box-shadow: none !important;
            filter: none !important;

            transform:
                translateX(-50%) !important;

            cursor: pointer !important;

            z-index: 2 !important;

            transition:
                background-color 120ms ease,
                border-color 120ms ease !important;
        }

        /* Mũi tên lên: tăng tỉ số */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        button[data-testid="stNumberInputStepUp"] {
            top: 0 !important;
            bottom: auto !important;
        }

        /* Mũi tên xuống: giảm tỉ số */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        button[data-testid="stNumberInputStepDown"] {
            top: auto !important;
            bottom: 0 !important;
        }

        /* Ẩn dấu cộng và trừ mặc định */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        :is(
            button[data-testid="stNumberInputStepUp"],
            button[data-testid="stNumberInputStepDown"]
        ) > * {
            opacity: 0 !important;
        }

        /* Tự vẽ chevron để hai mũi tên đồng nhất */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        :is(
            button[data-testid="stNumberInputStepUp"],
            button[data-testid="stNumberInputStepDown"]
        )::after {
            content: "";

            position: absolute !important;

            top: 50% !important;
            left: 50% !important;

            width: 9px !important;
            height: 9px !important;

            border-right:
                3px solid var(--epl-score-pink) !important;

            border-bottom:
                3px solid var(--epl-score-pink) !important;

            pointer-events: none !important;
        }

        div[class*="st-key-prediction_score_row_"]
        button[data-testid="stNumberInputStepUp"]::after {
            transform:
                translate(-50%, -32%)
                rotate(-135deg) !important;
        }

        div[class*="st-key-prediction_score_row_"]
        button[data-testid="stNumberInputStepDown"]::after {
            transform:
                translate(-50%, -68%)
                rotate(45deg) !important;
        }

        /* =====================================================
           TRẠNG THÁI TƯƠNG TÁC
           ===================================================== */

        @media (hover: hover) {
            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            :is(
                button[data-testid="stNumberInputStepUp"],
                button[data-testid="stNumberInputStepDown"]
            ):not(:disabled):hover {
                background:
                    var(--epl-score-pink) !important;

                border-color:
                    var(--epl-score-pink) !important;

                box-shadow: none !important;
                filter: none !important;

                transform:
                    translateX(-50%) !important;
            }

            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            :is(
                button[data-testid="stNumberInputStepUp"],
                button[data-testid="stNumberInputStepDown"]
            ):not(:disabled):hover::after {
                border-color: #FFFFFF !important;
            }
        }

        /* Khi bấm */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        :is(
            button[data-testid="stNumberInputStepUp"],
            button[data-testid="stNumberInputStepDown"]
        ):not(:disabled):active {
            background:
                var(--epl-score-purple) !important;

            border-color:
                var(--epl-score-purple) !important;

            box-shadow: none !important;
            filter: none !important;

            transform:
                translateX(-50%) !important;
        }

        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        :is(
            button[data-testid="stNumberInputStepUp"],
            button[data-testid="stNumberInputStepDown"]
        ):not(:disabled):active::after {
            border-color: #FFFFFF !important;
        }

        /*
         * Khi tỉ số bằng 0, nút giảm tự bị vô hiệu hóa.
         * Khi tỉ số bằng 20, nút tăng dùng cùng trạng thái.
         */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        :is(
            button[data-testid="stNumberInputStepUp"],
            button[data-testid="stNumberInputStepDown"]
        ):disabled {
            background:
                rgba(55, 0, 60, 0.025) !important;

            border-color:
                rgba(55, 0, 60, 0.18) !important;

            cursor: not-allowed !important;
            opacity: 1 !important;

            box-shadow: none !important;
            filter: none !important;

            transform:
                translateX(-50%) !important;
        }

        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        :is(
            button[data-testid="stNumberInputStepUp"],
            button[data-testid="stNumberInputStepDown"]
        ):disabled::after {
            border-color:
                var(--epl-score-disabled) !important;
        }

        /* Focus bằng bàn phím */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        :is(
            button[data-testid="stNumberInputStepUp"],
            button[data-testid="stNumberInputStepDown"]
        ):focus-visible {
            outline:
                2px solid var(--epl-score-purple) !important;

            outline-offset: 2px !important;

            box-shadow: none !important;
        }

        /* =====================================================
           DẤU - GIỮA HAI TỈ SỐ
           ===================================================== */

        div[class*="st-key-prediction_score_row_"]
        div[data-testid="stHorizontalBlock"]:has(
            div[class*="st-key-home_score_shell_"]
        ):has(
            div[class*="st-key-away_score_shell_"]
        ) {
            position: relative !important;
        }

        div[class*="st-key-prediction_score_row_"]
        div[data-testid="stHorizontalBlock"]:has(
            div[class*="st-key-home_score_shell_"]
        ):has(
            div[class*="st-key-away_score_shell_"]
        )::after {
            content: "—";

            position: absolute !important;

            top: 120px !important;
            left: 50% !important;

            color:
                var(--epl-score-purple) !important;

            font-family: inherit !important;
            font-size: 25px !important;
            font-weight: 850 !important;
            line-height: 1 !important;

            transform:
                translate(-50%, -50%) !important;

            pointer-events: none !important;

            z-index: 3 !important;
        }

        /* =====================================================
           MOBILE
           ===================================================== */

        @media (max-width: 768px) {
            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInput"] > label {
                min-height: 22px !important;

                margin-bottom: 4px !important;

                padding-left: 3px !important;
                padding-right: 3px !important;
            }

            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInput"] > label p {
                font-size: 12px !important;
            }

            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInput"]
            div[data-baseweb="input"],

            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInputContainer"] {
                width: 74px !important;
                min-width: 74px !important;
                max-width: 74px !important;

                height: 116px !important;
                min-height: 116px !important;
            }

            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInput"] input {
                top: 34px !important;

                width: 74px !important;
                min-width: 74px !important;
                max-width: 74px !important;

                height: 48px !important;
                min-height: 48px !important;

                border-radius: 8px !important;

                font-size: 21px !important;
                line-height: 46px !important;
            }

            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            :is(
                button[data-testid="stNumberInputStepUp"],
                button[data-testid="stNumberInputStepDown"]
            ) {
                width: 60px !important;
                min-width: 60px !important;
                max-width: 60px !important;

                height: 28px !important;
                min-height: 28px !important;
                max-height: 28px !important;

                border-radius: 7px !important;
            }

            div[class*="st-key-prediction_score_row_"]
            div[data-testid="stHorizontalBlock"]:has(
                div[class*="st-key-home_score_shell_"]
            ):has(
                div[class*="st-key-away_score_shell_"]
            )::after {
                top: 120px !important;
                font-size: 23px !important;
            }
        }

        @media (max-width: 390px) {
            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInput"]
            div[data-baseweb="input"],

            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInputContainer"],

            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInput"] input {
                width: 70px !important;
                min-width: 70px !important;
                max-width: 70px !important;
            }

            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            :is(
                button[data-testid="stNumberInputStepUp"],
                button[data-testid="stNumberInputStepDown"]
            ) {
                width: 56px !important;
                min-width: 56px !important;
                max-width: 56px !important;
            }
        }

        /* =====================================================
           HIỆU CHỈNH CUỐI: CĂN GIỮA + SCORE TILE MỚI
           ===================================================== */
        
        /* Tên đội chiếm toàn bộ chiều rộng cột */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] {
            width: 100% !important;
            min-width: 0 !important;
            max-width: 100% !important;
        
            margin: 0 !important;
        }
        
        /* Căn tên đội chính giữa */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] > label {
            display: flex !important;
            justify-content: center !important;
        
            width: 100% !important;
        
            margin: 0 0 6px !important;
            padding: 0 6px !important;
        
            text-align: center !important;
        }
        
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] > label p {
            width: 100% !important;
            margin: 0 !important;
        
            color: #37003C !important;
        
            font-size: 13px !important;
            font-weight: 800 !important;
            line-height: 1.25 !important;
            text-align: center !important;
        
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }
        
        /*
         * Quan trọng nhất:
         * Căn chính giữa cả wrapper cũ và container mới của Streamlit.
         */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"]
        div[data-baseweb="input"],
        
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInputContainer"] {
            position: relative !important;
            display: block !important;
        
            width: 88px !important;
            min-width: 88px !important;
            max-width: 88px !important;
        
            height: 136px !important;
            min-height: 136px !important;
        
            margin: 0 auto !important;
            padding: 0 !important;
        
            overflow: visible !important;
            box-sizing: border-box !important;
        
            background: transparent !important;
        
            border: 0 !important;
            border-radius: 0 !important;
            outline: 0 !important;
        
            box-shadow: none !important;
            filter: none !important;
        }
        
        /* Score tile lớn, dạng bảng tỉ số EPL */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] input {
            position: absolute !important;
        
            top: 37px !important;
            left: 50% !important;
            right: auto !important;
        
            width: 88px !important;
            min-width: 88px !important;
            max-width: 88px !important;
        
            height: 62px !important;
            min-height: 62px !important;
        
            margin: 0 !important;
            padding: 0 8px !important;
        
            box-sizing: border-box !important;
        
            background: #37003C !important;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        
            border: 2px solid #FF2882 !important;
            border-radius: 0 !important;
            outline: 0 !important;
        
            clip-path: polygon(
                9px 0,
                calc(100% - 9px) 0,
                100% 9px,
                100% calc(100% - 9px),
                calc(100% - 9px) 100%,
                9px 100%,
                0 calc(100% - 9px),
                0 9px
            ) !important;
        
            box-shadow: none !important;
            filter: none !important;
        
            transform: translateX(-50%) !important;
        
            font-family:
                system-ui,
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif !important;
        
            font-size: 34px !important;
            font-weight: 950 !important;
            line-height: 58px !important;
            letter-spacing: -0.055em !important;
            text-align: center !important;
            font-variant-numeric: tabular-nums !important;
        
            caret-color: transparent !important;
        
            user-select: none !important;
            -webkit-user-select: none !important;
        
            pointer-events: none !important;
        
            z-index: 1 !important;
        }
        
        /* Không cho các rule hover/focus cũ đổi score tile sang màu trắng */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] input:hover,
        
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] input:focus {
            background: #37003C !important;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        
            border-color: #FF2882 !important;
            outline: 0 !important;
        
            box-shadow: none !important;
        }
        
        /* Kích thước hai nút mũi tên */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        :is(
            button[data-testid="stNumberInputStepUp"],
            button[data-testid="stNumberInputStepDown"]
        ) {
            left: 50% !important;
            right: auto !important;
        
            width: 68px !important;
            min-width: 68px !important;
            max-width: 68px !important;
        
            height: 30px !important;
            min-height: 30px !important;
            max-height: 30px !important;
        
            transform: translateX(-50%) !important;
        
            box-shadow: none !important;
        }
        
        /* Nút tăng */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        button[data-testid="stNumberInputStepUp"] {
            top: 0 !important;
            bottom: auto !important;
        }
        
        /* Nút giảm */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        button[data-testid="stNumberInputStepDown"] {
            top: auto !important;
            bottom: 0 !important;
        }
        
        /* Dấu : phải ngang chính giữa hai score tile */
        div[class*="st-key-prediction_score_row_"]
        div[data-testid="stHorizontalBlock"]:has(
            div[class*="st-key-home_score_shell_"]
        ):has(
            div[class*="st-key-away_score_shell_"]
        )::after {
            top: 103px !important;
        
            color: #37003C !important;
        
            font-size: 30px !important;
            font-weight: 950 !important;
        }
        
        /* Mobile */
        @media (max-width: 768px) {
            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInput"] > label p {
                font-size: 12px !important;
            }
        
            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInput"]
            div[data-baseweb="input"],
        
            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInputContainer"] {
                width: 82px !important;
                min-width: 82px !important;
                max-width: 82px !important;
        
                height: 130px !important;
                min-height: 130px !important;
        
                margin-left: auto !important;
                margin-right: auto !important;
            }
        
            div[class*="st-key-prediction_score_row_"]
            :is(
                div[class*="st-key-home_score_shell_"],
                div[class*="st-key-away_score_shell_"]
            )
            div[data-testid="stNumberInput"] input {
                top: 36px !important;
        
                width: 82px !important;
                min-width: 82px !important;
                max-width: 82px !important;
        
                height: 58px !important;
                min-height: 58px !important;
        
                font-size: 32px !important;
                line-height: 54px !important;
            }
        
            div[class*="st-key-prediction_score_row_"]
            div[data-testid="stHorizontalBlock"]:has(
                div[class*="st-key-home_score_shell_"]
            ):has(
                div[class*="st-key-away_score_shell_"]
            )::after {
                top: 99px !important;
                font-size: 27px !important;
            }
        }

        /* =====================================================
           LOGO CLB PHÍA TRÊN BỘ CHỌN TỈ SỐ
           ===================================================== */
        
        /* Loại bỏ khoảng cách mặc định giữa logo và number_input */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stVerticalBlock"] {
            gap: 0 !important;
        }
        
        div[class*="st-key-prediction_score_row_"]
        div[data-testid="stElementContainer"]:has(
            .epl-prediction-team-logo
        ) {
            margin: 0 !important;
            padding: 0 !important;
        }
        
        /* Khung căn chỉnh; không tạo box hiển thị */
        div[class*="st-key-prediction_score_row_"]
        .epl-prediction-team-logo {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        
            width: 100% !important;
            height: 52px !important;
        
            margin: 0 0 8px !important;
            padding: 0 !important;
        
            background: transparent !important;
            border: 0 !important;
            border-radius: 0 !important;
        
            box-shadow: none !important;
            filter: none !important;
        
            overflow: visible !important;
        }
        
        /* Chỉ hiển thị logo, không có nền hoặc box bao quanh */
        div[class*="st-key-prediction_score_row_"]
        .epl-prediction-team-logo img {
            display: block !important;
        
            width: auto !important;
            height: auto !important;
        
            max-width: 54px !important;
            max-height: 52px !important;
        
            margin: 0 auto !important;
            padding: 0 !important;
        
            object-fit: contain !important;
            object-position: center !important;
        
            background: transparent !important;
            border: 0 !important;
            border-radius: 0 !important;
        
            box-shadow: none !important;
            filter: none !important;
        
            user-select: none !important;
            pointer-events: none !important;
        }
        
        /*
         * Tên đội vẫn tồn tại làm label của number_input,
         * nhưng được ẩn khỏi giao diện và không chiếm diện tích.
         */
        div[class*="st-key-prediction_score_row_"]
        :is(
            div[class*="st-key-home_score_shell_"],
            div[class*="st-key-away_score_shell_"]
        )
        div[data-testid="stNumberInput"] > label {
            position: absolute !important;
        
            width: 1px !important;
            min-width: 1px !important;
            max-width: 1px !important;
        
            height: 1px !important;
            min-height: 1px !important;
            max-height: 1px !important;
        
            margin: -1px !important;
            padding: 0 !important;
        
            overflow: hidden !important;
        
            clip: rect(0, 0, 0, 0) !important;
            clip-path: inset(50%) !important;
        
            white-space: nowrap !important;
        
            border: 0 !important;
        }
        
        /* Chỉ xuất hiện nếu metadata logo bị thiếu */
        div[class*="st-key-prediction_score_row_"]
        .epl-prediction-team-logo-fallback {
            color: #37003C !important;
        
            font-size: 12px !important;
            font-weight: 800 !important;
            line-height: 1.2 !important;
            text-align: center !important;
        }
        
        /*
         * Logo làm hàng cao hơn tên đội cũ.
         * Căn lại dấu : ngang chính giữa hai score tile.
         */
        div[class*="st-key-prediction_score_row_"]
        div[data-testid="stHorizontalBlock"]:has(
            div[class*="st-key-home_score_shell_"]
        ):has(
            div[class*="st-key-away_score_shell_"]
        )::after {
            top: 136px !important;
        }
        
        /* Mobile */
        @media (max-width: 768px) {
            div[class*="st-key-prediction_score_row_"]
            .epl-prediction-team-logo {
                height: 46px !important;
                margin-bottom: 7px !important;
            }
        
            div[class*="st-key-prediction_score_row_"]
            .epl-prediction-team-logo img {
                max-width: 48px !important;
                max-height: 46px !important;
            }
        
            div[class*="st-key-prediction_score_row_"]
            div[data-testid="stHorizontalBlock"]:has(
                div[class*="st-key-home_score_shell_"]
            ):has(
                div[class*="st-key-away_score_shell_"]
            )::after {
                top: 132px !important;
            }
        }
        /* =====================================================
           KẾT QUẢ TRẬN ĐẤU — CARD ĐÃ KẾT THÚC
           ===================================================== */
        
        .epl-finished-score-wrap {
            position: relative;
            isolation: isolate;
        
            width: min(100%, 680px);
        
            box-sizing: border-box;
        
            margin: 28px auto 0;
            padding-top: 15px;
        }
        
        /* Dải màu EPL */
        .epl-finished-score-wrap::before {
            content: "";
        
            position: absolute;
            z-index: 1;
        
            top: 12px;
            right: 0;
            left: 0;
        
            height: 4px;
        
            background: linear-gradient(
                90deg,
                #FF2882 0%,
                #FF2882 49.5%,
                #00FF85 50.5%,
                #00FF85 100%
            );
        
            border-radius: 1px;
        
            pointer-events: none;
        }
        
        /* Vệt sáng chạy dọc dải màu */
        .epl-finished-score-wrap::after {
            content: "";
        
            position: absolute;
            z-index: 2;
        
            top: 12px;
            right: 0;
            left: 0;
        
            height: 4px;
        
            background-image: linear-gradient(
                100deg,
                transparent 0%,
                transparent 38%,
                rgba(255, 255, 255, 0.96) 49%,
                rgba(255, 255, 255, 0.55) 53%,
                transparent 64%,
                transparent 100%
            );
        
            background-repeat: no-repeat;
            background-size: 130px 100%;
            background-position: -160px 0;
        
            animation:
                epl-finished-strip-shimmer
                2.8s
                linear
                infinite;
        
            pointer-events: none;
        }
        
        @keyframes epl-finished-strip-shimmer {
            from {
                background-position: -160px 0;
            }
        
            to {
                background-position: calc(100% + 160px) 0;
            }
        }
        
        /* Khung trắng góc cạnh bên ngoài nhãn */
        .epl-finished-score-label {
            position: absolute;
            z-index: 4;
        
            top: -1px;
            left: 50%;
        
            display: flex;
        
            width: 98px;
            height: 29px;
        
            box-sizing: border-box;
        
            align-items: center;
            justify-content: center;
        
            padding: 2px;
        
            transform: translateX(-50%);
        
            background: rgba(255, 255, 255, 0.98);
        
            clip-path: polygon(
                9px 0,
                calc(100% - 9px) 0,
                100% 9px,
                100% calc(100% - 9px),
                calc(100% - 9px) 100%,
                9px 100%,
                0 calc(100% - 9px),
                0 9px
            );
        
            box-shadow: none;
        }
        
        /* Phần màu hồng phía trong */
        .epl-finished-score-label span {
            display: flex;
        
            width: 100%;
            height: 100%;
        
            box-sizing: border-box;
        
            align-items: center;
            justify-content: center;
        
            padding: 0 12px;
        
            background: linear-gradient(
                110deg,
                #FF2882 0%,
                #FF2882 42%,
                #FF75B1 50%,
                #FF2882 58%,
                #FF2882 100%
            );
        
            color: #FFFFFF;
        
            clip-path: polygon(
                7px 0,
                calc(100% - 7px) 0,
                100% 7px,
                100% calc(100% - 7px),
                calc(100% - 7px) 100%,
                7px 100%,
                0 calc(100% - 7px),
                0 7px
            );
        
            font-size: 10px;
            font-weight: 950;
            line-height: 1;
            letter-spacing: 0.10em;
            white-space: nowrap;
            text-transform: uppercase;
        }
        
        /*
         * Hai cột đội rộng bằng nhau.
         * Vùng tỉ số có chiều rộng cố định và nằm đúng tâm card.
         */
        .epl-finished-score-row {
            position: relative;
        
            display: grid;
        
            grid-template-columns:
                minmax(0, 1fr)
                178px
                minmax(0, 1fr);
        
            width: 100%;
            min-height: 118px;
        
            box-sizing: border-box;
        
            align-items: center;
        
            margin: 0;
            padding: 28px 18px 0;
        
            overflow: visible;
        
            background: transparent;
            border: 0;
            border-radius: 0;
            box-shadow: none;
        }
        
        .epl-finished-score-team {
            display: grid;
        
            min-width: 0;
        
            grid-template-rows:
                62px
                auto;
        
            align-items: center;
            justify-items: center;
        
            gap: 8px;
        }
        
        .epl-finished-score-logo {
            display: flex;
        
            width: 100%;
            height: 62px;
        
            align-items: center;
            justify-content: center;
        
            margin: 0;
            padding: 0;
        
            overflow: visible;
        
            background: transparent;
            border: 0;
            box-shadow: none;
        }
        
        .epl-finished-score-logo img {
            display: block;
        
            width: auto;
            height: auto;
        
            max-width: 66px;
            max-height: 60px;
        
            margin: 0 auto;
        
            object-fit: contain;
            object-position: center;
        
            background: transparent;
            border: 0;
            box-shadow: none;
        
            user-select: none;
            pointer-events: none;
        }
        
        .epl-finished-score-logo-fallback {
            display: flex;
        
            width: 52px;
            height: 52px;
        
            box-sizing: border-box;
        
            align-items: center;
            justify-content: center;
        
            padding: 5px;
        
            overflow: hidden;
        
            background: rgba(55, 0, 60, 0.05);
            color: #37003C;
        
            border: 1px solid rgba(55, 0, 60, 0.18);
            border-radius: 50%;
        
            font-size: 9px;
            font-weight: 900;
            line-height: 1.05;
            text-align: center;
        }
        
        .epl-finished-score-team-name {
            display: block;
        
            width: 100%;
            max-width: 150px;
        
            margin: 0;
        
            overflow: hidden;
        
            color: #37003C;
        
            font-size: 13px;
            font-weight: 900;
            line-height: 1.2;
            text-align: center;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .epl-finished-score-team.is-winner
        .epl-finished-score-team-name {
            color: #00864A;
        }
        
        /*
         * Box tỉ số nằm đúng tâm card.
         * Hai ô số có chiều rộng bằng nhau, dấu gạch ngang ở chính giữa.
         */
        .epl-finished-score-value {
            display: grid;
        
            grid-template-columns:
                minmax(0, 1fr)
                20px
                minmax(0, 1fr);
        
            width: 174px;
            height: 86px;
        
            box-sizing: border-box;
        
            align-items: center;
            justify-items: stretch;
            justify-self: center;
        
            margin: 0;
            padding: 0 10px;
        
            background: rgba(255, 255, 255, 0.42);
        
            border: 1px solid rgba(55, 0, 60, 0.13);
            border-radius: 18px;
        
            box-shadow: none;
        
            backdrop-filter: blur(9px);
            -webkit-backdrop-filter: blur(9px);
        
            font-variant-numeric: tabular-nums;
            font-feature-settings: "tnum" 1;
        }
        
        .epl-finished-score-number {
            display: grid;
        
            width: 100%;
            min-width: 0;
            height: auto;
        
            place-items: center;
        
            margin: 0;
            padding: 0;
        
            color: #37003C;
        
            font-family:
                system-ui,
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;
        
            font-size: 64px;
            font-weight: 950;
            line-height: 0.88;
            letter-spacing: 0;
            text-align: center;
        
            font-variant-numeric: tabular-nums;
            font-feature-settings: "tnum" 1;
        
            transform: translateY(-1px);

            text-shadow: none;
            user-select: none;
        }
        
        .epl-finished-score-number.is-winner {
            color: #009E57;
        }
        
        .epl-finished-score-separator {
            display: grid;
        
            width: 100%;
            height: auto;
        
            place-items: center;
        
            margin: 0;
            padding: 0;
        
            color: #FF2882;
        
            font-size: 27px;
            font-weight: 800;
            line-height: 1;
            text-align: center;
        
            transform: translateY(-1px);
        
            user-select: none;
        }
        
        @media (prefers-reduced-motion: reduce) {
            .epl-finished-score-wrap::after {
                animation: none;
            }
        }
        
        @media (max-width: 768px) {
            .epl-finished-score-wrap {
                width: 100%;
        
                margin-top: 24px;
                padding-top: 13px;
            }
        
            .epl-finished-score-wrap::before,
            .epl-finished-score-wrap::after {
                top: 11px;
                height: 3px;
            }
        
            .epl-finished-score-label {
                top: 0;
        
                width: 88px;
                height: 26px;
            }
        
            .epl-finished-score-label span {
                font-size: 9px;
            }
        
            .epl-finished-score-row {
                grid-template-columns:
                    minmax(0, 1fr)
                    126px
                    minmax(0, 1fr);
        
                min-height: 102px;
        
                padding: 25px 6px 0;
            }
        
            .epl-finished-score-team {
                grid-template-rows:
                    50px
                    auto;
        
                gap: 6px;
            }
        
            .epl-finished-score-logo {
                height: 50px;
            }
        
            .epl-finished-score-logo img {
                max-width: 52px;
                max-height: 49px;
            }
        
            .epl-finished-score-logo-fallback {
                width: 44px;
                height: 44px;
        
                font-size: 8px;
            }
        
            .epl-finished-score-team-name {
                max-width: 88px;
        
                font-size: 10.5px;
            }
        
            .epl-finished-score-value {
                grid-template-columns:
                    minmax(0, 1fr)
                    14px
                    minmax(0, 1fr);
            
                width: 120px;
                height: 64px;
            
                padding: 0 8px;
            
                border-radius: 14px;
            }
            
            .epl-finished-score-number {
                font-size: 44px;
            }
            
            .epl-finished-score-separator {
                font-size: 20px;
            }
        }
        
        @media (max-width: 390px) {
            .epl-finished-score-row {
                grid-template-columns:
                    minmax(0, 1fr)
                    116px
                    minmax(0, 1fr);
        
                padding-right: 4px;
                padding-left: 4px;
            }
        
            .epl-finished-score-value {
                grid-template-columns:
                    minmax(0, 1fr)
                    14px
                    minmax(0, 1fr);
            
                width: 112px;
                height: 60px;
            
                padding: 0 6px;
            }
            
            .epl-finished-score-number {
                font-size: 40px;
            }
            
            .epl-finished-score-separator {
                font-size: 19px;
            }
        
            .epl-finished-score-team-name {
                max-width: 68px;
        
                font-size: 9.5px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_prediction_score_readonly_script():
    """
    Khóa thao tác nhập trực tiếp vào hai ô tỉ số dự đoán.

    Nút tăng/giảm native của Streamlit vẫn hoạt động bình thường.
    Không tác động đến number_input ở trang Admin.
    """
    components.html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;

            const inputSelector = [
                'div[class*="st-key-prediction_score_row_"]',
                ':is(',
                'div[class*="st-key-home_score_shell_"],',
                'div[class*="st-key-away_score_shell_"]',
                ') input'
            ].join(" ");

            const lockScoreInput = (input) => {
                if (
                    !input
                    || !(input instanceof parentWindow.HTMLInputElement)
                ) {
                    return;
                }

                input.readOnly = true;

                input.setAttribute("readonly", "");
                input.setAttribute("aria-readonly", "true");
                input.setAttribute("inputmode", "none");
                input.setAttribute("autocomplete", "off");
                input.setAttribute("spellcheck", "false");

                if (
                    input.dataset.eplScoreReadonlyBound === "1"
                ) {
                    return;
                }

                const preventEditing = (event) => {
                    event.preventDefault();
                };

                input.addEventListener(
                    "beforeinput",
                    preventEditing
                );

                input.addEventListener(
                    "paste",
                    preventEditing
                );

                input.addEventListener(
                    "drop",
                    preventEditing
                );

                input.addEventListener(
                    "wheel",
                    preventEditing,
                    { passive: false }
                );

                input.addEventListener(
                    "keydown",
                    (event) => {
                        const blockedKeys = new Set([
                            "Backspace",
                            "Delete",
                            "ArrowUp",
                            "ArrowDown",
                            "PageUp",
                            "PageDown",
                            "Home",
                            "End"
                        ]);

                        if (
                            event.key.length === 1
                            || blockedKeys.has(event.key)
                        ) {
                            event.preventDefault();
                        }
                    }
                );

                input.dataset.eplScoreReadonlyBound = "1";
            };

            const applyReadonly = () => {
                parentDocument
                    .querySelectorAll(inputSelector)
                    .forEach(lockScoreInput);
            };

            let updateScheduled = false;

            const scheduleUpdate = () => {
                if (updateScheduled) {
                    return;
                }

                updateScheduled = true;

                parentWindow.requestAnimationFrame(() => {
                    updateScheduled = false;
                    applyReadonly();
                });
            };

            const observerKey =
                "__eplPredictionScoreReadonlyObserver";

            if (parentWindow[observerKey]) {
                parentWindow[observerKey].disconnect();
            }

            applyReadonly();

            const observer =
                new parentWindow.MutationObserver(
                    scheduleUpdate
                );

            observer.observe(
                parentDocument.body,
                {
                    childList: true,
                    subtree: true
                }
            );

            parentWindow[observerKey] = observer;
        })();
        </script>
        """,
        height=0,
        scrolling=False
    )

def inject_mobile_team_name_display_script():
    """
    Chỉ đổi phần chữ đang hiển thị sang tên CLB ngắn khi viewport <= 768px.

    Giá trị Python, dữ liệu database và nội dung desktop luôn giữ tên đầy đủ.
    """
    aliases_json = json.dumps(
        MOBILE_TEAM_NAME_OVERRIDES,
        ensure_ascii=False
    )

    script_html = r"""
    <script>
    (() => {
        const parentWindow = window.parent;
        const parentDocument = parentWindow.document;
        const stateKey = "__eplMobileTeamNameDisplayState";
        const mobileQuery = parentWindow.matchMedia(
            "(max-width: 768px)"
        );
        const previousState = parentWindow[stateKey];

        const aliases = __EPL_MOBILE_TEAM_ALIASES__;

        const escapeRegExp = (value) => {
            return value.replace(
                /[.*+?^${}()|[\]\\]/g,
                "\\$&"
            );
        };

        const replacementPairs = Object
            .entries(aliases)
            .filter(([fullName, shortName]) => {
                return (
                    String(fullName).trim()
                    && String(fullName).toLocaleLowerCase()
                        !== String(shortName).toLocaleLowerCase()
                );
            })
            .sort((left, right) => {
                return right[0].length - left[0].length;
            })
            .map(([fullName, shortName]) => {
                return {
                    fullName,
                    replacement: shortName
                };
            });

        /*
         * Gộp toàn bộ tên CLB vào một RegExp duy nhất.
         * Bản cũ chạy lần lượt hàng chục RegExp trên mọi text node,
         * làm mobile tốn CPU rõ rệt khi DOM lớn.
         */
        const replacementByNormalizedName = new Map(
            replacementPairs.map((pair) => {
                return [
                    pair.fullName.toLocaleLowerCase(),
                    pair.replacement
                ];
            })
        );

        const combinedAliasPattern = (
            replacementPairs.length
            ? new RegExp(
                replacementPairs
                    .map((pair) => {
                        return escapeRegExp(
                            pair.fullName
                        );
                    })
                    .join("|"),
                "gi"
            )
            : null
        );

        const toMobileText = (value) => {
            const sourceText = String(value ?? "");

            if (!combinedAliasPattern) {
                return sourceText;
            }

            return sourceText.replace(
                combinedAliasPattern,
                (matchedText) => {
                    return (
                        replacementByNormalizedName.get(
                            matchedText.toLocaleLowerCase()
                        )
                        ?? matchedText
                    );
                }
            );
        };

        if (
            previousState
            && typeof previousState.restoreAll === "function"
        ) {
            previousState.restoreAll();
        }

        if (previousState?.observer) {
            previousState.observer.disconnect();
        }

        if (
            previousState?.mobileQuery
            && previousState?.mediaHandler
        ) {
            previousState.mobileQuery.removeEventListener(
                "change",
                previousState.mediaHandler
            );
        }

        const originalTextByNode = new WeakMap();

        const shouldSkipTextNode = (node) => {
            const parent = node.parentElement;

            if (!parent) {
                return true;
            }

            return Boolean(
                parent.closest(
                    "script, style, noscript, svg, code, pre"
                )
            );
        };

        const updateTextNode = (node, useMobileName) => {
            if (
                !node
                || node.nodeType !== parentWindow.Node.TEXT_NODE
                || shouldSkipTextNode(node)
            ) {
                return;
            }

            const currentText = node.nodeValue ?? "";

            if (!currentText.trim()) {
                return;
            }

            let originalText = originalTextByNode.get(node);

            if (originalText === undefined) {
                originalText = currentText;
                originalTextByNode.set(node, originalText);
            } else {
                const expectedMobileText = toMobileText(
                    originalText
                );

                if (
                    currentText !== originalText
                    && currentText !== expectedMobileText
                ) {
                    originalText = currentText;
                    originalTextByNode.set(
                        node,
                        originalText
                    );
                }
            }

            const targetText = (
                useMobileName
                ? toMobileText(originalText)
                : originalText
            );

            if (node.nodeValue !== targetText) {
                node.nodeValue = targetText;
            }
        };

        const updateSubtree = (
            rootNode,
            useMobileName
        ) => {
            if (!rootNode) {
                return;
            }

            if (
                rootNode.nodeType
                === parentWindow.Node.TEXT_NODE
            ) {
                updateTextNode(
                    rootNode,
                    useMobileName
                );
                return;
            }

            if (
                rootNode.nodeType
                !== parentWindow.Node.ELEMENT_NODE
                && rootNode.nodeType
                !== parentWindow.Node.DOCUMENT_NODE
                && rootNode.nodeType
                !== parentWindow.Node.DOCUMENT_FRAGMENT_NODE
            ) {
                return;
            }

            const walker = parentDocument.createTreeWalker(
                rootNode,
                parentWindow.NodeFilter.SHOW_TEXT
            );

            let textNode = walker.nextNode();

            while (textNode) {
                updateTextNode(
                    textNode,
                    useMobileName
                );
                textNode = walker.nextNode();
            }
        };

        const applyAll = () => {
            updateSubtree(
                parentDocument.body,
                mobileQuery.matches
            );
        };

        const observer = new parentWindow.MutationObserver(
            (mutations) => {
                if (!mobileQuery.matches) {
                    return;
                }

                for (const mutation of mutations) {
                    if (
                        mutation.type === "characterData"
                    ) {
                        updateTextNode(
                            mutation.target,
                            true
                        );
                        continue;
                    }

                    for (
                        const addedNode
                        of mutation.addedNodes
                    ) {
                        updateSubtree(
                            addedNode,
                            true
                        );
                    }
                }
            }
        );

        const mediaHandler = () => {
            applyAll();
        };

        mobileQuery.addEventListener(
            "change",
            mediaHandler
        );

        parentWindow[stateKey] = {
            observer,
            mobileQuery,
            mediaHandler,
            restoreAll: () => {
                updateSubtree(
                    parentDocument.body,
                    false
                );
            }
        };

        /*
         * Chuẩn hóa DOM hiện tại trước rồi mới bật observer,
         * tránh observer tự nhận chính các thay đổi vừa tạo ra.
         */
        applyAll();

        observer.observe(
            parentDocument.body,
            {
                childList: true,
                characterData: true,
                subtree: true
            }
        );
    })();
    </script>
    """.replace(
        "__EPL_MOBILE_TEAM_ALIASES__",
        aliases_json
    )

    components.html(
        script_html,
        height=0,
        scrolling=False
    )

def inject_match_datepicker_calendar_theme(match_dates):
    today = today_vietnam_date()

    english_month_names = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December"
    ]

    today_month_en = english_month_names[today.month - 1]
    today_day = today.day
    today_year = today.year
    match_date_iso_values = sorted({
        pd.Timestamp(date_value).date().isoformat()
        for date_value in match_dates
        if date_value is not None and not pd.isna(date_value)
    })

    match_date_iso_js = (
        "["
        + ",".join(
            f'"{date_value}"'
            for date_value in match_date_iso_values
        )
        + "]"
    )

    st.markdown(
        f"""
        <style>
        /* =====================================================
           PHẠM VI ÁP DỤNG
           Chỉ áp dụng khi widget filter_date có mặt trên trang
           ===================================================== */

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"] {{
            position: relative !important;
            isolation: isolate !important;

            color: #0F172A !important;
            font-weight: 400 !important;

            background: transparent !important;
            border: none !important;
            outline: none !important;
            box-shadow: none !important;

            border-radius: 999px !important;
        }}

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"] * {{
            position: relative !important;
            z-index: 2 !important;

            font-weight: 400 !important;
            box-shadow: none !important;
        }}

        /* Reset pseudo-element mặc định của từng ngày */
        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]::before {{
            content: "" !important;

            position: absolute !important;
            left: 50% !important;
            top: 50% !important;

            width: 0 !important;
            height: 0 !important;

            transform: translate(-50%, -50%) !important;

            border: none !important;
            border-radius: 999px !important;

            background: transparent !important;
            box-shadow: none !important;

            z-index: 0 !important;
            pointer-events: none !important;

            transition:
                width 0.15s ease,
                height 0.15s ease,
                background 0.15s ease !important;
        }}

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]::after {{
            content: none !important;
            display: none !important;

            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }}

        /* =====================================================
           HOVER
           ===================================================== */

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:not([aria-disabled="true"]):hover::before {{
            width: 28px !important;
            height: 28px !important;

            background: rgba(18, 60, 105, 0.08) !important;
        }}

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:not([aria-disabled="true"]):hover,
        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:not([aria-disabled="true"]):hover * {{
            color: #0F172A !important;
            font-weight: 400 !important;
        }}

        /* =====================================================
           NGÀY HÔM NAY
           Luôn có ô tròn xám nhạt khi chưa được chọn
           ===================================================== */

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]
        [aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"] {{
            font-weight: 400 !important;
        }}

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"]::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"]
        )::before {{
            width: 28px !important;
            height: 28px !important;

            background: #E5E7EB !important;

            border: none !important;
            border-radius: 999px !important;

            box-shadow: none !important;
        }}

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"]
        ),

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"]
        ) * {{
            color: #0F172A !important;
            font-weight: 400 !important;
        }}

        /* =====================================================
           RESET NGÀY ĐƯỢC CHỌN
           Xóa toàn bộ nền/vòng tròn đỏ mặc định ở các lớp con
           ===================================================== */

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-selected="true"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][data-selected="true"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="Selected"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([aria-selected="true"]),

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([data-selected="true"]) {{
            background: transparent !important;

            border: none !important;
            outline: none !important;

            box-shadow: none !important;
            filter: none !important;
        }}

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-selected="true"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][data-selected="true"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="Selected"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([aria-selected="true"]) *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([data-selected="true"]) * {{
            background: transparent !important;

            border-color: transparent !important;
            outline: none !important;

            box-shadow: none !important;
            filter: none !important;
        }}

        /* Xóa pseudo-element đỏ nằm trên các phần tử con */
        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-selected="true"] > *::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-selected="true"] > *::after,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][data-selected="true"] > *::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][data-selected="true"] > *::after,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="Selected"] > *::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="Selected"] > *::after,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([aria-selected="true"]) > *::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([aria-selected="true"]) > *::after {{
            content: none !important;
            display: none !important;

            background: transparent !important;
            border: none !important;
            outline: none !important;

            box-shadow: none !important;
            filter: none !important;
        }}

        /* =====================================================
           NGÀY ĐƯỢC CHỌN
           ===================================================== */

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-selected="true"]::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][data-selected="true"]::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="Selected"]::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([aria-selected="true"])::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([data-selected="true"])::before {{
            content: "" !important;
            display: block !important;

            width: 28px !important;
            height: 28px !important;

            background: #123C69 !important;

            border: none !important;
            border-radius: 999px !important;

            outline: none !important;
            box-shadow: none !important;
            filter: none !important;
        }}

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-selected="true"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-selected="true"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][data-selected="true"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][data-selected="true"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="Selected"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="Selected"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([aria-selected="true"]),

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([aria-selected="true"]) *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([data-selected="true"]),

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has([data-selected="true"]) * {{
            color: #FFFFFF !important;
            font-weight: 400 !important;
        }}

        /* =====================================================
           HÔM NAY + ĐANG ĐƯỢC CHỌN
           ===================================================== */

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-selected="true"]::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][data-selected="true"]::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-label*="Selected"]::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"]:has(
            [aria-selected="true"]
        )::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"]:has(
            [data-selected="true"]
        )::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-selected="true"]
        )::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][data-selected="true"]
        )::before,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-label*="Selected"]
        )::before {{
            width: 28px !important;
            height: 28px !important;

            background: #123C69 !important;

            border: none !important;
            border-radius: 999px !important;

            box-shadow: none !important;
        }}

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-selected="true"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-selected="true"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][data-selected="true"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][data-selected="true"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"]:has(
            [aria-selected="true"]
        ),

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"]:has(
            [aria-selected="true"]
        ) *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-selected="true"]
        ),

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-selected="true"]
        ) *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][data-selected="true"]
        ),

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][data-selected="true"]
        ) * {{
            color: #FFFFFF !important;
            font-weight: 400 !important;
        }}

        /* =====================================================
           NGÀY KHÔNG KHẢ DỤNG
           ===================================================== */

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-disabled="true"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-disabled="true"] * {{
            color: #A8B1C2 !important;
            font-weight: 400 !important;
            opacity: 0.72 !important;
        }}

        /* =====================================================
           FIX CUỐI: HÔM NAY KHI ĐƯỢC CHỌN
           Ép số ngày thành màu trắng
           ===================================================== */

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-selected="true"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-selected="true"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][data-selected="true"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][data-selected="true"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-label*="Selected"],

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"][aria-label*="{today_month_en} {today_day}"][aria-label*="{today_year}"][aria-label*="Selected"] *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"]
            [aria-label*="{today_year}"]
            [aria-selected="true"]
        ),

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"]
            [aria-label*="{today_year}"]
            [aria-selected="true"]
        ) *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"]
            [aria-label*="{today_year}"]
            [data-selected="true"]
        ),

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"]
            [aria-label*="{today_year}"]
            [data-selected="true"]
        ) *,

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"]
            [aria-label*="{today_year}"]
            [aria-label*="Selected"]
        ),

        body:has(div[class*="st-key-filter_date"])
        div[data-baseweb="calendar"]
        div[role="gridcell"]:has(
            [aria-label*="{today_month_en} {today_day}"]
            [aria-label*="{today_year}"]
            [aria-label*="Selected"]
        ) * {{
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
            fill: #FFFFFF !important;
            font-weight: 400 !important;
        }}
        /* =====================================================
           Ô ngày chỉ đọc
           ===================================================== */

        div[class*="st-key-filter_date"] input[readonly] {{
            cursor: pointer !important;
            caret-color: transparent !important;

            user-select: none !important;
            -webkit-user-select: none !important;
            -webkit-touch-callout: none !important;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )
    components.html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;

            /*
             * Danh sách ngày có trận, được truyền trực tiếp từ
             * matches["kickoff_date_filter"].
             */
            const matchDates = new Set(
                __WC_MATCH_DATES__
            );

            const monthNumbers = {
                january: "01",
                february: "02",
                march: "03",
                april: "04",
                may: "05",
                june: "06",
                july: "07",
                august: "08",
                september: "09",
                october: "10",
                november: "11",
                december: "12"
            };

            const inputSelector =
                'div[class*="st-key-filter_date"] input';

            /*
             * Giữ nguyên logic readonly hiện tại.
             */
            const makeInputReadonly = (input) => {
                if (
                    !input
                    || !(input instanceof parentWindow.HTMLInputElement)
                ) {
                    return;
                }

                input.readOnly = true;

                input.setAttribute("readonly", "");
                input.setAttribute("aria-readonly", "true");
                input.setAttribute("inputmode", "none");
                input.setAttribute("autocomplete", "off");
                input.setAttribute("spellcheck", "false");

                if (input.dataset.wcDateReadonlyBound === "1") {
                    return;
                }

                const preventManualEditing = (event) => {
                    event.preventDefault();
                };

                input.addEventListener(
                    "beforeinput",
                    preventManualEditing
                );

                input.addEventListener(
                    "paste",
                    preventManualEditing
                );

                input.addEventListener(
                    "drop",
                    preventManualEditing
                );

                input.dataset.wcDateReadonlyBound = "1";
            };

            /*
             * Lấy ngày thật từ aria-label của ô lịch.
             * Hỗ trợ cả aria-label nằm trên gridcell
             * và aria-label nằm trong phần tử con.
             */
            const extractDateIso = (cell) => {
                const labelledElements = [];

                if (cell.hasAttribute("aria-label")) {
                    labelledElements.push(cell);
                }

                cell
                    .querySelectorAll("[aria-label]")
                    .forEach((element) => {
                        labelledElements.push(element);
                    });

                for (const element of labelledElements) {
                    const ariaLabel =
                        element.getAttribute("aria-label") || "";

                    const dateMatch = ariaLabel.match(
                        /\\b(January|February|March|April|May|June|July|August|September|October|November|December)\\s+(\\d{1,2})(?:st|nd|rd|th)?(?:,)?\\s+(\\d{4})\\b/i
                    );

                    if (!dateMatch) {
                        continue;
                    }

                    const month =
                        monthNumbers[
                            dateMatch[1].toLowerCase()
                        ];

                    const day = String(
                        Number(dateMatch[2])
                    ).padStart(2, "0");

                    return `${dateMatch[3]}-${month}-${day}`;
                }

                return null;
            };

            /*
             * Gán font-weight dưới dạng inline !important.
             *
             * Inline !important sẽ không bị các rule hover,
             * selected hoặc today trong CSS ghi đè.
             */
            const setImportantFontWeight = (
                element,
                fontWeight
            ) => {
                if (!element) {
                    return;
                }

                const currentValue =
                    element.style.getPropertyValue(
                        "font-weight"
                    );

                const currentPriority =
                    element.style.getPropertyPriority(
                        "font-weight"
                    );

                if (
                    currentValue === fontWeight
                    && currentPriority === "important"
                ) {
                    return;
                }

                element.style.setProperty(
                    "font-weight",
                    fontWeight,
                    "important"
                );
            };

            const applyDateCellWeight = (cell) => {
                const dateIso = extractDateIso(cell);

                const isMatchDate = Boolean(
                    dateIso
                    && matchDates.has(dateIso)
                );

                const fontWeight = (
                    isMatchDate
                    ? "800"
                    : "400"
                );

                /*
                 * Xóa class từ cách triển khai cũ,
                 * tránh CSS cũ còn sót gây xung đột.
                 */
                if (
                    cell.classList.contains(
                        "wc-match-date"
                    )
                ) {
                    cell.classList.remove(
                        "wc-match-date"
                    );
                }

                cell.dataset.wcHasMatch = (
                    isMatchDate
                    ? "true"
                    : "false"
                );

                /*
                 * Áp trực tiếp lên cả ô ngày và phần tử chứa số.
                 */
                setImportantFontWeight(
                    cell,
                    fontWeight
                );

                cell
                    .querySelectorAll("*")
                    .forEach((element) => {
                        setImportantFontWeight(
                            element,
                            fontWeight
                        );
                    });
            };

            const applyCalendarEnhancements = () => {
                parentDocument
                    .querySelectorAll(inputSelector)
                    .forEach(makeInputReadonly);

                /*
                 * Chỉ xử lý calendar khi widget filter_date
                 * đang tồn tại trên trang.
                 */
                const filterDateWidget =
                    parentDocument.querySelector(
                        'div[class*="st-key-filter_date"]'
                    );

                if (!filterDateWidget) {
                    return;
                }

                parentDocument
                    .querySelectorAll(
                        'div[data-baseweb="calendar"] div[role="gridcell"]'
                    )
                    .forEach(applyDateCellWeight);
            };

            /*
             * Gom nhiều mutation liên tiếp vào một lần cập nhật.
             */
            let updateScheduled = false;

            const scheduleCalendarUpdate = () => {
                if (updateScheduled) {
                    return;
                }

                updateScheduled = true;

                parentWindow.requestAnimationFrame(() => {
                    updateScheduled = false;
                    applyCalendarEnhancements();
                });
            };

            /*
             * Dọn observer của cách triển khai cũ.
             */
            const legacyObserver =
                parentWindow.__wcMatchDateBoldObserver;

            if (legacyObserver) {
                legacyObserver.disconnect();

                try {
                    delete parentWindow.__wcMatchDateBoldObserver;
                } catch (error) {
                    parentWindow.__wcMatchDateBoldObserver = null;
                }
            }

            /*
             * Ngắt observer hiện tại trước khi tạo observer mới,
             * tránh observer bị nhân đôi sau mỗi Streamlit rerun.
             */
            const observerKey =
                "__wcFilterDateReadonlyObserver";

            const oldObserver =
                parentWindow[observerKey];

            if (oldObserver) {
                oldObserver.disconnect();
            }

            applyCalendarEnhancements();

            /*
             * Theo dõi cả việc Streamlit/BaseWeb:
             * - Mở calendar
             * - Đổi tháng
             * - Render lại ngày
             * - Thay đổi trạng thái hover/selected
             */
            const observer =
                new parentWindow.MutationObserver(
                    scheduleCalendarUpdate
                );

            observer.observe(
                parentDocument.body,
                {
                    childList: true,
                    subtree: true
                }
            );

            parentWindow[observerKey] = observer;
        })();
        </script>
        """.replace(
            "__WC_MATCH_DATES__",
            match_date_iso_js
        ),
        height=0,
        scrolling=False
    )


def inject_mobile_match_title_css():
    """
    Chỉ điều chỉnh tiêu đề trận đấu trên mobile.

    Desktop và mọi thành phần khác giữ nguyên.
    """
    st.markdown(
        """
        <style>
        /*
         * Mặc định ẩn title mobile trên desktop.
         */
        .wc-match-title-mobile {
            display: none;
        }

        @media (max-width: 768px) {
            /*
             * Chỉ trên mobile mới ẩn title desktop.
             */
            div[class*="st-key-match_title_desktop_"] {
                display: none !important;
            }

            .wc-match-title-mobile {
                display: block !important;

                width: 100% !important;
                min-width: 0 !important;
                max-width: 100% !important;

                margin: 2px 0 10px 0 !important;

                box-sizing: border-box !important;
            }

            /*
             * Cho tên đội xuống dòng đầy đủ.
             * Không còn dấu ...
             */
            .wc-match-title-mobile
            .wc-match-team {
                display: block !important;

                width: 100% !important;
                min-width: 0 !important;
                max-width: 100% !important;

                white-space: normal !important;

                overflow: visible !important;
                text-overflow: clip !important;

                word-break: normal !important;
                overflow-wrap: break-word !important;

                color: #190021 !important;

                font-size:
                    clamp(
                        17px,
                        4.7vw,
                        19px
                    ) !important;

                line-height: 1.12 !important;

                font-weight: 950 !important;

                letter-spacing:
                    -0.025em !important;
            }

            /*
             * Khoảng cách nhỏ giữa hai đội.
             */
            .wc-match-title-mobile
            .wc-match-team-home {
                margin-bottom: 1px !important;
            }

            .wc-match-title-mobile
            .wc-match-team-away {
                margin-top: 1px !important;
            }

            /*
             * Chữ VS nhỏ hơn để dành diện tích cho tên đội.
             */
            .wc-match-title-mobile
            .wc-match-vs {
                display: block !important;

                width: 100% !important;

                margin: 0 !important;

                color: #FF2882 !important;

                font-size: 13px !important;
                line-height: 1 !important;

                font-weight: 950 !important;

                letter-spacing: 0 !important;

                text-transform: uppercase;
            }
        }

        @media (max-width: 390px) {
            .wc-match-title-mobile
            .wc-match-team {
                font-size: 17px !important;
                line-height: 1.13 !important;
            }

            .wc-match-title-mobile
            .wc-match-vs {
                font-size: 12px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_desktop_match_vs_style():
    """
    Chỉ thay đổi màu và kích thước chữ 'vs' trên desktop.

    Không thay:
    - cấu trúc heading
    - khoảng cách với badge
    - khoảng cách với ribbon
    - giao diện mobile
    """
    st.markdown(
        """
        <style>
        @media (min-width: 769px) {
            div[class*="st-key-match_title_desktop_"]
            h3
            .epl-desktop-vs-only {
                display: inline;

                color: #FF2882 !important;

                font-size: 0.62em !important;
                font-weight: 950 !important;
                line-height: inherit !important;

                letter-spacing: 0 !important;

                vertical-align: 0.08em;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    components.html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;

            const headingSelector =
                'div[class*="st-key-match_title_desktop_"] h3';

            const observerKey =
                "__eplDesktopVsOnlyObserver";

            /*
             * Ngắt observer cũ sau mỗi Streamlit rerun,
             * tránh tạo nhiều observer trùng nhau.
             */
            if (parentWindow[observerKey]) {
                parentWindow[observerKey].disconnect();
            }

            const styleVsInHeading = (heading) => {
                if (
                    !heading
                    || heading.dataset.eplVsStyled === "1"
                ) {
                    return;
                }

                const walker =
                    parentDocument.createTreeWalker(
                        heading,
                        parentWindow.NodeFilter.SHOW_TEXT
                    );

                let textNode;

                while (
                    (textNode = walker.nextNode())
                ) {
                    const value =
                        textNode.nodeValue || "";

                    const matched =
                        value.match(
                            /^(.*?)(\\s+vs\\s+)(.*)$/i
                        );

                    if (!matched) {
                        continue;
                    }

                    const fragment =
                        parentDocument
                        .createDocumentFragment();

                    fragment.appendChild(
                        parentDocument.createTextNode(
                            matched[1] + " "
                        )
                    );

                    const vsSpan =
                        parentDocument.createElement(
                            "span"
                        );

                    vsSpan.className =
                        "epl-desktop-vs-only";

                    vsSpan.textContent = "vs";

                    fragment.appendChild(vsSpan);

                    fragment.appendChild(
                        parentDocument.createTextNode(
                            " " + matched[3]
                        )
                    );

                    textNode.parentNode.replaceChild(
                        fragment,
                        textNode
                    );

                    heading.dataset.eplVsStyled = "1";

                    break;
                }
            };

            const applyStyle = () => {
                parentDocument
                    .querySelectorAll(
                        headingSelector
                    )
                    .forEach(
                        styleVsInHeading
                    );
            };

            let updateScheduled = false;

            const scheduleUpdate = () => {
                if (updateScheduled) {
                    return;
                }

                updateScheduled = true;

                parentWindow.requestAnimationFrame(
                    () => {
                        updateScheduled = false;
                        applyStyle();
                    }
                );
            };

            applyStyle();

            const observer =
                new parentWindow.MutationObserver(
                    scheduleUpdate
                );

            observer.observe(
                parentDocument.body,
                {
                    childList: true,
                    subtree: true
                }
            );

            parentWindow[observerKey] = observer;
        })();
        </script>
        """,
        height=0,
        scrolling=False
    )

@st.dialog(" ")
def render_daily_checkin_dialog(user_id: int):
    reward_info = st.session_state.get("daily_checkin_reward_popup")

    if reward_info is not None:
        render_daily_checkin_reward_content(reward_info)
        return
    state = get_daily_checkin_state(user_id)

    claimed_days = set(int(day) for day in state.get("claimed_days", []))
    checked_today = bool(state.get("checked_today"))
    next_day_no = state.get("next_day_no")
    today_day_no = state.get("today_day_no")

    if checked_today and today_day_no is not None:
        claimed_days.add(int(today_day_no))

    checked_count = len(claimed_days)

    day_items_html = ""

    for day in range(1, CHECKIN_CYCLE_DAYS + 1):
        is_claimed = day in claimed_days
        is_today = (
            not checked_today
            and next_day_no is not None
            and int(next_day_no) == day
        )

        day_classes = ["wc-checkin-day"]

        if is_claimed:
            day_classes.append("wc-checkin-day-claimed")

        if is_today:
            day_classes.append("wc-checkin-day-today")

        if day in [CHECKIN_HOPE_REWARD_DAY, CHECKIN_SUPER_REWARD_DAY]:
            day_classes.append("wc-checkin-day-reward")

        day_class_text = " ".join(day_classes)

        day_icon = "✓" if is_claimed else "★"
        marker_text = "Hôm nay" if is_today else "&nbsp;"

        reward_html = ""

        if day == CHECKIN_HOPE_REWARD_DAY:
            reward_html = '<div class="wc-checkin-reward-mini">+1 Ngôi sao hy vọng</div>'

        elif day == CHECKIN_SUPER_REWARD_DAY:
            reward_html = '<div class="wc-checkin-reward-mini">+1 Siêu sao</div>'

        day_items_html += (
            f'<div class="{day_class_text}">'
            f'<div class="wc-checkin-marker">{marker_text}</div>'
            f'<div class="wc-checkin-circle">{day_icon}</div>'
            f'<div class="wc-checkin-day-label">Ngày {day}</div>'
            f'{reward_html}'
            f'</div>'
        )

    daily_checkin_html = f"""
    <style>
    div[role="dialog"]:has(.wc-daily-checkin-shell) {{
        width: min(860px, calc(100vw - 32px)) !important;
        max-width: min(860px, calc(100vw - 32px)) !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
    }}

    div[role="dialog"]:has(.wc-daily-checkin-shell) h2,
    div[role="dialog"]:has(.wc-daily-checkin-shell) [data-testid="stDialogHeader"] {{
        display: none !important;
    }}

    div[role="dialog"]:has(.wc-daily-checkin-shell) button[aria-label="Close"] {{
        color: #FFFFFF !important;
        background: rgba(255, 255, 255, 0.12) !important;
        border-radius: 999px !important;
        top: 18px !important;
        right: 18px !important;
    }}

    .wc-daily-checkin-shell {{
        position: relative;
        width: 100%;
        border-radius: 30px;
        padding: 34px 36px 30px 36px;
        background:
            radial-gradient(circle at 50% 0%, rgba(245, 197, 66, 0.18), transparent 30%),
            linear-gradient(135deg, rgba(7, 17, 31, 0.98), rgba(11, 31, 58, 0.97));
        border: 1px solid rgba(255, 255, 255, 0.16);
        box-shadow: 0 28px 70px rgba(7, 17, 31, 0.46);
        color: #F8FAFC;
        overflow: hidden;
        box-sizing: border-box;
    }}

    .wc-daily-checkin-shell::before {{
        content: "";
        position: absolute;
        left: 34px;
        right: 34px;
        top: 0;
        height: 3px;
        border-radius: 999px;
        background: linear-gradient(90deg, transparent, #F5C542, transparent);
        opacity: 0.85;
    }}

    .wc-daily-checkin-header {{
        text-align: center;
        margin-bottom: 24px;
    }}

    .wc-daily-checkin-kicker {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 6px 12px;
        border-radius: 999px;
        background: rgba(245, 197, 66, 0.10);
        border: 1px solid rgba(245, 197, 66, 0.28);
        color: #F5C542;
        font-size: 11px;
        font-weight: 900;
        letter-spacing: 0.10em;
        text-transform: uppercase;
        margin-bottom: 12px;
    }}

    .wc-daily-checkin-title {{
        color: #F8FAFC;
        font-size: 30px;
        font-weight: 950;
        letter-spacing: -0.04em;
        line-height: 1.15;
    }}

    .wc-daily-checkin-subtitle {{
        color: #CBD5E1;
        font-size: 15px;
        line-height: 1.5;
        margin-top: 8px;
    }}

    .wc-daily-checkin-progress {{
        margin: 16px auto 0 auto;
        width: min(420px, 100%);
        height: 8px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.10);
        overflow: hidden;
        border: 1px solid rgba(255, 255, 255, 0.08);
    }}

    .wc-daily-checkin-progress-fill {{
        width: calc({checked_count} / 7 * 100%);
        height: 100%;
        border-radius: 999px;
        background: linear-gradient(90deg, #F5C542, #FFD761);
        box-shadow: 0 0 18px rgba(245, 197, 66, 0.28);
    }}

    .wc-daily-checkin-days {{
        display: grid;
        grid-template-columns: repeat(7, minmax(0, 1fr));
        gap: 10px;
        align-items: start;
        padding: 22px 0 14px 0;
    }}

    .wc-checkin-day {{
        position: relative;
        min-width: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-start;
    }}

    .wc-checkin-marker {{
        height: 20px;
        margin-bottom: 6px;
        color: #07111F;
        background: transparent;
        font-size: 10px;
        font-weight: 950;
        line-height: 20px;
        white-space: nowrap;
    }}

    .wc-checkin-day-today .wc-checkin-marker {{
        padding: 0 8px;
        border-radius: 999px;
        background: #F5C542;
        color: #07111F;
        box-shadow: 0 8px 18px rgba(245, 197, 66, 0.24);
    }}

    .wc-checkin-circle {{
        width: 48px;
        height: 48px;
        border-radius: 999px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(15, 23, 42, 0.40);
        border: 1.5px solid rgba(255, 255, 255, 0.24);
        color: rgba(255, 255, 255, 0.42);
        font-size: 22px;
        font-weight: 950;
        line-height: 1;
        box-sizing: border-box;
    }}

    .wc-checkin-day-today .wc-checkin-circle {{
        background: rgba(245, 197, 66, 0.08);
        border-color: rgba(245, 197, 66, 0.78);
        color: #F5C542;
        box-shadow: 0 0 0 4px rgba(245, 197, 66, 0.08);
    }}

    .wc-checkin-day-claimed .wc-checkin-circle {{
        background: linear-gradient(135deg, #F5C542, #FFD761);
        border-color: rgba(245, 197, 66, 0.95);
        color: #07111F;
        box-shadow: 0 0 20px rgba(245, 197, 66, 0.34);
    }}

    .wc-checkin-day-label {{
        margin-top: 9px;
        color: #CBD5E1;
        font-size: 13px;
        font-weight: 850;
        white-space: nowrap;
    }}

    .wc-checkin-day-claimed .wc-checkin-day-label,
    .wc-checkin-day-today .wc-checkin-day-label {{
        color: #F5C542;
    }}

    .wc-checkin-reward-mini {{
        margin-top: 7px;
        min-height: 26px;
        color: #F5C542;
        font-size: 10.5px;
        font-weight: 850;
        line-height: 1.25;
        text-align: center;
        max-width: 90px;
    }}

    .wc-checkin-reward-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
        margin: 18px auto 18px auto;
        max-width: 520px;
    }}

    .wc-checkin-reward-card {{
        border: 1px solid rgba(245, 197, 66, 0.36);
        border-radius: 16px;
        padding: 12px 14px;
        text-align: center;
        color: #F5C542;
        font-size: 13.5px;
        font-weight: 850;
        background: rgba(245, 197, 66, 0.06);
    }}

    .wc-checkin-note {{
        color: #CBD5E1;
        font-size: 13px;
        text-align: center;
        margin-top: 8px;
        line-height: 1.45;
    }}

    div[class*="st-key-daily_checkin_claim_"],
    div[class*="st-key-daily_checkin_done_"] {{
        width: min(860px, calc(100vw - 32px)) !important;
        margin: 14px auto 0 auto !important;
    }}

    div[class*="st-key-daily_checkin_claim_"] button {{
        width: 100% !important;
        min-height: 54px !important;
        border-radius: 999px !important;
        border: none !important;
        background: linear-gradient(135deg, #F5C542, #FFD761) !important;
        color: #07111F !important;
        font-size: 18px !important;
        font-weight: 950 !important;
        box-shadow: 0 14px 34px rgba(245, 197, 66, 0.24) !important;
    }}

    div[class*="st-key-daily_checkin_claim_"] button:hover {{
        transform: translateY(-1px) !important;
        filter: brightness(1.02) !important;
    }}

    div[class*="st-key-daily_checkin_done_"] button {{
        width: 100% !important;
        min-height: 54px !important;
        border-radius: 999px !important;
        border: 1px solid rgba(255, 255, 255, 0.18) !important;
        background: rgba(255, 255, 255, 0.10) !important;
        color: #CBD5E1 !important;
        font-size: 16px !important;
        font-weight: 850 !important;
        box-shadow: none !important;
    }}

    @media (max-width: 768px) {{
        div[role="dialog"]:has(.wc-daily-checkin-shell) {{
            width: min(390px, calc(100vw - 24px)) !important;
            max-width: min(390px, calc(100vw - 24px)) !important;
        }}

        .wc-daily-checkin-shell {{
            padding: 28px 18px 24px 18px !important;
            border-radius: 24px !important;
        }}

        .wc-daily-checkin-title {{
            font-size: 25px;
        }}

        .wc-daily-checkin-days {{
            grid-template-columns: repeat(7, 62px);
            overflow-x: auto;
            justify-content: flex-start;
            padding-bottom: 12px;
        }}

        .wc-checkin-circle {{
            width: 48px;
            height: 48px;
        }}

        .wc-checkin-reward-grid {{
            grid-template-columns: 1fr;
            max-width: 100%;
        }}

        div[class*="st-key-daily_checkin_claim_"],
        div[class*="st-key-daily_checkin_done_"] {{
            width: min(390px, calc(100vw - 24px)) !important;
        }}
    }}
    </style>

    <div class="wc-daily-checkin-shell">
        <div class="wc-daily-checkin-header">
            <div class="wc-daily-checkin-kicker">7 ngày rực cháy</div>
            <div class="wc-daily-checkin-title">Điểm danh hàng ngày</div>
            <div class="wc-daily-checkin-subtitle">
                Điểm danh mỗi ngày để tích lũy phần thưởng.
            </div>

            <div class="wc-daily-checkin-progress">
                <div class="wc-daily-checkin-progress-fill"></div>
            </div>
        </div>

        <div class="wc-daily-checkin-days">
            {day_items_html}
        </div>

        <div class="wc-checkin-reward-grid">
            <div class="wc-checkin-reward-card">Ngày 5: +1 Ngôi sao hy vọng</div>
            <div class="wc-checkin-reward-card">Ngày 7: +1 Siêu sao</div>
        </div>

        <div class="wc-checkin-note">
            Sau khi hoàn thành 7 ngày, chu kỳ sẽ tự động bắt đầu lại.
        </div>
    </div>
    """

    if hasattr(st, "html"):
        st.html(daily_checkin_html)
    else:
        components.html(daily_checkin_html, height=620, scrolling=True)

    if not checked_today and next_day_no is not None:
        claim_clicked = st.button(
            "Điểm danh ngay",
            key=f"daily_checkin_claim_{user_id}_{state['cycle_no']}_{next_day_no}",
            use_container_width=True
        )

        if claim_clicked:
            result = claim_daily_checkin(user_id)
        
            if result.get("reward_type") is not None:
                st.session_state["daily_checkin_reward_popup"] = result
            else:
                st.session_state["daily_checkin_after_claim"] = True
        
            rerun_full_app()

    else:
        st.button(
            "Đã điểm danh hôm nay",
            key=f"daily_checkin_done_{user_id}_{today_vietnam_date()}",
            use_container_width=True,
            disabled=True
        )


@st.dialog(" ")
def render_daily_checkin_reward_dialog(reward_info: dict):
    reward_label = str(reward_info.get("reward_label") or "")
    reward_type = normalize_star_type(reward_info.get("reward_type"))
    day_no = int(reward_info.get("day_no") or 0)

    safe_reward_label = html.escape(reward_label)

    reward_symbol = "✦" if reward_type == STAR_TYPE_SUPER else "★"

    daily_reward_html = f"""
    <style>
    div[role="dialog"]:has(.wc-daily-reward-shell) {{
        width: min(560px, calc(100vw - 32px)) !important;
        max-width: min(560px, calc(100vw - 32px)) !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
    }}

    div[role="dialog"]:has(.wc-daily-reward-shell) h2,
    div[role="dialog"]:has(.wc-daily-reward-shell) [data-testid="stDialogHeader"] {{
        display: none !important;
    }}

    div[role="dialog"]:has(.wc-daily-reward-shell) button[aria-label="Close"] {{
        color: #FFFFFF !important;
        background: rgba(255, 255, 255, 0.12) !important;
        border-radius: 999px !important;
        top: 18px !important;
        right: 18px !important;
    }}

    .wc-daily-reward-shell {{
        border-radius: 28px;
        padding: 38px 34px 30px 34px;
        background:
            radial-gradient(circle at 50% 0%, rgba(245, 197, 66, 0.24), transparent 30%),
            linear-gradient(135deg, rgba(7, 17, 31, 0.98), rgba(11, 31, 58, 0.97));
        border: 1px solid rgba(255, 255, 255, 0.16);
        box-shadow: 0 28px 70px rgba(7, 17, 31, 0.46);
        color: #F8FAFC;
        text-align: center;
        overflow: hidden;
        box-sizing: border-box;
    }}

    .wc-daily-reward-orb {{
        width: 84px;
        height: 84px;
        margin: 0 auto 18px auto;
        border-radius: 999px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: linear-gradient(135deg, #F5C542, #FFD761);
        color: #07111F;
        font-size: 42px;
        font-weight: 950;
        box-shadow:
            0 0 0 8px rgba(245, 197, 66, 0.10),
            0 0 32px rgba(245, 197, 66, 0.32);
    }}

    .wc-daily-reward-title {{
        color: #F8FAFC;
        font-size: 32px;
        font-weight: 950;
        line-height: 1.12;
        letter-spacing: -0.04em;
        margin-bottom: 10px;
    }}

    .wc-daily-reward-subtitle {{
        color: #CBD5E1;
        font-size: 15.5px;
        line-height: 1.55;
        margin-bottom: 18px;
    }}

    .wc-daily-reward-card {{
        max-width: 420px;
        margin: 0 auto 24px auto;
        border: 1px solid rgba(245, 197, 66, 0.62);
        border-radius: 18px;
        padding: 16px 18px;
        background: rgba(245, 197, 66, 0.08);
        box-shadow: 0 0 28px rgba(245, 197, 66, 0.14);
    }}

    .wc-daily-reward-name {{
        color: #F5C542;
        font-size: 20px;
        font-weight: 950;
        line-height: 1.2;
    }}

    .wc-daily-reward-note {{
        color: #CBD5E1;
        font-size: 14px;
        margin-top: 6px;
    }}

    div[class*="st-key-daily_reward_confirm"] {{
        width: min(560px, calc(100vw - 32px)) !important;
        margin: 14px auto 0 auto !important;
    }}

    div[class*="st-key-daily_reward_confirm"] button {{
        width: 100% !important;
        min-height: 54px !important;
        border-radius: 999px !important;
        border: none !important;
        background: linear-gradient(135deg, #F5C542, #FFD761) !important;
        color: #07111F !important;
        font-size: 18px !important;
        font-weight: 950 !important;
        box-shadow: 0 14px 34px rgba(245, 197, 66, 0.24) !important;
    }}

    div[class*="st-key-daily_reward_confirm"] button:hover {{
        transform: translateY(-1px) !important;
        filter: brightness(1.02) !important;
    }}
    </style>

    <div class="wc-daily-reward-shell">
        <div class="wc-daily-reward-orb">{reward_symbol}</div>
        <div class="wc-daily-reward-title">Phần thưởng đã nhận</div>

        <div class="wc-daily-reward-subtitle">
            Bạn đã điểm danh đủ <b style="color:#F5C542;">{day_no} ngày</b>
            trong chu kỳ hiện tại.
        </div>

        <div class="wc-daily-reward-card">
            <div class="wc-daily-reward-name">{safe_reward_label}</div>
            <div class="wc-daily-reward-note">Đã được cộng vào kho bổ trợ của bạn</div>
        </div>
    </div>
    """

    if hasattr(st, "html"):
        st.html(daily_reward_html)
    else:
        components.html(daily_reward_html, height=430, scrolling=False)

    if st.button(
        "Hoàn tất",
        key="daily_reward_confirm",
        use_container_width=True
    ):
        st.rerun()

def render_daily_checkin_reward_content(reward_info: dict):
    reward_label = str(reward_info.get("reward_label") or "")
    reward_type = normalize_star_type(reward_info.get("reward_type"))
    day_no = int(reward_info.get("day_no") or 0)

    safe_reward_label = html.escape(reward_label)
    reward_symbol = "✦" if reward_type == STAR_TYPE_SUPER else "★"

    daily_reward_html = f"""
    <style>
    .wc-daily-reward-shell {{
        border-radius: 28px;
        padding: 38px 34px 30px 34px;
        background:
            radial-gradient(circle at 50% 0%, rgba(245, 197, 66, 0.24), transparent 30%),
            linear-gradient(135deg, rgba(7, 17, 31, 0.98), rgba(11, 31, 58, 0.97));
        border: 1px solid rgba(255, 255, 255, 0.16);
        box-shadow: 0 28px 70px rgba(7, 17, 31, 0.46);
        color: #F8FAFC;
        text-align: center;
        overflow: hidden;
        box-sizing: border-box;
    }}

    .wc-daily-reward-orb {{
        width: 84px;
        height: 84px;
        margin: 0 auto 18px auto;
        border-radius: 999px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: linear-gradient(135deg, #F5C542, #FFD761);
        color: #07111F;
        font-size: 42px;
        font-weight: 950;
        box-shadow:
            0 0 0 8px rgba(245, 197, 66, 0.10),
            0 0 32px rgba(245, 197, 66, 0.32);
    }}

    .wc-daily-reward-title {{
        color: #F8FAFC;
        font-size: 32px;
        font-weight: 950;
        line-height: 1.12;
        letter-spacing: -0.04em;
        margin-bottom: 10px;
    }}

    .wc-daily-reward-subtitle {{
        color: #CBD5E1;
        font-size: 15.5px;
        line-height: 1.55;
        margin-bottom: 18px;
    }}

    .wc-daily-reward-card {{
        max-width: 420px;
        margin: 0 auto 24px auto;
        border: 1px solid rgba(245, 197, 66, 0.62);
        border-radius: 18px;
        padding: 16px 18px;
        background: rgba(245, 197, 66, 0.08);
        box-shadow: 0 0 28px rgba(245, 197, 66, 0.14);
    }}

    .wc-daily-reward-name {{
        color: #F5C542;
        font-size: 20px;
        font-weight: 950;
        line-height: 1.2;
    }}

    .wc-daily-reward-note {{
        color: #CBD5E1;
        font-size: 14px;
        margin-top: 6px;
    }}

    div[class*="st-key-daily_reward_confirm"] button {{
        width: 100% !important;
        min-height: 54px !important;
        border-radius: 999px !important;
        border: none !important;
        background: linear-gradient(135deg, #F5C542, #FFD761) !important;
        color: #07111F !important;
        font-size: 18px !important;
        font-weight: 950 !important;
        box-shadow: 0 14px 34px rgba(245, 197, 66, 0.24) !important;
    }}
    </style>

    <div class="wc-daily-reward-shell">
        <div class="wc-daily-reward-orb">{reward_symbol}</div>
        <div class="wc-daily-reward-title">Phần thưởng đã nhận</div>

        <div class="wc-daily-reward-subtitle">
            Bạn đã điểm danh đủ <b style="color:#F5C542;">{day_no} ngày</b>
            trong chu kỳ hiện tại.
        </div>

        <div class="wc-daily-reward-card">
            <div class="wc-daily-reward-name">{safe_reward_label}</div>
            <div class="wc-daily-reward-note">Đã được cộng vào kho bổ trợ của bạn</div>
        </div>
    </div>
    """

    if hasattr(st, "html"):
        st.html(daily_reward_html)
    else:
        components.html(daily_reward_html, height=430, scrolling=False)

    if st.button(
        "Hoàn tất",
        key="daily_reward_confirm",
        use_container_width=True
    ):
        st.session_state.pop("daily_checkin_reward_popup", None)
        st.session_state.pop("daily_checkin_after_claim", None)
        rerun_full_app()

def get_final_poster_session_keys(user_id: int) -> dict:
    user_id = int(user_id)
    today_key = today_vietnam_date().isoformat()

    return {
        "seen": f"final_poster_popup_seen_{user_id}_{today_key}",
        "blocked_by_checkin": f"final_poster_blocked_by_checkin_{user_id}_{today_key}",
        "ready_after_checkin": f"final_poster_ready_after_checkin_{user_id}_{today_key}",
    }

def maybe_render_daily_checkin_popup(user_id: int) -> bool:
    """
    Tự mở popup điểm danh lần đầu trong ngày nếu user chưa điểm danh.
    Trả về True nếu đang render popup điểm danh/phần thưởng để popup khác không mở chồng.
    """
    user_id = int(user_id)
    today_key = today_vietnam_date().isoformat()

    if st.session_state.get("daily_checkin_reward_popup") is not None:
        render_daily_checkin_dialog(user_id)
        return True

    state = get_daily_checkin_state(user_id, use_cache=True)
    prompt_seen_key = f"daily_checkin_prompt_seen_{user_id}_{today_key}"

    should_open = (
        not bool(state.get("checked_today", False))
        and not bool(st.session_state.get(prompt_seen_key, False))
    )
    
    if should_open:
        poster_keys = get_final_poster_session_keys(user_id)
    
        if (
            is_final_poster_popup_active()
            and not bool(st.session_state.get(poster_keys["seen"], False))
            and not has_seen_final_poster_today(user_id)
        ):
            st.session_state[poster_keys["blocked_by_checkin"]] = True
    
        st.session_state[prompt_seen_key] = True
        render_daily_checkin_dialog(user_id)
        return True

    return False

def is_final_poster_popup_active() -> bool:
    return (
        ENABLE_FINAL_POSTER
        and today_vietnam_date() <= FINAL_POSTER_END_DATE
    )


def has_seen_final_poster_today(user_id: int) -> bool:
    try:
        row = fetch_one(
            """
            SELECT 1
            FROM final_poster_popup_views
            WHERE user_id = :user_id
              AND popup_date = :popup_date
            LIMIT 1
            """,
            {
                "user_id": int(user_id),
                "popup_date": today_vietnam_date()
            }
        )
        return row is not None
    except Exception:
        return True


def mark_final_poster_seen_today(user_id: int) -> bool:
    try:
        execute_sql(
            """
            INSERT INTO final_poster_popup_views (
                user_id,
                popup_date
            )
            VALUES (
                :user_id,
                :popup_date
            )
            ON CONFLICT (user_id, popup_date) DO NOTHING
            """,
            {
                "user_id": int(user_id),
                "popup_date": today_vietnam_date()
            }
        )
        return True
    except Exception:
        return False


@st.dialog(" ")
def render_final_poster_popup(user_id: int):
    poster_src = resolve_asset_src(FINAL_POSTER_IMAGE_URL)
    safe_poster_src = html.escape(poster_src, quote=True)

    poster_html = f"""
    <style>
    div[role="dialog"]:has(.wc-final-poster-shell) {{
        width: min(520px, calc(100vw - 28px)) !important;
        max-width: min(520px, calc(100vw - 28px)) !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
    }}

    div[role="dialog"]:has(.wc-final-poster-shell) h2,
    div[role="dialog"]:has(.wc-final-poster-shell) [data-testid="stDialogHeader"] {{
        display: none !important;
    }}

    div[role="dialog"]:has(.wc-final-poster-shell) button[aria-label="Close"] {{
        color: #FFFFFF !important;
        background: rgba(7, 17, 31, 0.55) !important;
        border-radius: 999px !important;
        top: 14px !important;
        right: 14px !important;
    }}

    .wc-final-poster-shell {{
        width: 100%;
        border-radius: 0;
        padding: 0;
        background: transparent;
        border: none;
        box-shadow: none;
        box-sizing: border-box;
    }}
    
    .wc-final-poster-image {{
        display: block;
        width: 100%;
        height: auto;
        border-radius: 22px;
    }}
    div[class*="st-key-final_poster_close_"] button {{
        width: 100% !important;
        min-height: 50px !important;
        border-radius: 999px !important;
        border: none !important;
        background: linear-gradient(135deg, #F5C542, #FFD761) !important;
        color: #07111F !important;
        font-weight: 950 !important;
    }}
    </style>

    <div class="wc-final-poster-shell">
        <img class="wc-final-poster-image" src="{safe_poster_src}" alt="Final poster">
    </div>
    """

    if hasattr(st, "html"):
        st.html(poster_html)
    else:
        components.html(poster_html, height=720, scrolling=True)

def maybe_render_final_poster_popup(user_id: int) -> bool:
    user_id = int(user_id)
    today_key = today_vietnam_date().isoformat()
    session_key = f"final_poster_popup_seen_{user_id}_{today_key}"

    if not is_final_poster_popup_active():
        return False

    if st.session_state.get(session_key):
        return False

    if has_seen_final_poster_today(user_id):
        st.session_state[session_key] = True
        return False

    render_final_poster_popup(user_id)

    if mark_final_poster_seen_today(user_id):
        st.session_state[session_key] = True

    return True

def render_daily_checkin_shortcut_button(user_id: int):
    """
    Nút điểm danh dạng float độc lập để mở lại popup điểm danh.
    Có thể kéo nút trong vùng nội dung; vị trí không được lưu qua lần tải trang.
    Chỉ gọi hàm này ở trang Lịch thi đấu & dự đoán.
    """
    user_id = int(user_id)

    daily_checkin_icon_svg = """
    <svg xmlns="http://www.w3.org/2000/svg"
         width="24"
         height="24"
         viewBox="0 0 24 24"
         fill="none"
         stroke="currentColor"
         stroke-width="1.5"
         stroke-linecap="round"
         stroke-linejoin="round"
         class="icon icon-tabler icons-tabler-outline icon-tabler-file-check">
      <path stroke="none" d="M0 0h24v24H0z" fill="none" />
      <path d="M14 3v4a1 1 0 0 0 1 1h4" />
      <path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2" />
      <path d="M9 15l2 2l4 -4" />
    </svg>
    """

    daily_checkin_icon_base64 = base64.b64encode(
        daily_checkin_icon_svg.encode("utf-8")
    ).decode("utf-8")

    st.markdown(
        f"""
        <style>
        div[class*="st-key-daily_checkin_shortcut_button"] {{
            position: fixed !important;
            top: 148px !important;
            right: 45px !important;
            z-index: 999998 !important;

            width: 46px !important;
            height: 46px !important;
            min-width: 46px !important;
            min-height: 46px !important;
            max-width: 46px !important;
            max-height: 46px !important;

            padding: 0 !important;
            margin: 0 !important;
            overflow: visible !important;
            cursor: grab !important;
            touch-action: none !important;
            user-select: none !important;
            -webkit-user-select: none !important;
            will-change: left, top;
        }}

        div[class*="st-key-daily_checkin_shortcut_button"] button {{
            position: relative !important;

            width: 46px !important;
            height: 46px !important;
            min-width: 46px !important;
            min-height: 46px !important;
            max-width: 46px !important;
            max-height: 46px !important;

            padding: 0 !important;
            margin: 0 !important;

            border-radius: 999px !important;
            border: none !important;
            outline: none !important;

            background: rgba(255, 255, 255, 0.96) !important;

            box-shadow:
                0 10px 24px rgba(7, 17, 31, 0.14),
                0 0 0 1px rgba(15, 23, 42, 0.06) !important;

            color: transparent !important;
            font-size: 0 !important;
            line-height: 0 !important;

            display: flex !important;
            align-items: center !important;
            justify-content: center !important;

            cursor: grab !important;
            overflow: visible !important;
            touch-action: none !important;
            user-select: none !important;
            -webkit-user-select: none !important;

            transition:
                box-shadow 0.18s ease,
                background 0.18s ease !important;
        }}

        div[class*="st-key-daily_checkin_shortcut_button"] button::before {{
            content: "";
            display: block;

            width: 23px;
            height: 23px;

            background: #F5C542;

            -webkit-mask: url("data:image/svg+xml;base64,{daily_checkin_icon_base64}") center / contain no-repeat;
            mask: url("data:image/svg+xml;base64,{daily_checkin_icon_base64}") center / contain no-repeat;

            pointer-events: none;
        }}

        div[class*="st-key-daily_checkin_shortcut_button"] button::after {{
            content: "Điểm danh";
            position: absolute;
            right: 58px;
            top: 50%;
            transform: translateY(-50%) translateX(8px);

            opacity: 0;
            pointer-events: none;

            padding: 8px 11px;
            border-radius: 999px;

            background: rgba(7, 17, 31, 0.94);
            color: #F8FAFC;

            font-size: 12px;
            font-weight: 850;
            line-height: 1;
            white-space: nowrap;

            box-shadow: 0 10px 24px rgba(7, 17, 31, 0.22);

            transition:
                opacity 0.18s ease,
                transform 0.18s ease;
        }}

        div[class*="st-key-daily_checkin_shortcut_button"] button:hover {{
            background: #FFFFFF !important;

            box-shadow:
                0 14px 30px rgba(7, 17, 31, 0.18),
                0 0 0 4px rgba(245, 197, 66, 0.12) !important;
        }}

        div[class*="st-key-daily_checkin_shortcut_button"] button:hover::after {{
            opacity: 1;
            transform: translateY(-50%) translateX(0);
        }}

        div[class*="st-key-daily_checkin_shortcut_button"] button:active {{
            cursor: grabbing !important;
        }}

        div[class*="st-key-daily_checkin_shortcut_button"].epl-checkin-dragging,
        div[class*="st-key-daily_checkin_shortcut_button"].epl-checkin-dragging * {{
            cursor: grabbing !important;
        }}

        div[class*="st-key-daily_checkin_shortcut_button"].epl-checkin-dragging
        button {{
            transition: none !important;
            box-shadow:
                0 16px 34px rgba(7, 17, 31, 0.22),
                0 0 0 5px rgba(245, 197, 66, 0.14) !important;
        }}

        div[class*="st-key-daily_checkin_shortcut_button"] button * {{
            display: none !important;
            visibility: hidden !important;
            color: transparent !important;
            font-size: 0 !important;
            line-height: 0 !important;
        }}

        @media (max-width: 768px) {{
            div[class*="st-key-daily_checkin_shortcut_button"] {{
                top: 77px !important;
                right: 5px !important;

                width: 40px !important;
                height: 40px !important;
                min-width: 40px !important;
                min-height: 40px !important;
                max-width: 40px !important;
                max-height: 40px !important;
            }}

            div[class*="st-key-daily_checkin_shortcut_button"] button {{
                width: 40px !important;
                height: 40px !important;
                min-width: 40px !important;
                min-height: 40px !important;
                max-width: 40px !important;
                max-height: 40px !important;

                border: none !important;
                outline: none !important;
            }}

            div[class*="st-key-daily_checkin_shortcut_button"] button::before {{
                width: 20px;
                height: 20px;
            }}

            div[class*="st-key-daily_checkin_shortcut_button"] button::after {{
                display: none !important;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

    shortcut_clicked = st.button(
        "Mở điểm danh",
        key="daily_checkin_shortcut_button",
        help="Xem điểm danh hàng ngày"
    )

    checkin_drag_script = """
    <script>
    (() => {
        const controllerName =
            "__eplCheckinDragController";

        const oldController =
            window[controllerName];

        if (
            oldController
            && typeof oldController.cleanup
                === "function"
        ) {
            oldController.cleanup();
        }

        const shell =
            document.querySelector(
                'div[class*="st-key-'
                + 'daily_checkin_shortcut_button"]'
            );

        if (!shell) {
            return;
        }

        const button =
            shell.querySelector("button");

        if (!button) {
            return;
        }

        const edgeGap = 8;
        const headerGap = 6;
        const dragThreshold = 6;

        let activePointer = null;
        let dragStarted = false;
        let suppressClickUntil = 0;
        let resizeFrame = 0;
        let cleaned = false;

        const getVisibleRect = (
            element
        ) => {
            if (!element) {
                return null;
            }

            const style =
                window.getComputedStyle(element);

            if (
                style.display === "none"
                || style.visibility === "hidden"
            ) {
                return null;
            }

            const rect =
                element.getBoundingClientRect();

            if (
                rect.width <= 0
                || rect.height <= 0
            ) {
                return null;
            }

            return rect;
        };

        const getHeaderRect = () => {
            const candidates =
                document.querySelectorAll(
                    'header[data-testid="stHeader"], '
                    + '[data-testid="stHeader"]'
                );

            for (const candidate of candidates) {
                const rect =
                    getVisibleRect(candidate);

                if (rect) {
                    return rect;
                }
            }

            return null;
        };

        const getMovementBounds = () => {
            const shellRect =
                shell.getBoundingClientRect();

            const headerRect =
                getHeaderRect();

            const minimumTop =
                headerRect
                ? Math.ceil(
                    headerRect.bottom
                    + headerGap
                )
                : edgeGap;

            const maxLeft =
                Math.max(
                    edgeGap,
                    window.innerWidth
                    - shellRect.width
                    - edgeGap
                );

            const maxTop =
                Math.max(
                    edgeGap,
                    window.innerHeight
                    - shellRect.height
                    - edgeGap
                );

            return {
                minLeft: edgeGap,
                minTop: Math.min(
                    Math.max(
                        edgeGap,
                        minimumTop
                    ),
                    maxTop
                ),
                maxLeft,
                maxTop
            };
        };

        const clampNumber = (
            value,
            minimum,
            maximum
        ) => Math.min(
            Math.max(
                Number.isFinite(Number(value))
                    ? Number(value)
                    : minimum,
                minimum
            ),
            maximum
        );

        const applyPosition = (
            proposedLeft,
            proposedTop
        ) => {
            const bounds =
                getMovementBounds();

            const left =
                clampNumber(
                    proposedLeft,
                    bounds.minLeft,
                    bounds.maxLeft
                );

            const top =
                clampNumber(
                    proposedTop,
                    bounds.minTop,
                    bounds.maxTop
                );

            shell.style.setProperty(
                "left",
                left + "px",
                "important"
            );

            shell.style.setProperty(
                "top",
                top + "px",
                "important"
            );

            shell.style.setProperty(
                "right",
                "auto",
                "important"
            );

            shell.style.setProperty(
                "bottom",
                "auto",
                "important"
            );
        };

        const stopDragging = (
            event
        ) => {
            if (!activePointer) {
                return;
            }

            if (
                event
                && event.pointerId
                    !== activePointer.pointerId
            ) {
                return;
            }

            if (dragStarted) {
                suppressClickUntil =
                    Date.now() + 500;

                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
            }

            activePointer = null;
            dragStarted = false;

            shell.classList.remove(
                "epl-checkin-dragging"
            );
        };

        const onPointerDown = (
            event
        ) => {
            if (
                event.button !== undefined
                && event.button !== 0
            ) {
                return;
            }

            const shellRect =
                shell.getBoundingClientRect();

            activePointer = {
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                startLeft: shellRect.left,
                startTop: shellRect.top
            };

            dragStarted = false;
        };

        const onPointerMove = (
            event
        ) => {
            if (
                !activePointer
                || event.pointerId
                    !== activePointer.pointerId
            ) {
                return;
            }

            const deltaX =
                event.clientX
                - activePointer.startX;

            const deltaY =
                event.clientY
                - activePointer.startY;

            if (
                !dragStarted
                && Math.hypot(
                    deltaX,
                    deltaY
                ) < dragThreshold
            ) {
                return;
            }

            dragStarted = true;

            shell.classList.add(
                "epl-checkin-dragging"
            );

            event.preventDefault();
            event.stopPropagation();

            applyPosition(
                activePointer.startLeft
                    + deltaX,
                activePointer.startTop
                    + deltaY
            );
        };

        const onPointerUp = (
            event
        ) => {
            stopDragging(event);
        };

        const onPointerCancel = (
            event
        ) => {
            stopDragging(event);
        };

        const onClickCapture = (
            event
        ) => {
            if (
                Date.now()
                >= suppressClickUntil
            ) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
        };

        const keepInsideAllowedArea = () => {
            cancelAnimationFrame(
                resizeFrame
            );

            resizeFrame =
                requestAnimationFrame(
                    () => {
                        const currentRect =
                            shell
                                .getBoundingClientRect();

                        applyPosition(
                            currentRect.left,
                            currentRect.top
                        );
                    }
                );
        };

        const cleanup = () => {
            if (cleaned) {
                return;
            }

            cleaned = true;

            cancelAnimationFrame(
                resizeFrame
            );

            button.removeEventListener(
                "pointerdown",
                onPointerDown
            );

            document.removeEventListener(
                "pointermove",
                onPointerMove,
                true
            );

            document.removeEventListener(
                "pointerup",
                onPointerUp,
                true
            );

            document.removeEventListener(
                "pointercancel",
                onPointerCancel,
                true
            );

            shell.removeEventListener(
                "click",
                onClickCapture,
                true
            );

            window.removeEventListener(
                "resize",
                keepInsideAllowedArea
            );

            if (window.visualViewport) {
                window.visualViewport
                    .removeEventListener(
                        "resize",
                        keepInsideAllowedArea
                    );
            }
        };

        button.setAttribute(
            "title",
            "Xem điểm danh"
        );

        button.setAttribute(
            "aria-label",
            "Xem điểm danh; giữ và kéo "
            + "để di chuyển nút"
        );

        button.addEventListener(
            "pointerdown",
            onPointerDown
        );

        document.addEventListener(
            "pointermove",
            onPointerMove,
            {
                capture: true,
                passive: false
            }
        );

        document.addEventListener(
            "pointerup",
            onPointerUp,
            true
        );

        document.addEventListener(
            "pointercancel",
            onPointerCancel,
            true
        );

        shell.addEventListener(
            "click",
            onClickCapture,
            true
        );

        window.addEventListener(
            "resize",
            keepInsideAllowedArea,
            { passive: true }
        );

        if (window.visualViewport) {
            window.visualViewport
                .addEventListener(
                    "resize",
                    keepInsideAllowedArea,
                    { passive: true }
                );
        }

        window[controllerName] = {
            cleanup
        };
    })();
    </script>
    """

    st.html(
        checkin_drag_script,
        unsafe_allow_javascript=True
    )
    
    if shortcut_clicked:
        render_daily_checkin_dialog(user_id)

def inject_mobile_goal_scorer_button_css():
    """
    Nút tròn mở/đóng timeline cầu thủ ghi bàn.
    """
    st.markdown(
        """
        <style>
        div[class*="st-key-goal_scorers_button_"] {
            display: flex !important;

            width: 100% !important;

            align-items: center !important;
            justify-content: center !important;

            margin: 2px auto 10px !important;
            text-align: center !important;
        }

        div[class*="st-key-goal_scorers_button_"]
        [data-testid="stButton"],
        div[class*="st-key-goal_scorers_button_"]
        .stButton {
            display: flex !important;

            width: 100% !important;

            align-items: center !important;
            justify-content: center !important;
        }

        div[class*="st-key-goal_scorers_button_"] button {
            display: inline-flex !important;

            width: 38px !important;
            height: 38px !important;

            min-width: 38px !important;
            min-height: 38px !important;
            max-width: 38px !important;
            max-height: 38px !important;

            box-sizing: border-box !important;
            flex: 0 0 38px !important;

            align-items: center !important;
            justify-content: center !important;

            margin: 0 auto !important;
            padding: 0 !important;

            background: rgba(255, 255, 255, 0.34) !important;
            color: #6F3B76 !important;

            border: 1px solid rgba(55, 0, 60, 0.16) !important;
            border-radius: 50% !important;

            box-shadow: none !important;

            font-family: Arial, sans-serif !important;
            font-size: 30px !important;
            font-weight: 400 !important;
            line-height: 1 !important;

            transition:
                background-color 150ms ease,
                border-color 150ms ease,
                color 150ms ease !important;
        }

        div[class*="st-key-goal_scorers_button_"]
        button [data-testid="stMarkdownContainer"] {
            display: flex !important;

            width: 100% !important;
            height: 100% !important;

            align-items: center !important;
            justify-content: center !important;

            margin: 0 !important;
            padding: 0 !important;
        }

        div[class*="st-key-goal_scorers_button_"] button p,
        div[class*="st-key-goal_scorers_button_"] button span {
            display: flex !important;

            width: 100% !important;
            height: 100% !important;

            align-items: center !important;
            justify-content: center !important;

            margin: 0 !important;
            padding: 0 !important;

            color: inherit !important;

            font-family: Arial, sans-serif !important;
            font-size: 30px !important;
            font-weight: 400 !important;
            line-height: 1 !important;
            text-align: center !important;

            transform: none !important;
        }

        div[class*="st-key-goal_scorers_button_"]
        button::before,
        div[class*="st-key-goal_scorers_button_"]
        button::after {
            content: none !important;
            display: none !important;
        }

        div[class*="st-key-goal_scorers_button_"] button:hover {
            background: #FF2882 !important;
            color: #FFFFFF !important;

            border-color: #FF2882 !important;

            box-shadow: none !important;
            transform: none !important;
        }

        div[class*="st-key-goal_scorers_button_"] button:active {
            background: #D91E6D !important;
            color: #FFFFFF !important;

            box-shadow: none !important;
            transform: none !important;
        }

        div[class*="st-key-goal_scorers_button_"] button:focus-visible {
            outline: 3px solid rgba(255, 40, 130, 0.20) !important;
            outline-offset: 2px !important;

            box-shadow: none !important;
        }

        @media (max-width: 768px) {
            div[class*="st-key-goal_scorers_button_"] {
                margin-bottom: 8px !important;
            }

            div[class*="st-key-goal_scorers_button_"] button {
                width: 36px !important;
                height: 36px !important;

                min-width: 36px !important;
                min-height: 36px !important;
                max-width: 36px !important;
                max-height: 36px !important;

                flex-basis: 36px !important;
            }

            div[class*="st-key-goal_scorers_button_"] button p,
            div[class*="st-key-goal_scorers_button_"] button span {
                font-size: 28px !important;
                font-weight: 400 !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_mobile_goal_scorer_panel_css():
    """
    Timeline bàn thắng chung của hai đội.
    Mỗi bàn thắng chiếm một hàng theo đúng thứ tự thời gian.
    """
    st.markdown(
        """
        <style>
        .wc-goal-scorers-grid {
            position: relative;

            display: flex;

            width: min(100%, 680px);

            box-sizing: border-box;

            flex-direction: column;

            gap: 5px;

            margin: 0 auto 19px;
            padding: 27px 22px 5px;

            background: transparent;
            border: 0;
            box-shadow: none;
        }

        .wc-goal-scorers-grid::before {
            content: "";

            position: absolute;

            top: 19px;
            bottom: 5px;
            left: 50%;

            width: 1px;

            background: linear-gradient(
                180deg,
                transparent 0%,
                rgba(55, 0, 60, 0.18) 16%,
                rgba(55, 0, 60, 0.18) 84%,
                transparent 100%
            );

            transform: translateX(-0.5px);

            pointer-events: none;
        }

        .wc-goal-scorers-grid::after {
            content: "⚽";

            position: absolute;

            top: 0;
            left: 50%;
            z-index: 2;

            display: flex;

            width: 22px;
            height: 22px;

            align-items: center;
            justify-content: center;

            font-family:
                "Segoe UI Emoji",
                "Apple Color Emoji",
                "Noto Color Emoji",
                sans-serif;
            font-size: 18px;
            line-height: 1;

            transform: translateX(-50%);

            pointer-events: none;
        }

        .wc-goal-scorer-row {
            position: relative;

            display: grid;

            grid-template-columns:
                minmax(0, 1fr)
                1px
                minmax(0, 1fr);

            column-gap: 16px;

            width: 100%;
            min-height: 17px;

            box-sizing: border-box;

            align-items: start;
        }

        .wc-goal-scorer-axis {
            width: 1px;
            min-height: 1px;
        }

        .wc-goal-scorer-slot {
            min-width: 0;
            min-height: 1.35em;
        }

        .wc-goal-scorer-slot.is-home {
            text-align: right;
        }

        .wc-goal-scorer-slot.is-away {
            text-align: left;
        }

        .wc-goal-scorer-item {
            display: block;

            max-width: 100%;

            color: #37003C;

            font-size: 12.5px;
            font-weight: 650;
            line-height: 1.35;

            white-space: normal;
            overflow-wrap: anywhere;
        }

        .wc-goal-scorers-no-data {
            width: 100%;

            box-sizing: border-box;

            margin: 0 auto 18px;

            color: #64748B;

            font-size: 12px;
            font-weight: 650;
            line-height: 1.4;
            text-align: center;
        }

        @media (max-width: 768px) {
            .wc-goal-scorers-grid {
                gap: 4px;

                margin-bottom: 17px;
                padding:
                    24px
                    7px
                    4px;
            }

            .wc-goal-scorers-grid::before {
                top: 17px;
            }

            .wc-goal-scorers-grid::after {
                width: 20px;
                height: 20px;

                font-size: 16px;
            }

            .wc-goal-scorer-row {
                column-gap: 10px;
                min-height: 16px;
            }

            .wc-goal-scorer-item {
                font-size: 11.5px;
                line-height: 1.35;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_ai_summary_button_css():
    ai_summary_icon_svg = """
    <svg xmlns="http://www.w3.org/2000/svg"
         width="24"
         height="24"
         viewBox="0 0 24 24"
         fill="currentColor"
         class="icon icon-tabler icons-tabler-filled icon-tabler-sparkles-2">
        <path
            stroke="none"
            d="M0 0h24v24H0z"
            fill="none"
        />
        <path d="M17.964 2.733c.156 .563 .312 1 .484 1.353c.342 .71 .758 1.125 1.47 1.467c.353 .17 .79 .326 1.352 .484c.98 .276 .97 1.668 -.013 1.93a8.3 8.3 0 0 0 -1.34 .481c-.71 .342 -1.127 .757 -1.463 1.453a8 8 0 0 0 -.486 1.352c-.258 .988 -1.658 1 -1.932 .015c-.156 -.565 -.312 -1.002 -.484 -1.354c-.342 -.71 -.758 -1.124 -1.458 -1.46a8 8 0 0 0 -1.374 -.495a.4 .4 0 0 1 -.06 -.02l-.044 -.017l-.045 -.02l-.049 -.025l-.035 -.02a.4 .4 0 0 1 -.049 -.03l-.032 -.023l-.043 -.034l-.033 -.028l-.036 -.035l-.034 -.035l-.028 -.033l-.035 -.043l-.022 -.032a.4 .4 0 0 1 -.032 -.049l-.02 -.035l-.025 -.05l-.02 -.044l-.017 -.043a.4 .4 0 0 1 -.02 -.06l-.01 -.034a.5 .5 0 0 1 -.02 -.098l-.006 -.065l-.005 -.035v-.05a.4 .4 0 0 1 .003 -.085a.5 .5 0 0 1 .013 -.093a.5 .5 0 0 1 .024 -.103a.4 .4 0 0 1 .02 -.06l.017 -.044l.02 -.045l.025 -.049l.02 -.035a.4 .4 0 0 1 .03 -.049l.023 -.032l.034 -.043l.028 -.033l.035 -.036l.035 -.034q .015 -.015 .033 -.028l.043 -.035l.032 -.022a.4 .4 0 0 1 .049 -.032l.035 -.02l.05 -.025l.044 -.02l.043 -.017a.4 .4 0 0 1 .06 -.02l.027 -.008a8.3 8.3 0 0 0 1.339 -.48c.71 -.342 1.127 -.757 1.47 -1.466c.17 -.354 .327 -.792 .483 -1.355c.272 -.976 1.657 -.976 1.928 0" />
        <path d="M10.965 6.737q .219 .801 .503 1.574c.856 2.28 1.945 3.363 4.23 4.22q .708 .265 1.571 .506c.976 .272 .974 1.656 -.002 1.927q -.798 .221 -1.568 .504c-2.288 .858 -3.376 1.94 -4.229 4.216a19 19 0 0 0 -.505 1.579c-.268 .983 -1.662 .983 -1.93 0a19 19 0 0 0 -.503 -1.574c-.856 -2.281 -1.944 -3.363 -4.226 -4.219a20 20 0 0 0 -1.594 -.513a.4 .4 0 0 1 -.054 -.018l-.044 -.017l-.043 -.02a.3 .3 0 0 1 -.048 -.024l-.036 -.02a.4 .4 0 0 1 -.048 -.03l-.032 -.024l-.044 -.034l-.033 -.029l-.037 -.034l-.034 -.037l-.03 -.033l-.033 -.044l-.023 -.032a.4 .4 0 0 1 -.03 -.048l-.021 -.036a.3 .3 0 0 1 -.024 -.048l-.02 -.043l-.017 -.044a.4 .4 0 0 1 -.018 -.054a.2 .2 0 0 1 -.01 -.039a.4 .4 0 0 1 -.014 -.059l-.007 -.04l-.007 -.056l-.003 -.044l-.002 -.05v-.05q 0 -.023 .004 -.044q .001 -.03 .007 -.057l.007 -.04a.4 .4 0 0 1 .017 -.076l.007 -.021a.4 .4 0 0 1 .018 -.054l.017 -.044l.02 -.043a.3 .3 0 0 1 .024 -.048l.02 -.036a.4 .4 0 0 1 .03 -.048l.024 -.032l.034 -.044l.029 -.033l.034 -.037l.037 -.034l.033 -.03l.044 -.033l.032 -.023a.4 .4 0 0 1 .048 -.03l.036 -.021a.3 .3 0 0 1 .048 -.024l.043 -.02l.044 -.017a.4 .4 0 0 1 .054 -.018l.021 -.007a20 20 0 0 0 1.568 -.504c2.287 -.858 3.375 -1.94 4.229 -4.216a19 19 0 0 0 .505 -1.579c.268 -.983 1.662 -.983 1.93 0" />
    </svg>
    """

    ai_summary_icon_base64 = base64.b64encode(
        ai_summary_icon_svg.encode("utf-8")
    ).decode("utf-8")

    st.markdown(
        f"""
        <style>
        div[class*="st-key-ai_summary_button_"],
        div[class*="st-key-ai_suggestion_button_"] {{
            display: flex !important;
            justify-content: flex-end !important;
            width: 100% !important;

            margin-top: -25px !important;
            margin-bottom: 7px !important;
        }}

        div[class*="st-key-ai_summary_button_"] button,
        div[class*="st-key-ai_suggestion_button_"] button {{
            width: auto !important;
            min-width: 0 !important;
            height: 30px !important;
            min-height: 30px !important;

            padding: 5px 10px !important;
            margin-left: auto !important;

            border-radius: 10px !important;
            border: 1px solid rgba(166, 109, 255, 0.42) !important;

            background: rgba(255, 255, 255, 0.92) !important;
            color: #334155 !important;

            box-shadow: 0 2px 7px rgba(15, 23, 42, 0.045) !important;

            font-size: 12px !important;
            font-weight: 400 !important;
            letter-spacing: 0 !important;
            line-height: 1 !important;
            white-space: nowrap !important;

            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 5px !important;

            transition:
                border-color 0.16s ease,
                background 0.16s ease,
                box-shadow 0.16s ease,
                transform 0.16s ease !important;
        }}

        div[class*="st-key-ai_summary_button_"] button::before,
        div[class*="st-key-ai_suggestion_button_"] button::before {{
            content: "";
            display: inline-block;
            width: 18px;
            height: 18px;
            flex: 0 0 auto;

            background: linear-gradient(135deg, #6CCBFF 0%, #A855F7 100%);
            -webkit-mask: url("data:image/svg+xml;base64,{ai_summary_icon_base64}") center / contain no-repeat;
            mask: url("data:image/svg+xml;base64,{ai_summary_icon_base64}") center / contain no-repeat;
        }}

        div[class*="st-key-ai_summary_button_"] button:hover,
        div[class*="st-key-ai_suggestion_button_"] button:hover {{
            background: #FFFFFF !important;
            border-color: rgba(168, 85, 247, 0.68) !important;
            box-shadow: 0 4px 10px rgba(15, 23, 42, 0.07) !important;
            transform: translateY(-1px) !important;
            color: #1F2937 !important;
        }}

        div[class*="st-key-ai_summary_button_"] button:active,
        div[class*="st-key-ai_suggestion_button_"] button:active {{
            transform: translateY(0) scale(0.99) !important;
            box-shadow: 0 2px 6px rgba(15, 23, 42, 0.05) !important;
        }}

        div[class*="st-key-ai_summary_button_"] button *,
        div[class*="st-key-ai_suggestion_button_"] button * {{
            color: #334155 !important;
            white-space: nowrap !important;
            word-break: keep-all !important;
            overflow-wrap: normal !important;
            line-height: 1 !important;
            font-size: inherit !important;
            font-weight: 400 !important;
            letter-spacing: 0 !important;
        }}

        @media (max-width: 768px) {{
            div[class*="st-key-ai_summary_button_"],
            div[class*="st-key-ai_suggestion_button_"] {{
                margin-top: -25px !important;
                margin-bottom: -5px !important;
            }}

            div[class*="st-key-ai_summary_button_"] button,
            div[class*="st-key-ai_suggestion_button_"] button {{
                height: 28px !important;
                min-height: 28px !important;
                padding: 4px 9px !important;
                border-radius: 9px !important;
                font-size: 11.5px !important;
                gap: 4px !important;
            }}

            div[class*="st-key-ai_summary_button_"] button::before,
            div[class*="st-key-ai_suggestion_button_"] button::before {{
                width: 16px;
                height: 16px;
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
    """
    CSS bố cục riêng cho cụm nút Lưu/Cập nhật/Xóa.

    Mỗi selector nằm trong một CSS block độc lập để stylable_container
    thêm scope cho chính selector đó. Tuyệt đối không gộp các selector
    button/column vào một chuỗi CSS vì chúng có thể thoát scope.
    """
    return [
        """
        {
            width: fit-content !important;
            max-width: 100% !important;
            margin-top: 16px !important;
            margin-right: 0 !important;
            margin-bottom: 24px !important;
            margin-left: auto !important;
        }
        """,
        """
        div[data-testid="stHorizontalBlock"] {
            width: fit-content !important;
            max-width: 100% !important;
            align-items: center !important;
            flex-wrap: nowrap !important;
            gap: 9px !important;
        }
        """,
        """
        div[data-testid="stColumn"] {
            flex: 0 0 auto !important;
            width: auto !important;
            min-width: 0 !important;
        }
        """,
        """
        div[data-testid="stFormSubmitButton"] {
            width: auto !important;
            margin: 0 !important;
        }
        """
    ]

def inject_mobile_prediction_action_buttons_css():
    """
    Chỉ chỉnh bố cục cụm nút dự đoán trên mobile.

    Selector được khóa bằng key riêng của cụm hành động trong từng card,
    nên không tác động tới nút, cột hoặc form ở khu vực khác.
    """
    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            /*
             * Vỏ cụm nút chiếm hết chiều ngang khả dụng để có một
             * mép phải ổn định, nhưng các nút vẫn giữ nguyên kích thước.
             */
            div[class*="st-key-prediction_action_spacing_shell_"] {
                width: 100% !important;
                max-width: 100% !important;

                display: flex !important;
                flex-direction: column !important;
                align-items: flex-end !important;

                margin-right: 0 !important;
                margin-left: 0 !important;

                padding-right: 4px !important;
                box-sizing: border-box !important;
            }

            /*
             * Giữ hai nút trên cùng một hàng, neo cả hàng sang phải
             * và tạo khoảng cách đủ rõ để chúng không chồng chéo.
             */
            div[class*="st-key-prediction_action_spacing_shell_"]
            div[data-testid="stHorizontalBlock"] {
                width: fit-content !important;
                min-width: 0 !important;
                max-width: 100% !important;

                display: flex !important;
                flex-direction: row !important;
                flex-wrap: nowrap !important;
                justify-content: flex-end !important;
                align-items: center !important;

                gap: 18px !important;
                column-gap: 18px !important;

                margin-right: 0 !important;
                margin-left: auto !important;
            }

            /*
             * Vô hiệu hóa kích thước responsive mặc định của st.columns
             * chỉ trong cụm nút này.
             */
            div[class*="st-key-prediction_action_spacing_shell_"]
            div[data-testid="stHorizontalBlock"]
            > :is(
                div[data-testid="stColumn"],
                div[data-testid="column"]
            ) {
                width: auto !important;
                min-width: 0 !important;
                max-width: none !important;

                flex: 0 0 auto !important;

                margin: 0 !important;
                padding: 0 !important;
            }

            div[class*="st-key-prediction_action_spacing_shell_"]
            div[data-testid="stFormSubmitButton"] {
                width: auto !important;
                min-width: 0 !important;
                margin: 0 !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def get_prediction_primary_button_css():
    """
    CSS chỉ dành cho nút Lưu/Cập nhật trong đúng card trận đấu.
    Kích thước và màu sắc bám theo ảnh UI mẫu.
    """
    return [
        """
        button {
            width: auto !important;
            min-width: 0 !important;
            height: 42px !important;
            min-height: 42px !important;
            padding: 0 15px !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 8px !important;
            position: relative !important;
            overflow: hidden !important;
            border: 1px solid rgba(245, 197, 66, 0.82) !important;
            border-radius: 9px !important;
            background: linear-gradient(135deg, #37003C 0%, #53005B 100%) !important;
            color: #FFFFFF !important;
            box-shadow: 0 4px 10px rgba(55, 0, 60, 0.17) !important;
            font-size: 15px !important;
            font-weight: 800 !important;
            letter-spacing: 0.002em !important;
            line-height: 1 !important;
            white-space: nowrap !important;
            transition:
                background 0.16s ease,
                border-color 0.16s ease,
                box-shadow 0.16s ease,
                transform 0.16s ease !important;
        }
        """,
        """
        button::before {
            content: "✓";
            width: 19px;
            height: 19px;
            min-width: 19px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            background: #00FF85;
            color: #37003C;
            font-size: 12px;
            font-weight: 950;
            line-height: 1;
        }
        """,
        """
        button p {
            margin: 0 !important;
            color: inherit !important;
            font: inherit !important;
            line-height: 1 !important;
            white-space: nowrap !important;
            word-break: keep-all !important;
            overflow-wrap: normal !important;
        }
        """,
        """
        button:hover {
            border-color: #F5C542 !important;
            background: linear-gradient(135deg, #420048 0%, #65006E 100%) !important;
            color: #FFFFFF !important;
            box-shadow: 0 6px 14px rgba(55, 0, 60, 0.21) !important;
            transform: translateY(-1px) !important;
        }
        """,
        """
        button:active {
            box-shadow: 0 2px 6px rgba(55, 0, 60, 0.16) !important;
            transform: translateY(0) !important;
        }
        """,
        """
        button:focus-visible {
            outline: 3px solid rgba(245, 197, 66, 0.30) !important;
            outline-offset: 2px !important;
        }
        """
    ]

def get_prediction_delete_button_css():
    """
    CSS chỉ dành cho nút Xóa: nút icon nhỏ gọn, hơi rộng hơn chiều cao.
    """
    return [
        """
        button {
            width: 46px !important;
            min-width: 46px !important;
            max-width: 46px !important;
            height: 42px !important;
            min-height: 42px !important;
            max-height: 42px !important;
            padding: 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            position: relative !important;
            overflow: hidden !important;
            border: 1px solid rgba(244, 63, 94, 0.58) !important;
            border-radius: 9px !important;
            background: rgba(255, 255, 255, 0.72) !important;
            color: #F43F5E !important;
            box-shadow: none !important;
            font-size: 0 !important;
            line-height: 0 !important;
            transition:
                background 0.16s ease,
                border-color 0.16s ease,
                color 0.16s ease,
                box-shadow 0.16s ease,
                transform 0.16s ease !important;
        }
        """,
        """
        button::before {
            content: "";
            width: 19px;
            height: 19px;
            flex: 0 0 19px;
            display: block;
            background: currentColor;
            -webkit-mask:
                url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M3 6h18'/%3E%3Cpath d='M8 6V4h8v2'/%3E%3Cpath d='M19 6l-1 14H6L5 6'/%3E%3Cpath d='M10 11v5'/%3E%3Cpath d='M14 11v5'/%3E%3C/svg%3E")
                center / contain no-repeat;
            mask:
                url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M3 6h18'/%3E%3Cpath d='M8 6V4h8v2'/%3E%3Cpath d='M19 6l-1 14H6L5 6'/%3E%3Cpath d='M10 11v5'/%3E%3Cpath d='M14 11v5'/%3E%3C/svg%3E")
                center / contain no-repeat;
        }
        """,
        """
        button > div {
            position: absolute !important;
            width: 1px !important;
            height: 1px !important;
            padding: 0 !important;
            margin: -1px !important;
            overflow: hidden !important;
            clip: rect(0, 0, 0, 0) !important;
            white-space: nowrap !important;
            border: 0 !important;
        }
        """,
        """
        button:hover {
            border-color: rgba(225, 29, 72, 0.78) !important;
            background: rgba(255, 228, 230, 0.86) !important;
            color: #E11D48 !important;
            box-shadow: 0 4px 10px rgba(225, 29, 72, 0.12) !important;
            transform: translateY(-1px) !important;
        }
        """,
        """
        button:active {
            box-shadow: none !important;
            transform: scale(0.96) !important;
        }
        """,
        """
        button:focus-visible {
            outline: 3px solid rgba(244, 63, 94, 0.18) !important;
            outline-offset: 2px !important;
        }
        """
    ]

def inject_sidebar_menu_radio_css():
    st.markdown(
        """
        <style>
        /*
         * Nút đóng/mở sidebar phải luôn có cả biểu tượng và chữ "Menu".
         *
         * Chỉ dùng các ancestor/test-id dành riêng cho sidebar; tuyệt đối
         * không dùng :first-of-type hoặc selector button toàn cục vì các
         * selector đó có thể bắt nhầm Share, Favorite và Edit trên header.
        */
        [data-testid="stExpandSidebarButton"]:is(button),
        [data-testid="stExpandSidebarButton"] button,
        [data-testid="stSidebarCollapsedControl"]:is(button),
        [data-testid="stSidebarCollapsedControl"] button,
        [data-testid="stSidebarCollapseButton"]:is(button),
        [data-testid="stSidebarCollapseButton"] button,
        section[data-testid="stSidebar"]
        button[data-testid="stBaseButton-headerNoPadding"],
        section[data-testid="stSidebar"]
        button[kind="headerNoPadding"],
        section[data-testid="stSidebar"]
        button[aria-label*="sidebar" i] {
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 8px !important;
            width: auto !important;
            min-width: 88px !important;
            height: 38px !important;
            min-height: 38px !important;
            padding: 0 12px !important;
            overflow: visible !important;
            white-space: nowrap !important;
        }

        [data-testid="stExpandSidebarButton"]:is(button)::after,
        [data-testid="stExpandSidebarButton"] button::after,
        [data-testid="stSidebarCollapsedControl"]:is(button)::after,
        [data-testid="stSidebarCollapsedControl"] button::after,
        [data-testid="stSidebarCollapseButton"]:is(button)::after,
        [data-testid="stSidebarCollapseButton"] button::after,
        section[data-testid="stSidebar"]
        button[data-testid="stBaseButton-headerNoPadding"]::after,
        section[data-testid="stSidebar"]
        button[kind="headerNoPadding"]::after,
        section[data-testid="stSidebar"]
        button[aria-label*="sidebar" i]::after {
            content: "Menu" !important;
            display: inline-block !important;
            color: #0D2940 !important;
            font-size: 13px !important;
            font-weight: 850 !important;
            line-height: 1 !important;
            letter-spacing: 0.01em !important;
            white-space: nowrap !important;
        }

        section[data-testid="stSidebar"]
        button[data-testid="stBaseButton-headerNoPadding"]::after,
        section[data-testid="stSidebar"]
        button[kind="headerNoPadding"]::after,
        section[data-testid="stSidebar"]
        button[aria-label*="sidebar" i]::after {
            color: #F8FAFC !important;
        }

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
        logo_html = '<div class="wc-logo-fallback">EPL</div>'

    st.markdown(
        f"""
        <div class="wc-sidebar-brand">
            <div class="wc-logo-row">
                {logo_html}
                <div>
                    <div class="wc-brand-title">EPL {get_selected_season_label()}</div>
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
            <strong>Every Match. Every Point.</strong>
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
    hero_visual_src = resolve_asset_src(
        HERO_TROPHY_IMAGE_URL
    )

    if hero_visual_src:
        hero_visual = (
            f'<img class="wc-hero-img" '
            f'src="{hero_visual_src}" '
            f'alt="EPL visual">'
        )
    else:
        hero_visual = (
            '<div class="wc-hero-orb">EPL</div>'
        )

    hero_html = (
        '<div class="wc-hero">'
            '<div class="wc-hero-grid">'
                '<div>'
                    '<div class="wc-eyebrow">'
                        '⚽ PREMIER LEAGUE PREDICTION HUB'
                    '</div>'

                    '<div class="wc-hero-title">'
                        'Premier League '
                        f'<span class="wc-gold">{get_selected_season_label()}</span>'
                        '<br>'
                        'Prediction Arena'
                    '</div>'

                    '<div class="wc-hero-subtitle">'
                        f'{APP_TAGLINE}'
                    '</div>'

                    '<div class="wc-hero-actions">'
                        '<div class="wc-pill">'
                            'Bảng xếp hạng'
                        '</div>'

                        '<div class="wc-pill">'
                            'Dự đoán tỉ số'
                        '</div>'

                        '<div class="wc-pill">'
                            '38 vòng đấu'
                        '</div>'
                    '</div>'
                '</div>'

                '<div>'
                    f'{hero_visual}'
                '</div>'
            '</div>'
        '</div>'
    )

    st.markdown(
        hero_html,
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

    if matches.empty:
        finished_matches = 0
        awaiting_result_matches = 0
        open_matches = 0
    else:
        matches_for_count = matches.copy()

        matches_for_count["has_unknown_team"] = matches_for_count.apply(
            lambda row: (
                is_unknown_team(row.get("home_team_name"))
                or is_unknown_team(row.get("away_team_name"))
            ),
            axis=1
        )

        matches_for_count["is_finished_bool"] = matches_for_count["is_finished"].apply(to_bool)

        now_utc = pd.Timestamp.now(tz="UTC")

        finished_matches = int(
            matches_for_count["is_finished_bool"].sum()
        )

        awaiting_result_matches = int(
            (
                (
                    matches_for_count["kickoff_time_utc_dt"]
                    <= now_utc
                )
                & (~matches_for_count["is_finished_bool"])
            ).sum()
        )

        open_matches = int(
            (
                (matches_for_count["kickoff_time_utc_dt"] > now_utc)
                & (~matches_for_count["is_finished_bool"])
                & (~matches_for_count["has_unknown_team"])
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
                <div class="wc-kpi-label">Đang chờ kết quả</div>
                <div class="wc-kpi-value" style="color:#F59E0B;">{awaiting_result_matches}</div>
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
                Sử dụng sao để nhân điểm khi dự đoán đúng. Nếu dự đoán sai, bạn sẽ bị trừ điểm theo loại trận và loại bổ trợ. Mỗi trận chỉ được dùng tối đa 1 sao.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    # Chỉ giữ hai box bổ trợ trên cùng một hàng ở mobile.
    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            /*
             * Chỉ chọn đúng hàng chứa đồng thời hai card bổ trợ.
             * Các st.columns khác trong app không bị ảnh hưởng.
             */
            div[data-testid="stHorizontalBlock"]:has(
                div[class*="st-key-hope_star_balance_card"]
            ):has(
                div[class*="st-key-super_star_balance_card"]
            ) {
                display: grid !important;
                grid-template-columns:
                    repeat(2, minmax(0, 1fr)) !important;

                width: 100% !important;
                max-width: 100% !important;

                column-gap: 10px !important;
                row-gap: 0 !important;

                align-items: stretch !important;
            }

            /*
             * Hai cột luôn rộng bằng nhau và được phép co vừa màn hình.
             * Hỗ trợ cả cấu trúc DOM Streamlit cũ và mới.
             */
            div[data-testid="stHorizontalBlock"]:has(
                div[class*="st-key-hope_star_balance_card"]
            ):has(
                div[class*="st-key-super_star_balance_card"]
            )
            > :is(
                div[data-testid="stColumn"],
                div[data-testid="column"]
            ) {
                width: 100% !important;
                min-width: 0 !important;
                max-width: 100% !important;

                flex: none !important;

                margin: 0 !important;
                padding-left: 0 !important;
                padding-right: 0 !important;
            }
        }
        </style>
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
                    {usage["hope_left"]}/{usage.get("hope_total", HOPE_STARS_PER_USER)}
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
                    Đúng x2 • Sai -1/-2 điểm
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
                    {usage["super_left"]}/{usage.get("super_total", SUPER_STARS_PER_USER)}
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
                    Đúng x3 • Sai -2/-4 điểm
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
        with st.expander("Luật chơi", expanded=False):
            rules_html = f"""
            <style>
            .epl-scoring-rules {{
                display: flex;
                flex-direction: column;
                gap: 14px;
                padding: 4px 2px 8px;
                color: #334155;
                font-size: 14px;
                line-height: 1.45;
            }}
        
            .epl-scoring-rules .rules-heading {{
                margin-bottom: 8px;
                color: #07111F;
                font-size: 15px;
                font-weight: 900;
            }}
        
            .epl-scoring-rules .rules-grid {{
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 10px;
            }}
        
            .epl-scoring-rules .rules-card {{
                padding: 11px 12px;
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.72);
            }}
        
            .epl-scoring-rules .rules-card-title {{
                margin-bottom: 7px;
                color: #0D2940;
                font-weight: 900;
            }}
        
            .epl-scoring-rules .rules-row {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 10px;
                margin-top: 6px;
            }}
        
            .epl-scoring-rules .rules-values {{
                display: flex;
                align-items: center;
                justify-content: flex-end;
                flex-wrap: wrap;
                gap: 5px;
            }}
        
            .epl-scoring-rules .rule-pill {{
                display: inline-flex;
                align-items: center;
                min-height: 25px;
                padding: 2px 8px;
                border-radius: 999px;
                font-weight: 900;
                white-space: nowrap;
            }}
        
            .epl-scoring-rules .rule-positive {{
                color: #15803D;
                background: #DCFCE7;
            }}
        
            .epl-scoring-rules .rule-negative {{
                color: #B91C1C;
                background: #FEE2E2;
            }}
        
            .epl-scoring-rules .rule-neutral {{
                color: #64748B;
                background: #F1F5F9;
            }}
        
            .epl-scoring-rules .rules-note {{
                margin-top: 7px;
                color: #64748B;
                font-size: 12px;
            }}
        
            .epl-scoring-rules .round-rule {{
                padding: 11px 12px;
                border-radius: 12px;
                background: rgba(245, 197, 66, 0.12);
            }}
        
            @media (max-width: 640px) {{
                .epl-scoring-rules .rules-grid {{
                    grid-template-columns: 1fr;
                }}
        
                .epl-scoring-rules .rules-row {{
                    align-items: flex-start;
                }}
            }}
            </style>
        
            <div class="epl-scoring-rules">
        
                <div>
                    <div class="rules-heading">Dự đoán tỉ số</div>
        
                    <div class="rules-grid">
                        <div class="rules-card">
                            <div class="rules-card-title">Trận thường</div>
        
                            <div class="rules-row">
                                <span>Đúng tỉ số</span>
                                <span class="rule-pill rule-positive">
                                    +{NORMAL_MATCH_EXACT_POINTS}
                                </span>
                            </div>
        
                            <div class="rules-row">
                                <span>Đúng kết quả</span>
                                <span class="rule-pill rule-positive">
                                    +{NORMAL_MATCH_OUTCOME_POINTS}
                                </span>
                            </div>
        
                            <div class="rules-row">
                                <span>Sai</span>
                                <span class="rule-pill rule-neutral">0</span>
                            </div>
                        </div>
        
                        <div class="rules-card">
                            <div class="rules-card-title">
                                Big Match
                            </div>
        
                            <div class="rules-row">
                                <span>Đúng tỉ số</span>
                                <span class="rule-pill rule-positive">
                                    +{BIG_MATCH_EXACT_POINTS}
                                </span>
                            </div>
        
                            <div class="rules-row">
                                <span>Đúng kết quả</span>
                                <span class="rule-pill rule-positive">
                                    +{BIG_MATCH_OUTCOME_POINTS}
                                </span>
                            </div>
        
                            <div class="rules-row">
                                <span>Sai</span>
                                <span class="rule-pill rule-neutral">0</span>
                            </div>
                        </div>
                    </div>
        
                    <div class="rules-note">
                        Đúng kết quả = đúng thắng/hòa/thua nhưng không khớp
                        chính xác tỉ số. Big Match là trận giữa hai đội Big 6.
                    </div>
                </div>
        
                <div class="rules-grid">
                    <div class="rules-card">
                        <div class="rules-card-title">
                            ⭐ Ngôi sao hy vọng
                        </div>
        
                        <div class="rules-row">
                            <span>Đúng tỉ số/kết quả</span>
                            <span class="rule-pill rule-positive">×2 điểm</span>
                        </div>
        
                        <div class="rules-row">
                            <span>Sai</span>
                            <span class="rules-values">
                                <span class="rule-pill rule-negative">
                                    −1 thường
                                </span>
                                <span class="rule-pill rule-negative">
                                    −2 Big Match
                                </span>
                            </span>
                        </div>
                    </div>
        
                    <div class="rules-card">
                        <div class="rules-card-title">
                            ✨ Siêu sao
                        </div>
        
                        <div class="rules-row">
                            <span>Đúng tỉ số/kết quả</span>
                            <span class="rule-pill rule-positive">×3 điểm</span>
                        </div>
        
                        <div class="rules-row">
                            <span>Sai</span>
                            <span class="rules-values">
                                <span class="rule-pill rule-negative">
                                    −2 thường
                                </span>
                                <span class="rule-pill rule-negative">
                                    −4 Big Match
                                </span>
                            </span>
                        </div>
                    </div>
                </div>
        
                <div class="round-rule">
                    <div class="rules-card-title">👑 Thưởng vòng</div>
        
                    Dẫn đầu sau đủ {EPL_MATCHES_PER_ROUND} trận:
                    <span class="rule-pill rule-positive">
                        +{ROUND_CHAMPION_BONUS_POINTS} điểm
                    </span>
        
                    <div class="rules-note">
                        Đồng điểm cao nhất: tất cả cùng nhận thưởng.
                    </div>
                </div>
        
            </div>
            """
        
            st.html(rules_html)
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
                ⭐ Ngôi sao hy vọng: <b style="color:#F5C542;">{usage["hope_left"]}/{usage.get("hope_total", HOPE_STARS_PER_USER)}</b>
            </div>
            <div style="font-size:13px;color:#CBD5E1;margin-top:4px;">
                ✨ Siêu sao: <b style="color:#F5C542;">{usage["super_left"]}/{usage.get("super_total", SUPER_STARS_PER_USER)}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


DISPLAY_NAME_FEEDBACK_KEY = "display_name_feedback_popup"


def inject_display_name_ui_css():
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_row"] {
            margin: 1px 0 2px 0 !important;
        }

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_row"]
        div[data-testid="stHorizontalBlock"] {
            align-items: center !important;
            justify-content: flex-start !important;
            gap: 4px !important;
        }

        /*
         * Hai cột chỉ rộng đúng theo nội dung để biểu tượng bút nằm ngay
         * sau tên, thay vì bị đẩy ra sát mép phải của sidebar.
         */
        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_row"]
        div[data-testid="stHorizontalBlock"]
        > div[data-testid="stColumn"]:first-child {
            flex: 0 1 auto !important;
            width: auto !important;
            min-width: 0 !important;
            max-width: calc(100% - 22px) !important;
        }

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_row"]
        div[data-testid="stHorizontalBlock"]
        > div[data-testid="stColumn"]:last-child {
            flex: 0 0 18px !important;
            width: 18px !important;
            min-width: 18px !important;
        }

        section[data-testid="stSidebar"]
        .epl-sidebar-greeting {
            min-width: 0;
            overflow: hidden;
            color: #F8FAFC;
            font-size: 14px;
            line-height: 28px;
            white-space: nowrap;
            text-overflow: ellipsis;
        }

        section[data-testid="stSidebar"]
        .epl-sidebar-greeting strong {
            font-weight: 900;
            color: #FFFFFF;
        }

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"] {
            width: 18px !important;
            min-width: 18px !important;
        }

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"]
        .stButton {
            width: 18px !important;
            min-width: 18px !important;
        }

        /*
         * Nút vẫn giữ vùng bấm để mở popup, nhưng mọi thành phần tạo
         * "box" đều trong suốt. Phần nhìn thấy duy nhất là icon SVG.
         */
        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"]
        button {
            position: relative !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 18px !important;
            min-width: 18px !important;
            height: 28px !important;
            min-height: 28px !important;
            padding: 0 !important;
            margin: 0 !important;
            border: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            background-color: transparent !important;
            background-image: none !important;
            color: #CBD5E1 !important;
            box-shadow: none !important;
            filter: none !important;
            transform: none !important;
            appearance: none !important;
            -webkit-appearance: none !important;
        }

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"]
        button::before {
            content: "" !important;
            display: block !important;
            width: 14px !important;
            height: 14px !important;
            flex: 0 0 14px !important;
            background-color: currentColor !important;
            -webkit-mask:
                url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zm17.71-10.04a.996.996 0 0 0 0-1.41l-2.34-2.34a.996.996 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.87z'/%3E%3C/svg%3E")
                center / contain no-repeat !important;
            mask:
                url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zm17.71-10.04a.996.996 0 0 0 0-1.41l-2.34-2.34a.996.996 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.87z'/%3E%3C/svg%3E")
                center / contain no-repeat !important;
        }

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"]
        button::after {
            content: none !important;
            display: none !important;
        }

        /*
         * Giữ tên nút cho trình đọc màn hình nhưng không hiển thị chữ,
         * nhờ đó icon không còn phụ thuộc vào font ký tự ✎.
         */
        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"]
        button p {
            position: absolute !important;
            width: 1px !important;
            height: 1px !important;
            padding: 0 !important;
            margin: -1px !important;
            overflow: hidden !important;
            clip: rect(0, 0, 0, 0) !important;
            clip-path: inset(50%) !important;
            white-space: nowrap !important;
            border: 0 !important;
        }

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"]
        button:hover {
            border: 0 !important;
            background: transparent !important;
            background-color: transparent !important;
            color: #F5C542 !important;
            box-shadow: none !important;
            transform: none !important;
        }

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"]
        button:active {
            border: 0 !important;
            background: transparent !important;
            color: #E7B82C !important;
            box-shadow: none !important;
            transform: none !important;
        }

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"]
        button:focus,
        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"]
        button:focus-visible {
            border: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"]
        button:focus {
            outline: none !important;
        }

        section[data-testid="stSidebar"]
        div[class*="st-key-sidebar_display_name_edit"]
        button:focus-visible {
            outline: 1px solid rgba(245, 197, 66, 0.82) !important;
            outline-offset: 1px !important;
        }

        div[role="dialog"]:has(.epl-display-name-dialog-shell) {
            width: min(430px, calc(100vw - 30px)) !important;
            max-width: 430px !important;
            border: 1px solid rgba(18, 60, 105, 0.15) !important;
            border-radius: 22px !important;
            background:
                radial-gradient(
                    circle at top right,
                    rgba(245, 197, 66, 0.12),
                    transparent 38%
                ),
                #FFFFFF !important;
            box-shadow:
                0 28px 70px rgba(7, 17, 31, 0.24),
                0 8px 24px rgba(15, 23, 42, 0.10) !important;
            overflow: hidden !important;
        }

        div[role="dialog"]:has(.epl-display-name-dialog-shell)
        [data-testid="stDialogHeader"] {
            padding-bottom: 4px !important;
        }

        div[role="dialog"]:has(.epl-display-name-dialog-shell) h2 {
            color: #07111F !important;
            font-size: 21px !important;
            font-weight: 950 !important;
            letter-spacing: -0.025em !important;
        }

        div[role="dialog"]:has(.epl-display-name-dialog-shell)
        button[aria-label="Close"] {
            border-radius: 10px !important;
        }

        .epl-display-name-dialog-shell {
            color: #475569;
            font-size: 14px;
            line-height: 1.55;
            margin: -2px 0 15px 0;
        }

        .epl-display-name-current {
            margin-top: 8px;
            padding: 9px 11px;
            border: 1px solid rgba(18, 60, 105, 0.10);
            border-radius: 11px;
            background: rgba(241, 245, 249, 0.72);
            color: #64748B;
            font-size: 13px;
        }

        .epl-display-name-current strong {
            color: #07111F;
            font-weight: 900;
        }

        .epl-display-name-warning {
            display: grid;
            grid-template-columns: 28px minmax(0, 1fr);
            align-items: center;
            gap: 10px;
            margin: 0 0 15px 0;
            padding: 11px 12px;
            border: 1px solid rgba(245, 197, 66, 0.48);
            border-radius: 13px;
            background: rgba(245, 197, 66, 0.10);
            color: #5F4700;
            font-size: 13px;
            font-weight: 700;
            line-height: 1.45;
        }

        .epl-display-name-warning-icon {
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 9px;
            background: #F5C542;
            color: #07111F;
            font-size: 15px;
            font-weight: 950;
        }

        div[role="dialog"]:has(.epl-display-name-dialog-shell)
        .stTextInput input {
            min-height: 44px !important;
            border-radius: 12px !important;
        }

        div[role="dialog"]:has(.epl-display-name-dialog-shell)
        .stTextInput input:focus {
            border-color: #123C69 !important;
            box-shadow: 0 0 0 2px rgba(18, 60, 105, 0.12) !important;
        }

        div[role="dialog"]:has(.epl-display-name-dialog-shell)
        button[kind="primaryFormSubmit"] {
            background: #123C69 !important;
            color: #FFFFFF !important;
            border-color: #123C69 !important;
        }

        div[role="dialog"]:has(.epl-display-name-dialog-shell)
        button[kind="primaryFormSubmit"]:hover {
            background: #0D2F55 !important;
            border-color: #0D2F55 !important;
            transform: none !important;
        }

        @media (max-width: 480px) {
            div[role="dialog"]:has(.epl-display-name-dialog-shell) {
                width: calc(100vw - 22px) !important;
                border-radius: 18px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )


def render_sidebar_display_name(user: dict) -> bool:
    display_name = normalize_display_name(
        user.get("display_name", "")
    )
    safe_display_name = html.escape(
        display_name,
        quote=True
    )

    with st.container(
        key="sidebar_display_name_row"
    ):
        name_column, edit_column = st.columns(
            [1, 0.14],
            gap="small"
        )

        with name_column:
            st.markdown(
                f"""
                <div
                    class="epl-sidebar-greeting"
                    title="{safe_display_name}"
                >
                    Xin chào, <strong>{safe_display_name}</strong>
                </div>
                """,
                unsafe_allow_html=True
            )

        with edit_column:
            return st.button(
                "Đổi tên hiển thị",
                key="sidebar_display_name_edit",
                help="Đổi tên hiển thị"
            )


def set_display_name_feedback(
    title: str,
    detail: str = "",
    tone: str = "info"
):
    st.session_state[DISPLAY_NAME_FEEDBACK_KEY] = {
        "title": str(title),
        "detail": str(detail),
        "tone": str(tone),
        "created_at_ms": int(
            datetime.now(timezone.utc).timestamp() * 1000
        )
    }


def render_display_name_feedback_popup():
    feedback = st.session_state.pop(
        DISPLAY_NAME_FEEDBACK_KEY,
        None
    )

    popup_html = """
    <div
        aria-hidden="true"
        style="display:none;width:0;height:0;overflow:hidden;"
    ></div>
    """

    if feedback:
        tone_config = {
            "success": {
                "icon": "✓",
                "accent": "#16A34A",
                "icon_bg": "#DCFCE7",
                "icon_color": "#166534"
            },
            "info": {
                "icon": "i",
                "accent": "#2563EB",
                "icon_bg": "#DBEAFE",
                "icon_color": "#1D4ED8"
            },
            "danger": {
                "icon": "!",
                "accent": "#E63946",
                "icon_bg": "#FEE2E2",
                "icon_color": "#B91C1C"
            }
        }

        theme = tone_config.get(
            feedback.get("tone"),
            tone_config["info"]
        )
        created_at_ms = int(
            feedback.get(
                "created_at_ms",
                datetime.now(timezone.utc).timestamp() * 1000
            )
        )
        safe_title = html.escape(
            str(feedback.get("title", ""))
        )
        safe_detail = html.escape(
            str(feedback.get("detail", ""))
        )
        detail_html = (
            f'<div class="epl-name-feedback-detail">'
            f'{safe_detail}</div>'
            if safe_detail
            else ""
        )

        popup_html = f"""
        <style>
        @keyframes eplNameFeedback{created_at_ms} {{
            0% {{
                opacity: 0;
                transform: translate(-50%, calc(-50% - 12px)) scale(0.97);
            }}
            9%, 82% {{
                opacity: 1;
                transform: translate(-50%, -50%) scale(1);
            }}
            100% {{
                opacity: 0;
                transform: translate(-50%, calc(-50% - 8px)) scale(0.98);
                visibility: hidden;
            }}
        }}

        .epl-name-feedback-{created_at_ms} {{
            position: fixed;
            left: 50%;
            top: 50%;
            z-index: 2147483647;
            width: min(390px, calc(100vw - 36px));
            display: grid;
            grid-template-columns: 42px minmax(0, 1fr);
            align-items: center;
            gap: 13px;
            box-sizing: border-box;
            padding: 15px 17px 15px 15px;
            border: 1px solid rgba(18, 60, 105, 0.15);
            border-left: 4px solid {theme["accent"]};
            border-radius: 18px;
            background:
                radial-gradient(
                    circle at top right,
                    rgba(245, 197, 66, 0.13),
                    transparent 42%
                ),
                rgba(255, 255, 255, 0.99);
            box-shadow:
                0 24px 58px rgba(7, 17, 31, 0.22),
                0 6px 18px rgba(15, 23, 42, 0.10);
            pointer-events: none;
            animation:
                eplNameFeedback{created_at_ms}
                5s
                cubic-bezier(0.22, 1, 0.36, 1)
                forwards;
        }}

        .epl-name-feedback-icon {{
            width: 42px;
            height: 42px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            background: {theme["icon_bg"]};
            color: {theme["icon_color"]};
            font-size: 20px;
            font-weight: 950;
        }}

        .epl-name-feedback-title {{
            color: #07111F;
            font-size: 15px;
            font-weight: 950;
            line-height: 1.3;
        }}

        .epl-name-feedback-detail {{
            margin-top: 3px;
            color: #64748B;
            font-size: 13px;
            font-weight: 650;
            line-height: 1.4;
        }}
        </style>

        <div
            class="epl-name-feedback-{created_at_ms}"
            role="status"
            aria-live="polite"
        >
            <div class="epl-name-feedback-icon">
                {theme["icon"]}
            </div>
            <div>
                <div class="epl-name-feedback-title">
                    {safe_title}
                </div>
                {detail_html}
            </div>
        </div>
        """

    st.html(popup_html)


@st.dialog("Đổi tên hiển thị")
def render_display_name_change_dialog(user: dict):
    user = st.session_state.get("user", user)
    current_display_name = normalize_display_name(
        user.get("display_name", "")
    )
    safe_current_display_name = html.escape(
        current_display_name
    )

    st.markdown(
        f"""
        <div class="epl-display-name-dialog-shell">
            Tên mới sẽ được cập nhật trên bảng xếp hạng và
            các khu vực hiển thị người chơi.
            <div class="epl-display-name-current">
                Tên hiện tại:
                <strong>{safe_current_display_name}</strong>
            </div>
        </div>
        <div class="epl-display-name-warning">
            <div class="epl-display-name-warning-icon">!</div>
            <div>
                Bạn chỉ có thể đổi tên 1 lần trong mỗi 30 ngày.
                Hãy kiểm tra kỹ trước khi lưu.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    with st.form(
        "display_name_change_form",
        clear_on_submit=False
    ):
        new_display_name = st.text_input(
            "Tên hiển thị mới",
            max_chars=DISPLAY_NAME_MAX_LENGTH,
            placeholder="Nhập tên bạn muốn sử dụng",
            help=(
                "Tối đa "
                f"{DISPLAY_NAME_MAX_LENGTH} ký tự."
            )
        )

        cancel_column, save_column = st.columns(
            [1, 1],
            gap="small"
        )

        with cancel_column:
            cancel_clicked = st.form_submit_button(
                "Hủy",
                use_container_width=True
            )

        with save_column:
            save_clicked = st.form_submit_button(
                "Lưu tên mới",
                type="primary",
                use_container_width=True
            )

    if cancel_clicked:
        rerun_full_app()

    if not save_clicked:
        return

    try:
        updated_user = update_user_display_name(
            user_id=int(user["user_id"]),
            new_display_name=new_display_name
        )

        session_user = dict(user)
        session_user["display_name"] = updated_user[
            "display_name"
        ]
        st.session_state["user"] = session_user

        set_display_name_feedback(
            title="Đã cập nhật tên hiển thị",
            detail=(
                f'Tên mới của bạn là '
                f'"{updated_user["display_name"]}".'
            ),
            tone="success"
        )

        rerun_full_app()

    except ValueError as error:
        st.error(str(error))

    except Exception:
        LOGGER.exception(
            "Failed to update display name for user_id=%s",
            int(user["user_id"])
        )
        st.error(
            "Chưa thể đổi tên lúc này. "
            "Vui lòng thử lại sau."
        )


@st.fragment
def render_avatar_popover(user: dict):
    """
    Hiển thị avatar tròn ở góc trên bên phải.
    Bấm vào avatar để mở kho chọn avatar.

    Cập nhật UI:
    - Avatar chính có viền vàng nhẹ và badge bút chì nhỏ ở chính giữa mép dưới.
    - Có thể kéo avatar tới vị trí bất kỳ trong vùng nhìn thấy của trình duyệt.
    - Mỗi lần tải lại app, avatar trở về vị trí mặc định.
    - Popup desktop: 4 avatar mỗi hàng.
    - Popup mobile: 2 avatar mỗi hàng, card cao hơn, ảnh avatar lớn hơn để dễ nhìn.
    - Người dùng chọn avatar bằng cách bấm trực tiếp vào khung avatar.
    - CSS target theo key riêng để hạn chế ảnh hưởng các nút khác.
    """
    user = st.session_state.get("user", user)
    avatar_catalog = load_avatar_catalog()

    if not avatar_catalog:
        return

    avatar_keys = tuple(avatar_catalog)

    current_avatar_key = normalize_avatar_key(
        user.get("avatar_key"),
        avatar_keys=list(avatar_keys)
    )
    current_avatar_src = get_avatar_src(
        current_avatar_key,
        avatar_keys=list(avatar_keys)
    )

    def render_avatar_grid():
        sprite_css = build_avatar_background_css()

        if sprite_css:
            st.markdown(
                sprite_css,
                unsafe_allow_html=True
            )

        for start_index in range(
            0,
            len(avatar_keys),
            4
        ):
            row_avatar_keys = avatar_keys[
                start_index:start_index + 4
            ]
            columns = st.columns(
                4,
                gap="small"
            )

            for column, avatar_key in zip(
                columns,
                row_avatar_keys
            ):
                with column:
                    avatar_clicked = st.button(
                        "Chọn avatar",
                        key=get_avatar_button_key(
                            avatar_key
                        ),
                        use_container_width=True,
                        help=(
                            "Avatar đang dùng."
                            if avatar_key
                            == current_avatar_key
                            else
                            "Bấm để chọn avatar này."
                        ),
                        disabled=(
                            avatar_key
                            == current_avatar_key
                        )
                    )

                    if (
                        avatar_clicked
                        and avatar_key
                        != current_avatar_key
                    ):
                        try:
                            saved_avatar_key = (
                                update_user_avatar(
                                    user_id=int(
                                        user["user_id"]
                                    ),
                                    avatar_key=avatar_key
                                )
                            )

                            updated_user = dict(
                                st.session_state.get(
                                    "user",
                                    user
                                )
                            )
                            updated_user["avatar_key"] = (
                                saved_avatar_key
                            )
                            st.session_state["user"] = (
                                updated_user
                            )
                            st.session_state.pop(
                                "avatar_picker_error",
                                None
                            )

                            rerun_current_fragment()

                        except Exception as error:
                            LOGGER.exception(
                                "Failed to update avatar "
                                "for user_id=%s",
                                int(user["user_id"])
                            )
                            st.session_state[
                                "avatar_picker_error"
                            ] = (
                                str(error)
                                or
                                "Không thể cập nhật "
                                "avatar lúc này."
                            )

        avatar_picker_error = st.session_state.pop(
            "avatar_picker_error",
            None
        )

        if avatar_picker_error:
            st.error(avatar_picker_error)

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
            cursor: grab;
            touch-action: none;
            user-select: none;
            -webkit-user-select: none;
            will-change: left, top;
        }}

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] {{
            width: 72px !important;
            height: 72px !important;
            overflow: visible !important;
        }}

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > button,

        div[class*="st-key-top_right_avatar_popover_shell"]
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
            cursor: grab !important;
            touch-action: none !important;
            user-select: none !important;
            -webkit-user-select: none !important;
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
        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > button::after,

        div[class*="st-key-top_right_avatar_popover_shell"]
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

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > button::before,

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > div > button::before {{
            content: "Xem và đổi avatar";
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

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > button:active,

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > div > button:active {{
            cursor: grabbing !important;
        }}

        div[class*="st-key-top_right_avatar_popover_shell"].epl-avatar-dragging,

        div[class*="st-key-top_right_avatar_popover_shell"].epl-avatar-dragging * {{
            cursor: grabbing !important;
        }}

        div[class*="st-key-top_right_avatar_popover_shell"].epl-avatar-dragging
        div[data-testid="stPopover"] > button,

        div[class*="st-key-top_right_avatar_popover_shell"].epl-avatar-dragging
        div[data-testid="stPopover"] > div > button {{
            transform: scale(1.045) !important;
            transition: none !important;
        }}

        div[class*="st-key-top_right_avatar_popover_shell"]
        .epl-avatar-boundary-blocked
        div[data-testid="stPopover"] > button,

        div[class*="st-key-top_right_avatar_popover_shell"]
        .epl-avatar-boundary-blocked
        div[data-testid="stPopover"] > div > button,

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > button.epl-avatar-boundary-blocked,

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > div > button.epl-avatar-boundary-blocked {{
            border-color: #F5C542 !important;
            outline-color: rgba(245, 197, 66, 1) !important;
            box-shadow:
                0 16px 36px rgba(7, 17, 31, 0.30),
                0 0 0 8px rgba(245, 197, 66, 0.18) !important;
        }}

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > button:hover,

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > div > button:hover {{
            transform: translateY(-1px) scale(1.045) !important;
            border-color: #F5C542 !important;
            outline-color: rgba(245, 197, 66, 0.96) !important;
            box-shadow:
                0 16px 36px rgba(7, 17, 31, 0.30),
                0 0 0 7px rgba(245, 197, 66, 0.12) !important;
        }}

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > button:hover::before,

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > div > button:hover::before {{
            opacity: 1;
            transform: translateY(-50%) translateX(0);
        }}

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > button:hover::after,

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > div > button:hover::after {{
            transform: translateX(-50%) scale(1.08);
            background: #FFD761;
        }}

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > button:focus-visible,

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > div > button:focus-visible {{
            outline: 3px solid rgba(37, 99, 235, 0.72) !important;
            outline-offset: 4px !important;
        }}

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > button[aria-expanded="true"],

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > div > button[aria-expanded="true"] {{
            border-color: #F5C542 !important;
            outline-color: rgba(245, 197, 66, 1) !important;
            box-shadow:
                0 16px 36px rgba(7, 17, 31, 0.30),
                0 0 0 7px rgba(245, 197, 66, 0.14) !important;
        }}

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > button *,

        div[class*="st-key-top_right_avatar_popover_shell"]
        div[data-testid="stPopover"] > div > button * {{
            display: none !important;
            visibility: hidden !important;
            font-size: 0 !important;
            line-height: 0 !important;
            color: transparent !important;
        }}

        div[data-testid="stPopoverBody"]:has(.wc-avatar-grid-desktop-shell),
        div[data-testid="stPopoverContent"]:has(.wc-avatar-grid-desktop-shell) {{
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

            div[class*="st-key-top_right_avatar_popover_shell"]
            div[data-testid="stPopover"] {{
                width: 56px !important;
                height: 56px !important;
            }}

            div[class*="st-key-top_right_avatar_popover_shell"]
            div[data-testid="stPopover"] > button,

            div[class*="st-key-top_right_avatar_popover_shell"]
            div[data-testid="stPopover"] > div > button {{
                width: 48px !important;
                height: 48px !important;
                min-width: 48px !important;
                min-height: 48px !important;
                max-width: 48px !important;
                max-height: 48px !important;
                border: none !important;
                outline: none !important;
                box-shadow:
                    0 10px 24px rgba(7, 17, 31, 0.22),
                    0 0 0 4px rgba(245, 197, 66, 0.10) !important;
            }}

            div[class*="st-key-top_right_avatar_popover_shell"]
            div[data-testid="stPopover"] > button::before,

            div[class*="st-key-top_right_avatar_popover_shell"]
            div[data-testid="stPopover"] > div > button::before {{
                display: none !important;
            }}

            div[class*="st-key-top_right_avatar_popover_shell"]
            div[data-testid="stPopover"] > button::after,

            div[class*="st-key-top_right_avatar_popover_shell"]
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

            div[class*="st-key-top_right_avatar_popover_shell"]
            div[data-testid="stPopover"] > button:hover::after,

            div[class*="st-key-top_right_avatar_popover_shell"]
            div[data-testid="stPopover"] > div > button:hover::after {{
                transform: translateX(-50%) scale(1.08);
            }}

            div[data-testid="stPopoverBody"]:has(.wc-avatar-grid-desktop-shell),
            div[data-testid="stPopoverContent"]:has(.wc-avatar-grid-desktop-shell) {{
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
                display: block !important;
            }}

            .wc-avatar-grid-mobile-shell {{
                display: none !important;
            }}

            div[data-testid="stPopoverBody"]:has(.wc-avatar-grid-desktop-shell)
            [data-testid="column"],

            div[data-testid="stPopoverContent"]:has(.wc-avatar-grid-desktop-shell)
            [data-testid="column"] {{
                padding-left: 0 !important;
                padding-right: 0 !important;
            }}
        }}

        @media (max-width: 390px) {{
            div[data-testid="stPopoverBody"]:has(.wc-avatar-grid-desktop-shell),
            div[data-testid="stPopoverContent"]:has(.wc-avatar-grid-desktop-shell) {{
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
                        display: block !important;
                    }

                    div[data-testid="stHorizontalBlock"] {
                        display: grid !important;
                        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                        gap: 10px !important;
                        align-items: stretch !important;
                        width: 100% !important;
                    }

                    div[data-testid="stColumn"],
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
                    '<div class="wc-avatar-grid-desktop-shell">',
                    unsafe_allow_html=True
                )
                render_avatar_grid()
                st.markdown("</div>", unsafe_allow_html=True)

    avatar_drag_script = """
    <script>
    (() => {
        const controllerName =
            "__eplAvatarDragController";

        const oldController =
            window[controllerName];

        if (
            oldController
            && typeof oldController.cleanup
                === "function"
        ) {
            oldController.cleanup();
        }

        const shell =
            document.querySelector(
                'div[class*="st-key-'
                + 'top_right_avatar_popover_shell"]'
            );

        if (!shell) {
            return;
        }

        const button =
            shell.querySelector(
                'div[data-testid="stPopover"] > button'
            )
            || shell.querySelector(
                'div[data-testid="stPopover"] '
                + '> div > button'
            );

        if (!button) {
            return;
        }

        const edgeGap = 8;
        const headerGap = 6;
        const dragThreshold = 6;

        let activePointer = null;
        let dragStarted = false;
        let suppressClickUntil = 0;
        let resizeFrame = 0;
        let mutationObserver = null;
        let cleaned = false;

        const createBoundaryGuide = (
            guideName
        ) => {
            const guide =
                document.createElement("div");

            guide.dataset.eplAvatarBoundary =
                guideName;

            Object.assign(
                guide.style,
                {
                    position: "fixed",
                    pointerEvents: "none",
                    opacity: "0",
                    visibility: "hidden",
                    zIndex: "999997",
                    transition:
                        "opacity 120ms ease"
                }
            );

            document.body.appendChild(guide);

            return guide;
        };

        const headerBoundaryGuide =
            createBoundaryGuide("header");

        Object.assign(
            headerBoundaryGuide.style,
            {
                height: "2px",
                borderRadius: "999px",
                background:
                    "linear-gradient("
                    + "90deg, transparent, "
                    + "rgba(245, 197, 66, 0.92), "
                    + "transparent)",
                boxShadow:
                    "0 0 12px "
                    + "rgba(245, 197, 66, 0.30)"
            }
        );

        const getVisibleRect = (
            element
        ) => {
            if (!element) {
                return null;
            }

            const style =
                window.getComputedStyle(element);

            if (
                style.display === "none"
                || style.visibility === "hidden"
            ) {
                return null;
            }

            const rect =
                element.getBoundingClientRect();

            if (
                rect.width <= 0
                || rect.height <= 0
            ) {
                return null;
            }

            return rect;
        };

        const getHeaderRect = () => {
            const candidates =
                document.querySelectorAll(
                    'header[data-testid="stHeader"], '
                    + '[data-testid="stHeader"]'
                );

            for (const candidate of candidates) {
                const rect =
                    getVisibleRect(candidate);

                if (rect) {
                    return rect;
                }
            }

            return null;
        };

        const getMovementBounds = () => {
            const shellRect =
                shell.getBoundingClientRect();

            const headerRect =
                getHeaderRect();

            const minimumTop =
                headerRect
                ? Math.ceil(
                    headerRect.bottom
                    + headerGap
                )
                : edgeGap;

            const maxLeft =
                Math.max(
                    edgeGap,
                    window.innerWidth
                    - shellRect.width
                    - edgeGap
                );

            const maxTop =
                Math.max(
                    edgeGap,
                    window.innerHeight
                    - shellRect.height
                    - edgeGap
                );

            return {
                minLeft: edgeGap,
                minTop: Math.min(
                    Math.max(
                        edgeGap,
                        minimumTop
                    ),
                    maxTop
                ),
                maxLeft,
                maxTop,
                shellWidth: shellRect.width,
                shellHeight: shellRect.height,
                headerRect
            };
        };

        const clampNumber = (
            value,
            minimum,
            maximum
        ) => Math.min(
            Math.max(
                Number.isFinite(Number(value))
                    ? Number(value)
                    : minimum,
                minimum
            ),
            maximum
        );

        const clampToBounds = (
            left,
            top,
            bounds
        ) => ({
            left: clampNumber(
                left,
                bounds.minLeft,
                bounds.maxLeft
            ),
            top: clampNumber(
                top,
                bounds.minTop,
                bounds.maxTop
            )
        });

        const constrainPosition = (
            proposedLeft,
            proposedTop
        ) => {
            const bounds =
                getMovementBounds();

            const requestedPosition = {
                left: Number(proposedLeft),
                top: Number(proposedTop)
            };

            let position =
                clampToBounds(
                    requestedPosition.left,
                    requestedPosition.top,
                    bounds
                );

            let blocked = (
                position.left
                    !== requestedPosition.left
                || position.top
                    !== requestedPosition.top
            );

            return {
                ...position,
                blocked,
                bounds
            };
        };

        const updateBoundaryGuides = () => {
            const bounds =
                getMovementBounds();

            const headerRect =
                bounds.headerRect;

            headerBoundaryGuide.style.left =
                (
                    headerRect
                    ? Math.max(0, headerRect.left)
                    : 0
                )
                + "px";

            headerBoundaryGuide.style.width =
                (
                    headerRect
                    ? Math.min(
                        window.innerWidth
                            - Math.max(
                                0,
                                headerRect.left
                            ),
                        headerRect.width
                    )
                    : window.innerWidth
                )
                + "px";

            headerBoundaryGuide.style.top =
                (bounds.minTop - 1) + "px";
        };

        const showBoundaryGuides = () => {
            updateBoundaryGuides();

            headerBoundaryGuide.style.visibility =
                "visible";

            headerBoundaryGuide.style.opacity =
                "1";
        };

        const hideBoundaryGuides = () => {
            headerBoundaryGuide.style.opacity =
                "0";

            headerBoundaryGuide.style.visibility =
                "hidden";
        };

        const applyPosition = (
            proposedLeft,
            proposedTop
        ) => {
            const position =
                constrainPosition(
                    proposedLeft,
                    proposedTop
                );

            shell.style.setProperty(
                "left",
                position.left + "px",
                "important"
            );

            shell.style.setProperty(
                "top",
                position.top + "px",
                "important"
            );

            shell.style.setProperty(
                "right",
                "auto",
                "important"
            );

            shell.style.setProperty(
                "bottom",
                "auto",
                "important"
            );

            button.classList.toggle(
                "epl-avatar-boundary-blocked",
                Boolean(
                    dragStarted
                    && position.blocked
                )
            );

            return position;
        };

        const useDefaultPosition = () => {
            const initialRect =
                shell.getBoundingClientRect();

            applyPosition(
                initialRect.left,
                initialRect.top
            );
        };

        const stopDragging = (
            event
        ) => {
            if (!activePointer) {
                return;
            }

            if (
                event
                && event.pointerId
                    !== activePointer.pointerId
            ) {
                return;
            }

            if (dragStarted) {
                suppressClickUntil =
                    Date.now() + 500;

                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
            }

            activePointer = null;
            dragStarted = false;

            shell.classList.remove(
                "epl-avatar-dragging"
            );

            button.classList.remove(
                "epl-avatar-boundary-blocked"
            );

            hideBoundaryGuides();
        };

        const onPointerDown = (
            event
        ) => {
            if (
                event.button !== undefined
                && event.button !== 0
            ) {
                return;
            }

            const shellRect =
                shell.getBoundingClientRect();

            activePointer = {
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                startLeft: shellRect.left,
                startTop: shellRect.top
            };

            dragStarted = false;
        };

        const onPointerMove = (
            event
        ) => {
            if (
                !activePointer
                || event.pointerId
                    !== activePointer.pointerId
            ) {
                return;
            }

            const deltaX =
                event.clientX
                - activePointer.startX;

            const deltaY =
                event.clientY
                - activePointer.startY;

            if (
                !dragStarted
                && Math.hypot(
                    deltaX,
                    deltaY
                ) < dragThreshold
            ) {
                return;
            }

            dragStarted = true;

            shell.classList.add(
                "epl-avatar-dragging"
            );

            showBoundaryGuides();

            event.preventDefault();
            event.stopPropagation();

            const previousRect =
                shell.getBoundingClientRect();

            applyPosition(
                activePointer.startLeft
                    + deltaX,
                activePointer.startTop
                    + deltaY,
                false,
                {
                    left: previousRect.left,
                    top: previousRect.top
                },
                true
            );
        };

        const onPointerUp = (
            event
        ) => {
            stopDragging(event);
        };

        const onPointerCancel = (
            event
        ) => {
            stopDragging(event);
        };

        const onClickCapture = (
            event
        ) => {
            if (
                Date.now()
                >= suppressClickUntil
            ) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
        };

        const keepInsideAllowedArea = () => {
            cancelAnimationFrame(
                resizeFrame
            );

            resizeFrame =
                requestAnimationFrame(
                    () => {
                        const currentRect =
                            shell
                                .getBoundingClientRect();

                        applyPosition(
                            currentRect.left,
                            currentRect.top
                        );

                        if (dragStarted) {
                            showBoundaryGuides();
                        }
                    }
                );
        };

        const cleanup = () => {
            if (cleaned) {
                return;
            }

            cleaned = true;

            cancelAnimationFrame(
                resizeFrame
            );

            button.removeEventListener(
                "pointerdown",
                onPointerDown
            );

            document.removeEventListener(
                "pointermove",
                onPointerMove,
                true
            );

            document.removeEventListener(
                "pointerup",
                onPointerUp,
                true
            );

            document.removeEventListener(
                "pointercancel",
                onPointerCancel,
                true
            );

            shell.removeEventListener(
                "click",
                onClickCapture,
                true
            );

            window.removeEventListener(
                "resize",
                keepInsideAllowedArea
            );

            if (window.visualViewport) {
                window.visualViewport
                    .removeEventListener(
                        "resize",
                        keepInsideAllowedArea
                    );
            }

            if (mutationObserver) {
                mutationObserver.disconnect();
            }

            headerBoundaryGuide.remove();
        };

        button.setAttribute(
            "title",
            "Xem và đổi avatar"
        );

        button.setAttribute(
            "aria-label",
            "Xem và đổi avatar; giữ và kéo "
            + "để di chuyển nút"
        );

        button.addEventListener(
            "pointerdown",
            onPointerDown
        );

        document.addEventListener(
            "pointermove",
            onPointerMove,
            {
                capture: true,
                passive: false
            }
        );

        document.addEventListener(
            "pointerup",
            onPointerUp,
            true
        );

        document.addEventListener(
            "pointercancel",
            onPointerCancel,
            true
        );

        shell.addEventListener(
            "click",
            onClickCapture,
            true
        );

        window.addEventListener(
            "resize",
            keepInsideAllowedArea,
            { passive: true }
        );

        if (window.visualViewport) {
                window.visualViewport
                    .addEventListener(
                        "resize",
                        keepInsideAllowedArea,
                        { passive: true }
                    );
        }

        mutationObserver =
            new MutationObserver(
                () => {
                    if (!shell.isConnected) {
                        cleanup();
                        return;
                    }

                    keepInsideAllowedArea();
                }
            );

        mutationObserver.observe(
            document.body,
            {
                childList: true,
                subtree: true
            }
        );

        useDefaultPosition();

        window[controllerName] = {
            cleanup
        };
    })();
    </script>
    """

    st.html(
        avatar_drag_script,
        unsafe_allow_javascript=True
    )
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
        pool_use_lifo=True,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=20000 -c lock_timeout=5000"
        }
    )

    return engine


def is_retryable_database_error(error: Exception) -> bool:
    """
    Chỉ retry lỗi kết nối tạm thời của truy vấn đọc.

    Không retry statement timeout hoặc lỗi SQL/schema vì chạy lại chỉ làm
    người dùng chờ lâu hơn. Thao tác ghi không dùng helper này để tránh ghi
    trùng trong trường hợp kết quả commit không xác định.
    """
    current_error = error
    visited_error_ids = set()

    for _ in range(5):
        if current_error is None:
            break

        current_error_id = id(current_error)

        if current_error_id in visited_error_ids:
            break

        visited_error_ids.add(current_error_id)
        error_text = str(current_error).casefold()

        if (
            "statement timeout" in error_text
            or "query canceled" in error_text
            or "syntax error" in error_text
            or "undefined table" in error_text
            or "undefined column" in error_text
        ):
            return False

        if isinstance(
            current_error,
            SQLAlchemyTimeoutError
        ):
            return True

        if isinstance(
            current_error,
            OperationalError
        ):
            return True

        if (
            isinstance(current_error, DBAPIError)
            and bool(
                getattr(
                    current_error,
                    "connection_invalidated",
                    False
                )
            )
        ):
            return True

        transient_markers = (
            "server closed the connection",
            "connection reset",
            "connection refused",
            "connection aborted",
            "connection timed out",
            "could not connect",
            "ssl syscall error",
            "terminating connection",
            "connection is closed",
            "broken pipe"
        )

        if any(
            marker in error_text
            for marker in transient_markers
        ):
            return True

        current_error = (
            getattr(current_error, "__cause__", None)
            or getattr(current_error, "__context__", None)
        )

    return False


def reset_database_pool_after_disconnect():
    """
    Loại các connection hỏng khỏi pool trước lần retry duy nhất.
    """
    try:
        get_engine().dispose(close=False)
    except TypeError:
        # Tương thích SQLAlchemy cũ chưa hỗ trợ close=False.
        get_engine().dispose()
    except Exception:
        pass


def read_sql(query: str, params: dict | None = None) -> pd.DataFrame:
    last_error = None

    for attempt in range(2):
        try:
            with get_engine().connect() as conn:
                return pd.read_sql_query(
                    text(query),
                    conn,
                    params=params or {}
                )

        except Exception as error:
            last_error = error

            if (
                attempt >= 1
                or not is_retryable_database_error(
                    error
                )
            ):
                raise

            LOGGER.warning(
                "Transient database read failure; "
                "retrying once.",
                exc_info=True
            )
            reset_database_pool_after_disconnect()

    raise last_error

def rerun_current_fragment():
    """
    Rerun riêng fragment/dialog hiện tại.
    Nếu Streamlit version cũ không hỗ trợ scope='fragment' thì fallback về full rerun.
    """
    try:
        st.rerun(scope="fragment")
    except Exception:
        st.rerun()

def rerun_full_app():
    """
    Rerun toàn app để main() chạy lại.
    Dùng cho các flow cần chuyển từ popup này sang popup khác.
    """
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()

def fetch_one(query: str, params: dict | None = None):
    for attempt in range(2):
        try:
            with get_engine().connect() as conn:
                row = conn.execute(
                    text(query),
                    params or {}
                ).mappings().fetchone()

            break

        except Exception as error:
            if (
                attempt >= 1
                or not is_retryable_database_error(
                    error
                )
            ):
                raise

            LOGGER.warning(
                "Transient database fetch failure; "
                "retrying once.",
                exc_info=True
            )
            reset_database_pool_after_disconnect()

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


def can_edit_prediction(
    kickoff_time_utc,
    is_finished=False
) -> bool:
    if to_bool(is_finished):
        return False

    kickoff = parse_utc_datetime(
        kickoff_time_utc
    )

    if pd.isna(kickoff):
        return False

    now = pd.Timestamp.now(tz="UTC")

    return now < kickoff

def can_use_ai_match_suggestion(
    kickoff_time_utc,
    is_finished=False
) -> bool:
    """
    Chỉ cho phép AI phân tích trong tối đa 3 ngày
    trước chính xác giờ kickoff.

    Ví dụ:
    - Còn 72 giờ: được phép
    - Còn 72 giờ 1 phút: không được phép
    - Đã kickoff: không được phép
    - Đã có kết quả: không được phép
    """
    if to_bool(is_finished):
        return False

    kickoff = parse_utc_datetime(
        kickoff_time_utc
    )

    if pd.isna(kickoff):
        return False

    now = pd.Timestamp.now(tz="UTC")

    ai_window_start = (
        kickoff
        - pd.Timedelta(
            days=AI_SUGGESTION_MAX_DAYS
        )
    )

    return (
        ai_window_start <= now < kickoff
    )

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

    raw_text = str(team_name).strip()
    text = raw_text.lower()

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

    if any(keyword in text for keyword in unknown_keywords):
        return True

    # Bắt các placeholder kiểu W87, L87, W 87, L 87
    # Thường nghĩa là Winner/Loser của match số 87, tức đội chưa xác định.
    if re.fullmatch(r"[wl]\s*\d+", text):
        return True

    # Bắt thêm các dạng có ký hiệu kèm theo như "W87 / L88" nếu sau này data có biến thể.
    if re.search(r"\b[wl]\s*\d+\b", text):
        return True

    return False


def get_outcome(home_score, away_score):
    if home_score > away_score:
        return "HOME_WIN"

    if home_score < away_score:
        return "AWAY_WIN"

    return "DRAW"


def calculate_score_points(
    pred_home,
    pred_away,
    actual_home,
    actual_away,
    is_big_match: bool = False
) -> int:
    if pred_home is None or pred_away is None:
        return 0

    if actual_home is None or actual_away is None:
        return 0

    pred_home = int(pred_home)
    pred_away = int(pred_away)
    actual_home = int(actual_home)
    actual_away = int(actual_away)

    if pred_home == actual_home and pred_away == actual_away:
        return (
            BIG_MATCH_EXACT_POINTS
            if is_big_match
            else NORMAL_MATCH_EXACT_POINTS
        )

    if get_outcome(pred_home, pred_away) == get_outcome(
        actual_home,
        actual_away
    ):
        return (
            BIG_MATCH_OUTCOME_POINTS
            if is_big_match
            else NORMAL_MATCH_OUTCOME_POINTS
        )

    return 0

def calculate_total_points(row) -> int:
    pred_home = to_optional_int(
        row.get("predicted_home_score")
    )
    pred_away = to_optional_int(
        row.get("predicted_away_score")
    )

    actual_home = to_optional_int(
        row.get("home_score_for_prediction")
    )
    actual_away = to_optional_int(
        row.get("away_score_for_prediction")
    )

    is_big_match = is_big_six_match(
        row.get("home_team_name"),
        row.get("away_team_name")
    )

    points = calculate_score_points(
        pred_home,
        pred_away,
        actual_home,
        actual_away,
        is_big_match=is_big_match
    )

    # Giữ lại logic knockout cũ để không làm hỏng
    # khả năng tái sử dụng code trong tương lai.
    is_knockout = to_bool(row.get("is_knockout"))

    if is_knockout:
        predicted_winner_team_id = to_optional_int(
            row.get("predicted_winner_team_id")
        )
        actual_winner_team_id = to_optional_int(
            row.get("winner_team_id")
        )

        if (
            predicted_winner_team_id is not None
            and actual_winner_team_id is not None
            and predicted_winner_team_id
            == actual_winner_team_id
        ):
            points += 1

    return int(points)

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


def calculate_points_with_star(
    base_points: int,
    star_type: str,
    is_big_match: bool = False
) -> dict:
    base_points = int(base_points or 0)
    star_type = normalize_star_type(star_type)

    star_config = STAR_CONFIG[star_type]
    multiplier = int(star_config["multiplier"])

    if base_points > 0:
        final_points = base_points * multiplier
    else:
        penalty_key = (
            "wrong_penalty_big"
            if is_big_match
            else "wrong_penalty_normal"
        )

        final_points = int(
            star_config.get(penalty_key, 0)
        )

    star_bonus_points = final_points - base_points

    return {
        "base_points": int(base_points),
        "star_bonus_points": int(star_bonus_points),
        "points": int(final_points)
    }
def format_star_short(star_type) -> str:
    star_type = normalize_star_type(star_type)
    return STAR_CONFIG[star_type]["short_label"]

def build_star_usage_result(
    user_id: int,
    hope_locked_used: int,
    super_locked_used: int,
    hope_reserved_used: int,
    super_reserved_used: int
) -> dict:
    """
    Gom phần tính quota sao sau khi đã có số sao locked/reserved.

    Hàm này chỉ gom logic bị lặp giữa get_user_star_usage() và
    get_user_star_usage_from_db(), không thay đổi công thức hiện tại.
    """
    quota = get_user_star_quota(user_id)

    hope_total = int(quota["hope_total"])
    super_total = int(quota["super_total"])

    hope_left = max(0, hope_total - hope_locked_used)
    super_left = max(0, super_total - super_locked_used)

    hope_free_left = max(0, hope_left - hope_reserved_used)
    super_free_left = max(0, super_left - super_reserved_used)

    return {
        "hope_used": hope_locked_used,
        "super_used": super_locked_used,

        "hope_locked_used": hope_locked_used,
        "super_locked_used": super_locked_used,

        "hope_reserved_used": hope_reserved_used,
        "super_reserved_used": super_reserved_used,

        "hope_total": hope_total,
        "super_total": super_total,

        "hope_bonus": int(quota.get("hope_bonus", 0)),
        "super_bonus": int(quota.get("super_bonus", 0)),

        "hope_left": hope_left,
        "super_left": super_left,

        "hope_free_left": hope_free_left,
        "super_free_left": super_free_left
    }


@st.cache_data(
    ttl=10,
    max_entries=512,
    show_spinner=False
)
def _load_user_star_usage_counts_cached(
    user_id: int,
    season_slug: str,
    use_all_predictions: bool,
    all_predictions_revision: int,
    all_user_predictions_revision: int,
    single_user_predictions_revision: int
) -> dict:
    """
    Tính trạng thái sao của một user đúng một lần trong mỗi chu kỳ cache.

    Kết quả giữ cả đóng góp theo match_id, nhờ đó việc loại trận đang sửa
    chỉ còn là phép trừ O(1), thay vì merge/apply lại toàn bộ dữ liệu mỗi card.
    """
    if use_all_predictions:
        predictions = load_predictions(season_slug)

        if not predictions.empty:
            predictions = predictions[
                predictions["user_id"].astype(int) == int(user_id)
            ]
    else:
        predictions = load_user_predictions(
            int(user_id),
            season_slug
        )

    matches = load_matches(season_slug)

    counts = {
        "hope_locked_used": 0,
        "super_locked_used": 0,
        "hope_reserved_used": 0,
        "super_reserved_used": 0
    }
    contributions = {}

    if predictions.empty or matches.empty:
        return {
            **counts,
            "contributions": contributions
        }

    match_info = matches[
        [
            "match_id",
            "kickoff_time_utc",
            "is_finished"
        ]
    ]

    usage_rows = predictions.merge(
        match_info,
        on="match_id",
        how="left"
    )

    for row in usage_rows.itertuples(index=False):
        match_id = int(row.match_id)
        star_type = normalize_star_type(row.star_type)
        is_locked = is_match_locked_for_star(
            row.kickoff_time_utc,
            row.is_finished
        )
        is_reserved = is_match_open_for_star_transfer(
            row.kickoff_time_utc,
            row.is_finished
        )

        if star_type not in {
            STAR_TYPE_HOPE,
            STAR_TYPE_SUPER
        }:
            continue

        contribution = {
            "star_type": star_type,
            "is_locked": bool(is_locked),
            "is_reserved": bool(is_reserved)
        }
        contributions[match_id] = contribution

        if star_type == STAR_TYPE_HOPE:
            if is_locked:
                counts["hope_locked_used"] += 1
            elif is_reserved:
                counts["hope_reserved_used"] += 1

        elif star_type == STAR_TYPE_SUPER:
            if is_locked:
                counts["super_locked_used"] += 1
            elif is_reserved:
                counts["super_reserved_used"] += 1

    return {
        **counts,
        "contributions": contributions
    }


def get_user_star_usage(user_id: int, exclude_match_id: int | None = None) -> dict:
    """
    Dùng cho UI.

    Logic mới:
    - locked_used: chỉ tính sao ở các trận đã khóa dự đoán.
    - reserved_used: sao đang giữ tạm ở các trận chưa diễn ra.
    - left: số sao còn lại theo kho chính thức, chỉ trừ locked_used.
    - free_left: số sao còn trống để gắn ngay, đã trừ cả reserved_used.
    """
    user_id = int(user_id)
    season_slug = get_selected_season_slug()
    use_all_predictions = st.session_state.get(
        "selected_page",
        "Lịch thi đấu & dự đoán"
    ) in {
        "Dự đoán của tôi",
        "Bảng xếp hạng",
        "Phân tích tổng quan",
        "Admin"
    }

    if use_all_predictions:
        all_predictions_revision = (
            get_all_predictions_revision(
                season_slug
            )
        )
        all_user_predictions_revision = 0
        single_user_predictions_revision = 0

    else:
        (
            all_user_predictions_revision,
            single_user_predictions_revision
        ) = get_user_predictions_revisions(
            user_id,
            season_slug
        )
        all_predictions_revision = 0

    counts = _load_user_star_usage_counts_cached(
        user_id,
        season_slug,
        use_all_predictions,
        all_predictions_revision,
        all_user_predictions_revision,
        single_user_predictions_revision
    )

    hope_locked_used = int(counts["hope_locked_used"])
    super_locked_used = int(counts["super_locked_used"])
    hope_reserved_used = int(counts["hope_reserved_used"])
    super_reserved_used = int(counts["super_reserved_used"])

    if exclude_match_id is not None:
        contribution = counts["contributions"].get(
            int(exclude_match_id)
        )

        if contribution:
            star_type = contribution["star_type"]

            if star_type == STAR_TYPE_HOPE:
                if contribution["is_locked"]:
                    hope_locked_used = max(0, hope_locked_used - 1)
                elif contribution["is_reserved"]:
                    hope_reserved_used = max(0, hope_reserved_used - 1)

            elif star_type == STAR_TYPE_SUPER:
                if contribution["is_locked"]:
                    super_locked_used = max(0, super_locked_used - 1)
                elif contribution["is_reserved"]:
                    super_reserved_used = max(0, super_reserved_used - 1)

    return build_star_usage_result(
        user_id=user_id,
        hope_locked_used=hope_locked_used,
        super_locked_used=super_locked_used,
        hope_reserved_used=hope_reserved_used,
        super_reserved_used=super_reserved_used
    )

def validate_star_quota(
    user_id: int,
    match_id: int,
    star_type: str,
    usage: dict | None = None
):
    """
    Kiểm tra quota sao.

    usage có thể được truyền từ transaction để tránh query lặp.
    Khi không dùng sao, hàm thoát ngay.
    """
    star_type = normalize_star_type(star_type)

    if star_type == STAR_TYPE_NONE:
        return

    if usage is None:
        usage = get_user_star_usage_from_db(
            user_id=int(user_id),
            exclude_match_id=int(match_id)
        )

    if star_type == STAR_TYPE_HOPE:
        hope_left = int(usage.get("hope_left", 0))
        hope_free_left = int(
            usage.get("hope_free_left", hope_left)
        )

        if hope_left <= 0:
            raise ValueError("Bạn đã dùng hết Ngôi sao hy vọng.")

        if hope_free_left <= 0:
            raise ValueError(
                "Ngôi sao hy vọng đang được sử dụng hết ở các trận khác."
            )

    elif star_type == STAR_TYPE_SUPER:
        super_left = int(usage.get("super_left", 0))
        super_free_left = int(
            usage.get("super_free_left", super_left)
        )

        if super_left <= 0:
            raise ValueError("Bạn đã dùng hết Siêu sao.")

        if super_free_left <= 0:
            raise ValueError(
                "Siêu sao đang được sử dụng ở một trận khác."
            )


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
        "predicted_home_score": existing.get(
            "predicted_home_score"
        ),
        "predicted_away_score": existing.get(
            "predicted_away_score"
        ),
        "predicted_winner_team_id": existing.get(
            "predicted_winner_team_id"
        ),

        "home_score_for_prediction": match_row.get(
            "home_score_for_prediction"
        ),
        "away_score_for_prediction": match_row.get(
            "away_score_for_prediction"
        ),

        "home_team_name": match_row.get(
            "home_team_name"
        ),
        "away_team_name": match_row.get(
            "away_team_name"
        ),

        "is_knockout": match_row.get("is_knockout"),
        "winner_team_id": match_row.get(
            "winner_team_id"
        )
    }

    is_big_match = is_big_six_match(
        match_row.get("home_team_name"),
        match_row.get("away_team_name")
    )

    base_points = calculate_total_points(
        scoring_row
    )

    return calculate_points_with_star(
        base_points=base_points,
        star_type=existing.get("star_type"),
        is_big_match=is_big_match
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

        score_title = (
            f"Điểm gốc: {base_points} | "
            f"Điểm bổ trợ: {star_bonus_points} | "
            f"Tổng điểm trận: {final_points}"
        )

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

BIG_SIX_CANONICAL_TEAMS = frozenset({
    "arsenal",
    "chelsea",
    "liverpool",
    "manchester_city",
    "manchester_united",
    "tottenham"
})

BIG_SIX_TEAM_ALIASES = {
    "arsenal": "arsenal",
    "chelsea": "chelsea",
    "liverpool": "liverpool",

    "manchester city": "manchester_city",
    "man city": "manchester_city",

    "manchester united": "manchester_united",
    "man united": "manchester_united",
    "man utd": "manchester_united",

    "tottenham hotspur": "tottenham",
    "tottenham": "tottenham",
    "spurs": "tottenham"
}


def canonicalize_big_six_team_name(team_name) -> str:
    """
    Chuẩn hóa tên đội để nhận diện Big 6.

    Hỗ trợ các dạng như:
    - Arsenal FC
    - Manchester United FC
    - Man United
    - Manchester City FC
    - Man City
    - Tottenham Hotspur FC
    """
    if team_name is None:
        return ""

    try:
        if pd.isna(team_name):
            return ""
    except (TypeError, ValueError):
        pass

    normalized_name = str(
        team_name
    ).casefold().strip()

    # Xóa dấu câu và chuẩn hóa khoảng trắng.
    normalized_name = re.sub(
        r"[^a-z0-9]+",
        " ",
        normalized_name
    )

    # Xóa FC, AFC hoặc Football Club.
    normalized_name = re.sub(
        r"\b(?:football club|afc|fc)\b",
        " ",
        normalized_name
    )

    normalized_name = re.sub(
        r"\s+",
        " ",
        normalized_name
    ).strip()

    return BIG_SIX_TEAM_ALIASES.get(
        normalized_name,
        normalized_name.replace(" ", "_")
    )


def is_big_six_match(
    home_team_name,
    away_team_name
) -> bool:
    """
    Chỉ trả về True khi cả hai đội đều thuộc Big 6.
    """
    home_team_key = canonicalize_big_six_team_name(
        home_team_name
    )

    away_team_key = canonicalize_big_six_team_name(
        away_team_name
    )

    return (
        home_team_key != away_team_key
        and home_team_key in BIG_SIX_CANONICAL_TEAMS
        and away_team_key in BIG_SIX_CANONICAL_TEAMS
    )

@st.cache_data(show_spinner=False, max_entries=8)
def get_match_card_css(status_info):
    """
    Thiết kế chung cho toàn bộ card Premier League.

    Mục tiêu:
    - Giữ nguyên toàn bộ logic theo trạng thái.
    - Dùng một khung thiết kế đồng bộ, danh giá.
    - Màu chủ đạo Premier League: tím đậm, hồng, xanh mint.
    - Giữ màu trạng thái cho badge và hiệu ứng chạy viền.
    """
    status_key = str(
        status_info.get("status_key") or ""
    ).strip().lower()

    status_accent_by_key = {
        "open": {
            "accent": "#00A8E8",
            "soft": "#9FE7FF",
            "glow": "rgba(0, 168, 232, 0.22)",
            "shimmer": "#5DD8FF",
        },
        "locked": {
            "accent": "#F5B700",
            "soft": "#FFE7A3",
            "glow": "rgba(245, 183, 0, 0.22)",
            "shimmer": "#FFD45C",
        },
        "finished": {
            "accent": "#00A86B",
            "soft": "#A7F3D0",
            "glow": "rgba(0, 168, 107, 0.20)",
            "shimmer": "#52E3A6",
        },
        "unknown": {
            "accent": "#94A3B8",
            "soft": "#E2E8F0",
            "glow": "rgba(100, 116, 139, 0.14)",
            "shimmer": "#CBD5E1",
        },
    }

    accent_config = status_accent_by_key.get(
        status_key,
        status_accent_by_key["unknown"]
    )

    shimmer_opacity = (
        "1"
        if status_key in {"open", "locked", "finished"}
        else "0"
    )

    return f"""
    {{
        --wc-match-card-shimmer-opacity:
            {shimmer_opacity};

        --wc-match-card-shimmer-color:
            {accent_config["shimmer"]};

        --wc-match-card-shimmer-soft:
            {accent_config["soft"]};

        --wc-match-card-shimmer-speed:
            4.2s;

        --epl-card-status-accent:
            {accent_config["accent"]};

        --epl-card-status-glow:
            {accent_config["glow"]};

        border:
            2px solid #37003C;

        border-radius:
            20px;

        padding:
            24px 24px 18px 24px;

        margin:
            4px 4px 28px 4px;

        background:
            linear-gradient(
                #E8C96A,
                #E8C96A
            )
            left 12px top 12px
            / 24px 1px
            no-repeat,

            linear-gradient(
                #E8C96A,
                #E8C96A
            )
            left 12px top 12px
            / 1px 24px
            no-repeat,

            linear-gradient(
                #E8C96A,
                #E8C96A
            )
            right 12px top 12px
            / 24px 1px
            no-repeat,

            linear-gradient(
                #E8C96A,
                #E8C96A
            )
            right 12px top 12px
            / 1px 24px
            no-repeat,

            linear-gradient(
                #E8C96A,
                #E8C96A
            )
            left 12px bottom 12px
            / 24px 1px
            no-repeat,

            linear-gradient(
                #E8C96A,
                #E8C96A
            )
            left 12px bottom 12px
            / 1px 24px
            no-repeat,

            linear-gradient(
                #E8C96A,
                #E8C96A
            )
            right 12px bottom 12px
            / 24px 1px
            no-repeat,

            linear-gradient(
                #E8C96A,
                #E8C96A
            )
            right 12px bottom 12px
            / 1px 24px
            no-repeat,

            linear-gradient(
                90deg,
                transparent,
                var(--epl-card-status-accent),
                transparent
            )
            center top
            / 38% 2px
            no-repeat,

            radial-gradient(
                circle at 8% 8%,
                rgba(255, 40, 130, 0.13),
                transparent 25%
            ),

            radial-gradient(
                circle at 90% 10%,
                rgba(0, 255, 133, 0.12),
                transparent 24%
            ),

            repeating-linear-gradient(
                125deg,
                rgba(55, 0, 60, 0.018) 0,
                rgba(55, 0, 60, 0.018) 1px,
                transparent 1px,
                transparent 27px
            ),

            linear-gradient(
                135deg,
                rgba(255, 251, 254, 0.99) 0%,
                rgba(250, 248, 255, 0.98) 48%,
                rgba(246, 255, 251, 0.98) 100%
            );

        box-shadow:
            0 0 0 2px rgba(232, 201, 106, 0.94),
            0 0 0 4px rgba(55, 0, 60, 0.96),
            0 18px 44px rgba(55, 0, 60, 0.15),
            0 8px 24px var(--epl-card-status-glow),
            inset 0 0 0 1px rgba(255, 255, 255, 0.88);

        position:
            relative;

        overflow:
            hidden;

        isolation:
            isolate;
    }}

    @media (max-width: 768px) {{
        {{
            padding:
                20px 16px 15px 16px;

            margin:
                4px 3px 26px 3px;

            border-radius:
                18px;

            background:
                linear-gradient(
                    #E8C96A,
                    #E8C96A
                )
                left 9px top 9px
                / 18px 1px
                no-repeat,

                linear-gradient(
                    #E8C96A,
                    #E8C96A
                )
                left 9px top 9px
                / 1px 18px
                no-repeat,

                linear-gradient(
                    #E8C96A,
                    #E8C96A
                )
                right 9px top 9px
                / 18px 1px
                no-repeat,

                linear-gradient(
                    #E8C96A,
                    #E8C96A
                )
                right 9px top 9px
                / 1px 18px
                no-repeat,

                linear-gradient(
                    #E8C96A,
                    #E8C96A
                )
                left 9px bottom 9px
                / 18px 1px
                no-repeat,

                linear-gradient(
                    #E8C96A,
                    #E8C96A
                )
                left 9px bottom 9px
                / 1px 18px
                no-repeat,

                linear-gradient(
                    #E8C96A,
                    #E8C96A
                )
                right 9px bottom 9px
                / 18px 1px
                no-repeat,

                linear-gradient(
                    #E8C96A,
                    #E8C96A
                )
                right 9px bottom 9px
                / 1px 18px
                no-repeat,

                linear-gradient(
                    90deg,
                    transparent,
                    var(--epl-card-status-accent),
                    transparent
                )
                center top
                / 44% 2px
                no-repeat,

                radial-gradient(
                    circle at 5% 5%,
                    rgba(255, 40, 130, 0.10),
                    transparent 24%
                ),

                radial-gradient(
                    circle at 94% 7%,
                    rgba(0, 255, 133, 0.10),
                    transparent 22%
                ),

                linear-gradient(
                    135deg,
                    rgba(255, 251, 254, 0.99),
                    rgba(248, 250, 255, 0.98) 54%,
                    rgba(247, 255, 252, 0.98)
                );
        }}
    }}
    """

def local_asset_exists(asset_path: str) -> bool:
    """
    Kiểm tra file ảnh local có tồn tại không.
    Nếu thiếu ảnh thì không render logo, tránh ảnh vỡ trong card.
    """
    if not asset_path:
        return False

    asset_path = str(asset_path).strip()

    if asset_path.startswith(
        ("http://", "https://", "data:")
    ):
        return True

    normalized_path = asset_path.replace("\\", "/")
    raw_path = Path(normalized_path)

    candidate_paths = []

    if raw_path.is_absolute():
        candidate_paths.append(raw_path)
    else:
        candidate_paths.append(
            BASE_DIR / raw_path
        )

        if normalized_path.startswith(
            "data/static/"
        ):
            candidate_paths.append(
                BASE_DIR
                / normalized_path.replace(
                    "data/static/",
                    "static/",
                    1
                )
            )

        candidate_paths.append(
            BASE_DIR
            / "static"
            / raw_path.name
        )

    return any(
        candidate_path.exists()
        and candidate_path.is_file()
        for candidate_path in candidate_paths
    )


def get_winner_team_display_name(row) -> str:
    """
    Lấy tên đội thắng để dùng cho alt/title của logo.
    """
    if row is None:
        return ""

    display_name = row.get(
        "winner_team_display_name"
    )

    if (
        display_name is not None
        and not pd.isna(display_name)
        and str(display_name).strip()
    ):
        return str(display_name).strip()

    winner_name = row.get(
        "winner_team_name"
    )

    if (
        winner_name is not None
        and not pd.isna(winner_name)
        and str(winner_name).strip()
    ):
        return str(winner_name).strip()

    winner_team_id = to_optional_int(
        row.get("winner_team_id")
    )

    home_team_id = to_optional_int(
        row.get("home_team_id")
    )

    away_team_id = to_optional_int(
        row.get("away_team_id")
    )

    if (
        winner_team_id is not None
        and winner_team_id == home_team_id
    ):
        return str(
            row.get("home_team_name") or ""
        ).strip()

    if (
        winner_team_id is not None
        and winner_team_id == away_team_id
    ):
        return str(
            row.get("away_team_name") or ""
        ).strip()

    return ""


def get_winner_team_logo_path(row) -> str:
    """
    Lấy logo của đội thắng từ metadata đã JOIN trong load_matches().
    """
    if row is None:
        return ""

    direct_logo_path = row.get(
        "winner_team_logo_path"
    )

    if (
        direct_logo_path is not None
        and not pd.isna(direct_logo_path)
        and str(direct_logo_path).strip()
    ):
        return str(direct_logo_path).strip()

    winner_team_id = to_optional_int(
        row.get("winner_team_id")
    )

    home_team_id = to_optional_int(
        row.get("home_team_id")
    )

    away_team_id = to_optional_int(
        row.get("away_team_id")
    )

    if winner_team_id is None:
        return ""

    if winner_team_id == home_team_id:
        logo_path = row.get(
            "home_team_logo_path"
        )

    elif winner_team_id == away_team_id:
        logo_path = row.get(
            "away_team_logo_path"
        )

    else:
        return ""

    if (
        logo_path is None
        or pd.isna(logo_path)
    ):
        return ""

    return str(logo_path).strip()


def should_render_winner_logo(row) -> bool:
    """
    Chỉ hiển thị logo khi:
    - Trận đã kết thúc.
    - Có đội thắng, không phải trận hòa.
    - Metadata có logo hợp lệ.
    """
    if row is None:
        return False

    if not to_bool(
        row.get("is_finished")
    ):
        return False

    if (
        to_optional_int(
            row.get("winner_team_id")
        )
        is None
    ):
        return False

    logo_path = get_winner_team_logo_path(
        row
    )

    if not logo_path:
        return False

    return local_asset_exists(
        logo_path
    )


def render_winner_logo_overlay(row):
    """
    Hiển thị logo đội thắng bằng đúng cơ chế overlay cờ
    đã dùng ổn định trong app World Cup.

    Chỉ thay nguồn ảnh từ cờ sang logo câu lạc bộ.
    Vị trí, hiệu ứng, kích thước và responsive được giữ nguyên.
    """
    if not should_render_winner_logo(row):
        return

    match_id = int(row.get("match_id"))

    logo_asset_path = get_winner_team_logo_path(row)
    logo_src = resolve_asset_src(logo_asset_path)

    if not logo_src:
        return

    winner_name = (
        get_winner_team_display_name(row)
        or "Đội thắng"
    )

    safe_winner_name = html.escape(
        winner_name,
        quote=True
    )

    safe_logo_src = html.escape(
        logo_src,
        quote=True
    )

    logo_html = f"""
    <style>
    @keyframes wcWinnerLogoWave_{match_id} {{
        0% {{
            transform:
                perspective(520px)
                rotateY(-9deg)
                skewY(-1deg)
                translateY(0);
            filter: brightness(1.02) saturate(1.08);
        }}

        50% {{
            transform:
                perspective(520px)
                rotateY(9deg)
                skewY(1.15deg)
                translateY(-1px);
            filter: brightness(1.08) saturate(1.14);
        }}

        100% {{
            transform:
                perspective(520px)
                rotateY(-9deg)
                skewY(-1deg)
                translateY(0);
            filter: brightness(1.02) saturate(1.08);
        }}
    }}

    @keyframes wcWinnerLogoShine_{match_id} {{
        0% {{
            transform: translateX(-150%) skewX(-22deg);
            opacity: 0;
        }}

        18% {{
            opacity: 0;
        }}

        38% {{
            opacity: 0.75;
        }}

        62% {{
            opacity: 0.75;
        }}

        82% {{
            opacity: 0;
        }}

        100% {{
            transform: translateX(170%) skewX(-22deg);
            opacity: 0;
        }}
    }}

    .wc-winner-logo-overlay-{match_id} {{
        position: absolute;

        top: -50px;
        right: -48px;

        z-index: 3;

        width: 122px;
        height: 72px;

        pointer-events: none;

        display: flex;
        align-items: flex-start;
        justify-content: flex-start;
    }}

    .wc-winner-logo-frame-{match_id} {{
        position: absolute;
    
        left: 11px;
        top: 8px;
    
        width: fit-content;
        height: fit-content;
    
        max-width: 98px;
        max-height: 64px;
    
        border: none;
        border-radius: 0;
        background: transparent;
        box-shadow: none;
    
        overflow: visible;
        transform-origin: center;
    
        animation:
            wcWinnerLogoWave_{match_id}
            2.4s
            ease-in-out
            infinite;
    }}

    .wc-winner-logo-img-{match_id} {{
        display: block;
    
        width: auto;
        height: auto;
    
        max-width: 56px;
        max-height: 50px;
    
        object-fit: contain;
        object-position: center;
    
        filter:
            drop-shadow(
                0 8px 12px
                rgba(15, 23, 42, 0.24)
            );
    }}
    .wc-winner-logo-shine-{match_id} {{
        display: none;
    }}
    @media (max-width: 768px) {{
        .wc-winner-logo-overlay-{match_id} {{
            top: -25px;
            right: -20px;

            width: 84px;
            height: 52px;
        }}

        .wc-winner-logo-frame-{match_id} {{
            left: 8px;
            top: 7px;

            max-width: 66px;
            max-height: 39px;

            border-radius: 6px;
        }}

        .wc-winner-logo-img-{match_id} {{
            max-width: 66px;
            max-height: 39px;
        }}

        .wc-winner-logo-shine-{match_id} {{
            width: 48%;
        }}
    }}

    @media (max-width: 390px) {{
        .wc-winner-logo-overlay-{match_id} {{
            top: 15px;
            right: 10px;

            width: 78px;
            height: 50px;
        }}

        .wc-winner-logo-frame-{match_id} {{
            max-width: 61px;
            max-height: 36px;
        }}

        .wc-winner-logo-img-{match_id} {{
            max-width: 61px;
            max-height: 36px;
        }}
    }}
    </style>

    <div class="wc-winner-logo-overlay-{match_id}" title="Đội thắng: {safe_winner_name}">
        <div class="wc-winner-logo-frame-{match_id}">
            <img class="wc-winner-logo-img-{match_id}" src="{safe_logo_src}" alt="Logo {safe_winner_name}" />
            <div class="wc-winner-logo-shine-{match_id}"></div>
        </div>
    </div>
    """

    st.markdown(
        textwrap.dedent(logo_html).strip(),
        unsafe_allow_html=True
    )

def get_countdown_seconds_to_kickoff(kickoff_time_utc) -> int | None:
    """
    Tính số giây còn lại đến giờ kickoff.

    Trả về:
    - None nếu không parse được thời gian.
    - 0 nếu đã đến/qua giờ kickoff.
    - Số giây còn lại nếu trận chưa diễn ra.
    """
    kickoff = parse_utc_datetime(kickoff_time_utc)

    if pd.isna(kickoff):
        return None

    now = pd.Timestamp.now(tz="UTC")
    remaining_seconds = int((kickoff - now).total_seconds())

    return max(0, remaining_seconds)


def format_countdown_seconds(total_seconds: int) -> str:
    """
    Format countdown:
    - Dưới 1 ngày: 12h 59m 12s
    - Từ 1 ngày trở lên: 2d 1h 5m
    """
    total_seconds = max(0, int(total_seconds or 0))

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if days >= 1:
        return f"{days}d {hours}h {minutes}m"

    return f"{hours}h {minutes}m {seconds}s"


def inject_match_countdown_runtime():
    """
    Một runtime duy nhất cập nhật tất cả badge countdown trên trang.

    Bản cũ tạo một iframe + một setInterval cho từng card. Khi một ngày có
    nhiều trận, số iframe/timer tăng tuyến tính và làm trình duyệt tốn CPU/RAM.
    """
    st.markdown(
        """
        <style>
        .wc-countdown-badge {
            display: inline-block;
            padding: 7px 13px;
            border-radius: 999px;
            font-weight: 850;
            font-size: 13px;
            line-height: 1.25;
            margin-bottom: 8px;
            border: 1px solid rgba(15,23,42,0.06);
            font-family:
                system-ui,
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;
            white-space: nowrap;
            box-sizing: border-box;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    components.html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;
            const runtimeKey = "__eplMatchCountdownRuntime";
            const previousRuntime = parentWindow[runtimeKey];

            if (
                previousRuntime
                && typeof previousRuntime.stop === "function"
            ) {
                previousRuntime.stop();
            }

            let timerId = null;
            let emptyTicks = 0;

            const formatCountdown = (totalSeconds) => {
                totalSeconds = Math.max(
                    0,
                    Math.floor(totalSeconds)
                );

                const days = Math.floor(
                    totalSeconds / 86400
                );
                const hours = Math.floor(
                    (totalSeconds % 86400) / 3600
                );
                const minutes = Math.floor(
                    (totalSeconds % 3600) / 60
                );
                const seconds = totalSeconds % 60;

                if (days >= 1) {
                    return (
                        days + "d "
                        + hours + "h "
                        + minutes + "m"
                    );
                }

                return (
                    hours + "h "
                    + minutes + "m "
                    + seconds + "s"
                );
            };

            const stop = () => {
                if (timerId !== null) {
                    parentWindow.clearInterval(timerId);
                    timerId = null;
                }
            };

            const updateAllCountdowns = () => {
                const badges = parentDocument.querySelectorAll(
                    ".wc-countdown-badge[data-kickoff-ms]"
                );

                if (!badges.length) {
                    emptyTicks += 1;

                    // Tự dừng khi người dùng đã chuyển sang trang khác.
                    if (emptyTicks >= 3) {
                        stop();
                    }

                    return;
                }

                emptyTicks = 0;
                const nowMs = Date.now();

                badges.forEach((badge) => {
                    const kickoffMs = Number(
                        badge.dataset.kickoffMs
                    );

                    if (!Number.isFinite(kickoffMs)) {
                        return;
                    }

                    const remainingMs = kickoffMs - nowMs;

                    if (remainingMs <= 0) {
                        badge.textContent = (
                            badge.dataset.expiredLabel
                            || ""
                        );
                        badge.removeAttribute(
                            "data-kickoff-ms"
                        );
                        return;
                    }

                    badge.textContent = formatCountdown(
                        remainingMs / 1000
                    );
                });
            };

            updateAllCountdowns();

            timerId = parentWindow.setInterval(
                updateAllCountdowns,
                1000
            );

            parentWindow[runtimeKey] = {
                stop
            };
        })();
        </script>
        """,
        height=0,
        scrolling=False
    )


def render_status_badge(status_info, row=None):
    """
    Hiển thị badge trạng thái ở đầu card trận đấu.

    Với trận chưa diễn ra thuộc trạng thái:
    - Đang mở dự đoán
    - Chưa xác định đội

    Badge sẽ hiển thị countdown đến giờ kickoff:
    - Dưới 1 ngày: 12h 59m 12s
    - Từ 1 ngày trở lên: 2d 1h 5m

    Các trạng thái khác giữ nguyên label cũ.
    """
    status_key = status_info.get("status_key")
    badge_label = str(status_info.get("label", ""))

    should_show_countdown = (
        row is not None
        and status_key in ["open", "unknown"]
        and not to_bool(row.get("is_finished"))
    )

    if should_show_countdown:
        remaining_seconds = get_countdown_seconds_to_kickoff(
            row.get("kickoff_time_utc")
        )

        if remaining_seconds is not None and remaining_seconds > 0:
            kickoff = parse_utc_datetime(row.get("kickoff_time_utc"))
            kickoff_epoch_ms = int(kickoff.timestamp() * 1000)

            initial_countdown_text = format_countdown_seconds(
                remaining_seconds
            )

            safe_initial_text = html.escape(initial_countdown_text)
            safe_expired_label = html.escape(badge_label)
            safe_badge_bg = html.escape(str(status_info["badge_bg"]))
            safe_badge_text = html.escape(str(status_info["badge_text"]))

            st.markdown(
                (
                    '<div class="wc-countdown-badge" '
                    f'data-kickoff-ms="{kickoff_epoch_ms}" '
                    f'data-expired-label="{safe_expired_label}" '
                    f'style="background:{safe_badge_bg};'
                    f'color:{safe_badge_text};">'
                    f'{safe_initial_text}'
                    '</div>'
                ),
                unsafe_allow_html=True
            )

            return

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
            {html.escape(badge_label)}
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
    try:
        schema_columns = read_sql(
            """
            SELECT
                table_name AS name,
                column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN (
                  'teams',
                  'matches',
                  'users',
                  'predictions',
                  'prediction_history',
                  'login_sessions',
                  'daily_checkins',
                  'daily_checkin_rewards',
                  'final_poster_popup_views',
                  'match_goals'
              )
            """
        )
    except Exception as e:
        st.error("Không kiểm tra được schema Supabase.")
        st.exception(e)
        st.stop()

    table_names = set(schema_columns["name"].tolist())

    required_tables = {
        "teams",
        "matches",
        "users",
        "predictions",
        "prediction_history",
        "login_sessions",
        "daily_checkins",
        "daily_checkin_rewards",
        "final_poster_popup_views",
        "match_goals"
    }

    missing_tables = sorted(
        required_tables - table_names
    )

    if missing_tables:
        st.error(
            "Database đang thiếu bảng bắt buộc: "
            + ", ".join(missing_tables)
            + ". Hãy kiểm tra lại schema Supabase."
        )
        st.stop()

    actual_user_columns = set(
        schema_columns.loc[
            schema_columns["name"] == "users",
            "column_name"
        ].tolist()
    )

    required_user_columns = {
        "display_name_changed_at"
    }

    missing_user_columns = sorted(
        required_user_columns
        - actual_user_columns
    )

    if missing_user_columns:
        st.error(
            "Bảng `users` đang thiếu cột phục vụ đổi tên: "
            + ", ".join(missing_user_columns)
            + ". Hãy chạy migration database trước khi mở app."
        )
        st.stop()

    actual_team_columns = set(
        schema_columns.loc[
            schema_columns["name"] == "teams",
            "column_name"
        ].tolist()
    )

    required_team_columns = {
        "team_id",
        "team_name",
        "logo_path",
        "stadium_name",
        "stadium_city"
    }

    missing_team_columns = sorted(
        required_team_columns
        - actual_team_columns
    )

    if missing_team_columns:
        st.error(
            "Bảng `teams` đang thiếu cột metadata: "
            + ", ".join(missing_team_columns)
            + ". Hãy chạy câu lệnh ALTER TABLE trước khi mở app."
        )
        st.stop()

    actual_match_columns = set(
        schema_columns.loc[
            schema_columns["name"] == "matches",
            "column_name"
        ].tolist()
    )

    required_match_columns = {
        "season_slug"
    }

    missing_match_columns = sorted(
        required_match_columns
        - actual_match_columns
    )

    if missing_match_columns:
        st.error(
            "Bảng `matches` đang thiếu cột phân mùa: "
            + ", ".join(missing_match_columns)
            + ". Hãy thêm cột này trước khi mở app."
        )
        st.stop()

def init_app_tables():
    execute_sql(
        """
        ALTER TABLE matches
        ADD COLUMN IF NOT EXISTS season_slug TEXT
        """
    )

    execute_sql(
        """
        UPDATE matches
        SET season_slug = CASE
            WHEN kickoff_time_utc::timestamptz >= TIMESTAMPTZ '2026-08-01 00:00:00+00'
                THEN '2026-27'
            ELSE '2025-26'
        END
        WHERE season_slug IS NULL
           OR TRIM(season_slug) = ''
        """
    )

    execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_matches_season_slug
        ON matches(season_slug)
        """
    )

    execute_sql(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'player',
            created_at TEXT NOT NULL,
            display_name_changed_at TIMESTAMPTZ
        )
        """
    )

    execute_sql(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS display_name_changed_at TIMESTAMPTZ
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

    # Các index phục vụ trực tiếp những truy vấn đọc thường xuyên nhất.
    # Chỉ chạy trong chế độ migration, không phát sinh DDL ở mỗi app rerun.
    execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_matches_season_kickoff
        ON matches (season_slug, kickoff_time_utc)
        """
    )

    execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_predictions_match_id
        ON predictions (match_id)
        """
    )

    execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_predictions_user_star
        ON predictions (user_id, star_type, match_id)
        """
    )

    execute_sql(
        """
        DO $$
        BEGIN
            IF to_regclass('public.match_goals') IS NOT NULL THEN
                CREATE INDEX IF NOT EXISTS idx_match_goals_match_id_goal_key
                ON match_goals (match_id, goal_key);
            END IF;

            IF to_regclass('public.daily_checkin_rewards') IS NOT NULL THEN
                CREATE INDEX IF NOT EXISTS idx_daily_checkin_rewards_user_id
                ON daily_checkin_rewards (user_id);
            END IF;

            IF to_regclass('public.daily_checkins') IS NOT NULL THEN
                CREATE INDEX IF NOT EXISTS idx_daily_checkins_user_cycle_day
                ON daily_checkins (user_id, cycle_no, day_no);
            END IF;

            IF to_regclass('public.login_sessions') IS NOT NULL THEN
                CREATE INDEX IF NOT EXISTS idx_login_sessions_expires_at
                ON login_sessions (expires_at);
            END IF;

            IF to_regclass('public.final_poster_popup_views') IS NOT NULL THEN
                CREATE INDEX IF NOT EXISTS idx_final_poster_views_user_date
                ON final_poster_popup_views (user_id, popup_date);
            END IF;
        END $$;
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
    if RUN_DB_MIGRATIONS:
        check_base_database()
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
        WITH expired_sessions AS (
            DELETE FROM login_sessions
            WHERE expires_at <= NOW()
            RETURNING session_id
        )
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

def clear_daily_checkin_cache():
    """
    Chỉ clear cache liên quan đến điểm danh và quota sao thưởng.
    Không clear matches/predictions/users vì điểm danh không làm thay đổi các dữ liệu đó.
    """
    try:
        get_daily_checkin_bonus_counts_cached.clear()
    except Exception:
        pass

    try:
        get_all_daily_checkin_bonus_counts_cached.clear()
    except Exception:
        pass

    try:
        get_daily_checkin_state_cached.clear()
    except Exception:
        pass

    try:
        build_leaderboard_df.clear()
    except Exception:
        pass

@st.cache_data(
    ttl=60,
    max_entries=512,
    show_spinner=False
)
def get_daily_checkin_bonus_counts_cached(user_id: int) -> dict:
    try:
        row = fetch_one(
            """
            SELECT
                COALESCE(SUM(CASE WHEN reward_type = 'hope' THEN amount ELSE 0 END), 0) AS hope_bonus,
                COALESCE(SUM(CASE WHEN reward_type = 'super' THEN amount ELSE 0 END), 0) AS super_bonus
            FROM daily_checkin_rewards
            WHERE user_id = :user_id
            """,
            {
                "user_id": int(user_id)
            }
        )
    except Exception:
        return {
            "hope_bonus": 0,
            "super_bonus": 0
        }

    if row is None:
        return {
            "hope_bonus": 0,
            "super_bonus": 0
        }

    return {
        "hope_bonus": int(row.get("hope_bonus") or 0),
        "super_bonus": int(row.get("super_bonus") or 0)
    }


def get_daily_checkin_bonus_counts(user_id: int) -> dict:
    return get_daily_checkin_bonus_counts_cached(int(user_id))


@st.cache_data(ttl=60, show_spinner=False)
def get_all_daily_checkin_bonus_counts_cached() -> dict[int, dict]:
    """
    Tải thưởng điểm danh của toàn bộ user bằng một query.
    Chỉ dùng ở bảng xếp hạng để tránh một query riêng cho từng người chơi.
    """
    try:
        rewards = read_sql(
            """
            SELECT
                user_id,
                COALESCE(SUM(CASE WHEN reward_type = 'hope' THEN amount ELSE 0 END), 0) AS hope_bonus,
                COALESCE(SUM(CASE WHEN reward_type = 'super' THEN amount ELSE 0 END), 0) AS super_bonus
            FROM daily_checkin_rewards
            GROUP BY user_id
            """
        )
    except Exception:
        return {}

    if rewards.empty:
        return {}

    result = {}

    for row in rewards.itertuples(index=False):
        result[int(row.user_id)] = {
            "hope_bonus": int(row.hope_bonus or 0),
            "super_bonus": int(row.super_bonus or 0)
        }

    return result


def get_user_star_quota(user_id: int) -> dict:
    """
    Quota sao thực tế = quota gốc + sao thưởng từ điểm danh.
    """
    bonus = get_daily_checkin_bonus_counts(user_id)

    hope_total = HOPE_STARS_PER_USER + int(bonus["hope_bonus"])
    super_total = SUPER_STARS_PER_USER + int(bonus["super_bonus"])

    return {
        "hope_total": hope_total,
        "super_total": super_total,
        "hope_bonus": int(bonus["hope_bonus"]),
        "super_bonus": int(bonus["super_bonus"])
    }


def get_daily_checkin_state_from_db(user_id: int) -> dict:
    today = today_vietnam_date()

    try:
        df = read_sql(
            """
            SELECT
                checkin_date,
                cycle_no,
                day_no,
                created_at
            FROM daily_checkins
            WHERE user_id = :user_id
            ORDER BY cycle_no ASC, day_no ASC
            """,
            {
                "user_id": int(user_id)
            }
        )
    except Exception:
        return {
            "cycle_no": 1,
            "claimed_days": [],
            "next_day_no": 1,
            "checked_today": False,
            "today_day_no": None
        }

    if df.empty:
        return {
            "cycle_no": 1,
            "claimed_days": [],
            "next_day_no": 1,
            "checked_today": False,
            "today_day_no": None
        }

    df["checkin_date"] = pd.to_datetime(
        df["checkin_date"],
        errors="coerce"
    ).dt.date

    today_rows = df[df["checkin_date"] == today]

    checked_today = not today_rows.empty
    today_day_no = None

    if checked_today:
        today_day_no = int(today_rows.iloc[-1]["day_no"])

    max_cycle_no = int(df["cycle_no"].max())

    current_cycle_df = df[df["cycle_no"].astype(int) == max_cycle_no].copy()

    current_cycle_days = sorted(
        int(day)
        for day in current_cycle_df["day_no"].dropna().tolist()
    )

    cycle_completed = CHECKIN_CYCLE_DAYS in current_cycle_days

    if cycle_completed:
        cycle_no = max_cycle_no + 1
        claimed_days = []
    else:
        cycle_no = max_cycle_no
        claimed_days = current_cycle_days

    if checked_today:
        next_day_no = None
    else:
        next_day_no = min(len(claimed_days) + 1, CHECKIN_CYCLE_DAYS)

    return {
        "cycle_no": int(cycle_no),
        "claimed_days": claimed_days,
        "next_day_no": next_day_no,
        "checked_today": checked_today,
        "today_day_no": today_day_no
    }


@st.cache_data(
    ttl=60,
    max_entries=512,
    show_spinner=False
)
def get_daily_checkin_state_cached(user_id: int, today_key: str) -> dict:
    return get_daily_checkin_state_from_db(int(user_id))


def get_daily_checkin_state(user_id: int, use_cache: bool = True) -> dict:
    today_key = today_vietnam_date().isoformat()

    if use_cache:
        return get_daily_checkin_state_cached(
            int(user_id),
            today_key
        )

    return get_daily_checkin_state_from_db(int(user_id))


def claim_daily_checkin(user_id: int) -> dict:
    """
    Ghi nhận điểm danh hôm nay.
    Nếu đạt mốc ngày 5 hoặc ngày 7 thì ghi nhận thưởng sao.
    """
    user_id = int(user_id)
    state = get_daily_checkin_state(user_id, use_cache=False)

    if state["checked_today"]:
        return {
            "status": "already_checked",
            "reward_type": None,
            "reward_label": None,
            "day_no": state.get("today_day_no"),
            "cycle_no": state.get("cycle_no")
        }

    cycle_no = int(state["cycle_no"])
    day_no = int(state["next_day_no"] or 1)
    today = today_vietnam_date()

    reward_type = None
    reward_label = None
    reward_icon = None

    if day_no == CHECKIN_HOPE_REWARD_DAY:
        reward_type = STAR_TYPE_HOPE
        reward_label = "1 Ngôi sao hy vọng"
        reward_icon = "⭐"

    elif day_no == CHECKIN_SUPER_REWARD_DAY:
        reward_type = STAR_TYPE_SUPER
        reward_label = "1 Siêu sao"
        reward_icon = "✨"

    with get_engine().begin() as conn:
        inserted = conn.execute(
            text(
                """
                INSERT INTO daily_checkins (
                    user_id,
                    checkin_date,
                    cycle_no,
                    day_no
                )
                VALUES (
                    :user_id,
                    :checkin_date,
                    :cycle_no,
                    :day_no
                )
                ON CONFLICT (user_id, checkin_date)
                DO NOTHING
                RETURNING checkin_id
                """
            ),
            {
                "user_id": user_id,
                "checkin_date": today,
                "cycle_no": cycle_no,
                "day_no": day_no
            }
        ).mappings().fetchone()

        if inserted is None:
            return {
                "status": "already_checked",
                "reward_type": None,
                "reward_label": None,
                "day_no": day_no,
                "cycle_no": cycle_no
            }

        if reward_type is not None:
            conn.execute(
                text(
                    """
                    INSERT INTO daily_checkin_rewards (
                        user_id,
                        cycle_no,
                        day_no,
                        reward_type,
                        amount
                    )
                    VALUES (
                        :user_id,
                        :cycle_no,
                        :day_no,
                        :reward_type,
                        1
                    )
                    ON CONFLICT (user_id, cycle_no, day_no, reward_type)
                    DO NOTHING
                    """
                ),
                {
                    "user_id": user_id,
                    "cycle_no": cycle_no,
                    "day_no": day_no,
                    "reward_type": reward_type
                }
            )

    clear_daily_checkin_cache()

    return {
        "status": "checked",
        "reward_type": reward_type,
        "reward_label": reward_label,
        "reward_icon": reward_icon,
        "day_no": day_no,
        "cycle_no": cycle_no
    }
# ============================================================
# 5. AUTH FUNCTIONS
# ============================================================

def normalize_display_name(display_name: str) -> str:
    """
    Chuẩn hóa khoảng trắng nhưng vẫn giữ nguyên chữ hoa/thường và Unicode.
    """
    return re.sub(
        r"\s+",
        " ",
        str(display_name or "")
    ).strip()


def format_vietnam_datetime(datetime_value) -> str:
    timestamp = pd.Timestamp(datetime_value)

    if pd.isna(timestamp):
        return ""

    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")

    return (
        timestamp
        .tz_convert("Asia/Ho_Chi_Minh")
        .strftime("%H:%M, %d/%m/%Y")
    )


def get_display_name_change_state(user_id: int) -> dict:
    """
    Đọc trực tiếp từ database khi người dùng bấm nút sửa tên.
    Không cache để trạng thái luôn đúng giữa nhiều tab/thiết bị.
    """
    state = fetch_one(
        """
        SELECT
            display_name,
            display_name_changed_at,
            (
                display_name_changed_at IS NULL
                OR display_name_changed_at
                   + (:cooldown_days * INTERVAL '1 day')
                   <= NOW()
            ) AS can_change,
            CASE
                WHEN display_name_changed_at IS NULL THEN NULL
                ELSE display_name_changed_at
                     + (:cooldown_days * INTERVAL '1 day')
            END AS next_available_at
        FROM users
        WHERE user_id = :user_id
        """,
        {
            "user_id": int(user_id),
            "cooldown_days": DISPLAY_NAME_CHANGE_COOLDOWN_DAYS
        }
    )

    if state is None:
        raise ValueError(
            "Không tìm thấy tài khoản để kiểm tra quyền đổi tên."
        )

    state["can_change"] = to_bool(state.get("can_change"))
    return state


def update_user_display_name(
    user_id: int,
    new_display_name: str
) -> dict:
    """
    Đổi tên trong một transaction và khóa đúng user hiện tại.

    Advisory lock dùng chung với create_user() để việc kiểm tra tên trùng
    không thể bị vượt qua bởi hai yêu cầu đăng ký/đổi tên đồng thời.
    """
    new_display_name = normalize_display_name(
        new_display_name
    )

    if not new_display_name:
        raise ValueError(
            "Tên hiển thị không được để trống."
        )

    if len(new_display_name) > DISPLAY_NAME_MAX_LENGTH:
        raise ValueError(
            "Tên hiển thị không được vượt quá "
            f"{DISPLAY_NAME_MAX_LENGTH} ký tự."
        )

    try:
        with get_engine().begin() as conn:
            conn.execute(
                text(
                    """
                    SELECT pg_advisory_xact_lock(
                        2026072901
                    )
                    """
                )
            )

            current_user = conn.execute(
                text(
                    """
                    SELECT
                        display_name,
                        display_name_changed_at,
                        NOW() AS checked_at
                    FROM users
                    WHERE user_id = :user_id
                    FOR UPDATE
                    """
                ),
                {
                    "user_id": int(user_id)
                }
            ).mappings().fetchone()

            if current_user is None:
                raise ValueError(
                    "Không tìm thấy tài khoản để đổi tên."
                )

            current_display_name = normalize_display_name(
                current_user.get("display_name")
            )

            if new_display_name == current_display_name:
                raise ValueError(
                    "Tên mới cần khác tên hiển thị hiện tại."
                )

            changed_at = current_user.get(
                "display_name_changed_at"
            )

            if changed_at is not None:
                next_available_at = (
                    changed_at
                    + timedelta(
                        days=DISPLAY_NAME_CHANGE_COOLDOWN_DAYS
                    )
                )

                if current_user["checked_at"] < next_available_at:
                    raise ValueError(
                        "Bạn chưa thể đổi tên lúc này. "
                        "Có thể đổi lại từ "
                        f"{format_vietnam_datetime(next_available_at)}."
                    )

            duplicate_name = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM users
                    WHERE user_id <> :user_id
                      AND LOWER(TRIM(display_name))
                          = LOWER(TRIM(:display_name))
                    LIMIT 1
                    """
                ),
                {
                    "user_id": int(user_id),
                    "display_name": new_display_name
                }
            ).fetchone()

            if duplicate_name is not None:
                raise ValueError(
                    "Tên hiển thị này đã được sử dụng. "
                    "Hãy chọn tên khác."
                )

            updated_user = conn.execute(
                text(
                    """
                    UPDATE users
                    SET
                        display_name = :display_name,
                        display_name_changed_at = NOW()
                    WHERE user_id = :user_id
                    RETURNING
                        display_name,
                        display_name_changed_at
                    """
                ),
                {
                    "user_id": int(user_id),
                    "display_name": new_display_name
                }
            ).mappings().one()

    except IntegrityError as error:
        raise ValueError(
            "Tên hiển thị này đã được sử dụng. "
            "Hãy chọn tên khác."
        ) from error

    try:
        load_users.clear()
    except (NameError, AttributeError):
        pass

    try:
        build_leaderboard_df.clear()
    except (NameError, AttributeError):
        pass

    return dict(updated_user)


def create_user(username: str, display_name: str, password: str):
    username = username.strip().lower()
    display_name = normalize_display_name(display_name)

    if not username:
        raise ValueError("Username không được để trống.")

    if not display_name:
        raise ValueError("Tên hiển thị không được để trống.")

    if len(display_name) > DISPLAY_NAME_MAX_LENGTH:
        raise ValueError(
            "Tên hiển thị không được vượt quá "
            f"{DISPLAY_NAME_MAX_LENGTH} ký tự."
        )

    if len(password) < 8:
        raise ValueError("Mật khẩu nên có ít nhất 8 ký tự.")

    salt, password_hash = hash_password(password)

    try:
        with get_engine().begin() as conn:
            # Tuần tự hóa luồng đăng ký để không thể có hai tài khoản đầu tiên
            # cùng nhận role admin hoặc hai display_name trùng nhau do race.
            conn.execute(
                text(
                    """
                    SELECT pg_advisory_xact_lock(
                        2026072901
                    )
                    """
                )
            )

            user_state = conn.execute(
                text(
                    """
                    SELECT
                        COUNT(*)::INTEGER AS user_count,
                        COALESCE(
                            BOOL_OR(username = :username),
                            FALSE
                        ) AS username_exists,
                        COALESCE(
                            BOOL_OR(
                                LOWER(TRIM(display_name))
                                = LOWER(TRIM(:display_name))
                            ),
                            FALSE
                        ) AS display_name_exists
                    FROM users
                    """
                ),
                {
                    "username": username,
                    "display_name": display_name
                }
            ).mappings().one()

            if to_bool(user_state["username_exists"]):
                raise ValueError(
                    "Username này đã tồn tại."
                )

            if to_bool(user_state["display_name_exists"]):
                raise ValueError(
                    "Tên hiển thị này đã được sử dụng. "
                    "Hãy chọn tên khác."
                )

            role = (
                "admin"
                if int(user_state["user_count"]) == 0
                else "player"
            )

            conn.execute(
                text(
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
                    """
                ),
                {
                    "username": username,
                    "display_name": display_name,
                    "password_salt": salt,
                    "password_hash": password_hash,
                    "role": role,
                    "created_at": now_utc_iso()
                }
            )

        # Tạo user chỉ làm thay đổi danh sách người chơi và BXH.
        # Không xóa matches/predictions/goal scorers vì sẽ gây query lại
        # toàn bộ dữ liệu ngay sau khi đăng ký.
        try:
            load_users.clear()
        except (NameError, AttributeError):
            pass

        try:
            build_leaderboard_df.clear()
        except (NameError, AttributeError):
            pass

    except IntegrityError:
        raise ValueError("Username hoặc tên hiển thị đã tồn tại.")

    return role


def login_user(username: str, password: str):
    username = username.strip().lower()

    user = fetch_one(
        """
        SELECT
            user_id,
            username,
            display_name,
            role,
            created_at,
            COALESCE(
                avatar_key,
                :default_avatar_key
            ) AS avatar_key,
            password_salt,
            password_hash
        FROM users
        WHERE username = :username
        """,
        {
            "username": username,
            "default_avatar_key": DEFAULT_AVATAR_KEY
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

    # Không đưa salt/hash vào session_state hoặc cookie flow.
    user.pop("password_salt", None)
    user.pop("password_hash", None)

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

@st.cache_resource(show_spinner=False)
def get_prediction_cache_revision_store() -> dict:
    """
    Revision nhỏ dùng làm cache key thay cho việc clear toàn bộ cache.

    Một user lưu dự đoán chỉ làm mới:
    - cache tổng của đúng mùa;
    - cache cá nhân của đúng user;
    - không xóa dữ liệu cá nhân của những user khác.
    """
    return {
        "lock": threading.RLock(),
        "all_predictions": {},
        "all_user_predictions": {},
        "single_user_predictions": {}
    }


def get_all_predictions_revision(
    season_slug: str
) -> int:
    store = get_prediction_cache_revision_store()

    with store["lock"]:
        return int(
            store["all_predictions"].get(
                str(season_slug),
                0
            )
        )


def get_user_predictions_revisions(
    user_id: int,
    season_slug: str
) -> tuple[int, int]:
    store = get_prediction_cache_revision_store()
    season_slug = str(season_slug)
    user_key = (
        int(user_id),
        season_slug
    )

    with store["lock"]:
        return (
            int(
                store[
                    "all_user_predictions"
                ].get(
                    season_slug,
                    0
                )
            ),
            int(
                store[
                    "single_user_predictions"
                ].get(
                    user_key,
                    0
                )
            )
        )


def bump_prediction_cache_revisions(
    season_slug: str,
    user_id: int | None = None,
    all_users: bool = False
):
    """
    Làm mới cache theo phạm vi thay đổi thực tế.
    """
    store = get_prediction_cache_revision_store()
    season_slug = str(
        season_slug
        or DEFAULT_SEASON_SLUG
    )

    with store["lock"]:
        store["all_predictions"][season_slug] = (
            int(
                store["all_predictions"].get(
                    season_slug,
                    0
                )
            )
            + 1
        )

        if all_users:
            store[
                "all_user_predictions"
            ][season_slug] = (
                int(
                    store[
                        "all_user_predictions"
                    ].get(
                        season_slug,
                        0
                    )
                )
                + 1
            )

        elif user_id is not None:
            user_key = (
                int(user_id),
                season_slug
            )

            store[
                "single_user_predictions"
            ][user_key] = (
                int(
                    store[
                        "single_user_predictions"
                    ].get(
                        user_key,
                        0
                    )
                )
                + 1
            )


@st.cache_resource(
    ttl=30,
    max_entries=8,
    show_spinner=False
)
def load_matches(season_slug: str | None = None) -> pd.DataFrame:
    season_slug = season_slug or DEFAULT_SEASON_SLUG

    df = read_sql(
        """
        SELECT
            m.*,

            home_team.logo_path
                AS home_team_logo_path,

            home_team.stadium_name
                AS home_team_stadium_name,

            home_team.stadium_city
                AS home_team_stadium_city,

            away_team.logo_path
                AS away_team_logo_path,

            away_team.stadium_name
                AS away_team_stadium_name,

            away_team.stadium_city
                AS away_team_stadium_city,

            CASE
                WHEN m.winner_team_id = m.home_team_id
                    THEN home_team.logo_path

                WHEN m.winner_team_id = m.away_team_id
                    THEN away_team.logo_path

                ELSE NULL
            END AS winner_team_logo_path,

            COALESCE(
                NULLIF(TRIM(m.winner_team_name), ''),
                CASE
                    WHEN m.winner_team_id = m.home_team_id
                        THEN m.home_team_name

                    WHEN m.winner_team_id = m.away_team_id
                        THEN m.away_team_name

                    ELSE NULL
                END
            ) AS winner_team_display_name,

            COALESCE(
                NULLIF(TRIM(m.venue), ''),
                home_team.stadium_name
            ) AS display_venue,

            COALESCE(
                NULLIF(TRIM(m.city), ''),
                home_team.stadium_city
            ) AS display_city

        FROM matches AS m

        LEFT JOIN teams AS home_team
          ON home_team.team_id = m.home_team_id

        LEFT JOIN teams AS away_team
          ON away_team.team_id = m.away_team_id

        WHERE m.season_slug = :season_slug

        ORDER BY m.kickoff_time_utc
        """,
        {
            "season_slug": season_slug
        }
    )

    if df.empty:
        return df

    df["venue"] = df["display_venue"]
    df["city"] = df["display_city"]

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
        df["kickoff_date_filter"] = (
            df["kickoff_time_utc_dt"]
            .dt.tz_convert("Asia/Ho_Chi_Minh")
            .dt.date
        )

    return df

@st.cache_resource(
    ttl=300,
    max_entries=2,
    show_spinner=False
)
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


@st.cache_resource(
    ttl=30,
    max_entries=64,
    show_spinner=False
)
def _load_predictions_cached(
    season_slug: str,
    revision: int
) -> pd.DataFrame:
    return read_sql(
        """
        SELECT p.*
        FROM predictions AS p
        JOIN matches AS m
          ON m.match_id = p.match_id
        WHERE m.season_slug = :season_slug
        """,
        {
            "season_slug": season_slug
        }
    )


def load_predictions(
    season_slug: str | None = None
) -> pd.DataFrame:
    season_slug = (
        season_slug
        or DEFAULT_SEASON_SLUG
    )

    return _load_predictions_cached(
        season_slug,
        get_all_predictions_revision(
            season_slug
        )
    )


@st.cache_resource(
    ttl=30,
    max_entries=256,
    show_spinner=False
)
def _load_user_predictions_cached(
    user_id: int,
    season_slug: str,
    season_revision: int,
    user_revision: int
) -> pd.DataFrame:
    """
    Chỉ tải dự đoán của user hiện tại cho các màn hình cá nhân/card trận.

    Bảng xếp hạng, dashboard và chấm điểm vẫn dùng load_predictions()
    để giữ nguyên phạm vi dữ liệu toàn giải.
    """
    return read_sql(
        """
        SELECT p.*
        FROM predictions AS p
        JOIN matches AS m
          ON m.match_id = p.match_id
        WHERE p.user_id = :user_id
          AND m.season_slug = :season_slug
        """,
        {
            "user_id": int(user_id),
            "season_slug": season_slug
        }
    )


def load_user_predictions(
    user_id: int,
    season_slug: str | None = None
) -> pd.DataFrame:
    season_slug = (
        season_slug
        or DEFAULT_SEASON_SLUG
    )
    season_revision, user_revision = (
        get_user_predictions_revisions(
            int(user_id),
            season_slug
        )
    )

    return _load_user_predictions_cached(
        int(user_id),
        season_slug,
        season_revision,
        user_revision
    )


@st.cache_resource(
    ttl=900,
    max_entries=256,
    show_spinner=False
)
def _load_goal_scorers_for_match_cached(
    match_id: int
) -> pd.DataFrame:
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
        ORDER BY goal_key ASC
        """,
        {
            "match_id": int(match_id)
        }
    )


def load_goal_scorers_for_match(
    match_id: int
) -> pd.DataFrame:
    """
    Chỉ load danh sách cầu thủ ghi bàn của đúng 1 trận.

    Cache chỉ lưu kết quả thành công. Nếu Supabase lỗi tạm thời, wrapper trả
    trạng thái rỗng cho fragment hiện tại nhưng lần bấm/rerun sau vẫn có thể
    thử lại ngay, thay vì giữ lỗi rỗng trong cache suốt 15 phút.
    """
    try:
        return _load_goal_scorers_for_match_cached(
            int(match_id)
        )

    except Exception:
        LOGGER.warning(
            "Could not load goal scorers for match_id=%s",
            int(match_id),
            exc_info=True
        )
        return pd.DataFrame()

@st.cache_resource(
    ttl=300,
    max_entries=64,
    show_spinner=False
)
def load_epl_top_scorers(
    season_slug: str | None = None,
    team_id: int | None = None
) -> pd.DataFrame:
    """
    Tính danh sách ghi bàn của đúng mùa đang chọn.

    - team_id=None: top 20 cầu thủ toàn giải.
    - Có team_id: toàn bộ cầu thủ ghi bàn cho CLB đó.
    - Không tính phản lưới nhà.
    - Penalty vẫn được tính.
    """
    season_slug = season_slug or DEFAULT_SEASON_SLUG

    params = {
        "season_slug": season_slug
    }

    team_filter_sql = ""

    if team_id is not None:
        params["team_id"] = int(team_id)

        team_filter_sql = """
          AND mg.team_id = :team_id
        """

    scorers = read_sql(
        f"""
        WITH valid_goals AS (
            SELECT
                LOWER(TRIM(mg.player_name)) AS player_key,
                TRIM(mg.player_name) AS player_name,
                mg.team_id,

                COALESCE(
                    NULLIF(TRIM(t.team_name), ''),
                    NULLIF(TRIM(mg.team_name), ''),
                    'Chưa xác định'
                ) AS club_name,

                COALESCE(
                    t.logo_path,
                    ''
                ) AS club_logo,

                m.kickoff_time_utc,
                mg.goal_key

            FROM match_goals AS mg

            INNER JOIN matches AS m
                ON m.match_id = mg.match_id

            LEFT JOIN teams AS t
                ON t.team_id = mg.team_id

            WHERE m.season_slug = :season_slug

              AND COALESCE(
                    mg.is_own_goal,
                    FALSE
                  ) = FALSE

              AND NULLIF(
                    TRIM(mg.player_name),
                    ''
                  ) IS NOT NULL

              {team_filter_sql}
        ),

        player_totals AS (
            SELECT
                player_key,
                COUNT(*)::INTEGER AS goals

            FROM valid_goals

            GROUP BY player_key
        ),

        latest_player_info AS (
            SELECT DISTINCT ON (player_key)
                player_key,
                player_name,
                club_name,
                club_logo

            FROM valid_goals

            ORDER BY
                player_key,
                kickoff_time_utc DESC NULLS LAST,
                goal_key DESC NULLS LAST
        )

        SELECT
            info.player_name,
            info.club_name,
            info.club_logo,
            totals.goals

        FROM player_totals AS totals

        INNER JOIN latest_player_info AS info
            ON info.player_key = totals.player_key

        ORDER BY
            totals.goals DESC,
            info.player_name ASC
        """,
        params
    )

    if scorers.empty:
        return pd.DataFrame(
            columns=[
                "rank",
                "player_name",
                "club_name",
                "club_logo",
                "goals"
            ]
        )

    scorers["goals"] = pd.to_numeric(
        scorers["goals"],
        errors="coerce"
    ).fillna(0).astype(int)

    # Tất cả = đúng 20 cầu thủ đầu tiên toàn giải.
    # Chọn CLB = không giới hạn số cầu thủ.
    if team_id is None:
        scorers = scorers.head(20).copy()
    else:
        scorers = scorers.copy()

    scorers["rank"] = (
        scorers["goals"]
        .rank(
            method="min",
            ascending=False
        )
        .astype(int)
    )

    return scorers[
        [
            "rank",
            "player_name",
            "club_name",
            "club_logo",
            "goals"
        ]
    ].reset_index(drop=True)

def goal_minute_sort_key(value) -> tuple[int, int]:
    """
    Chuyển phút ghi bàn thành khóa sắp xếp.

    37      -> (37, 0)
    45+2    -> (45, 2)
    90+6’   -> (90, 6)
    """
    if value is None or pd.isna(value):
        return 10000, 0

    minute_text = str(value).strip()

    minute_match = re.search(
        r"(\d+)(?:\s*\+\s*(\d+))?",
        minute_text
    )

    if not minute_match:
        return 10000, 0

    normal_minute = int(
        minute_match.group(1)
    )

    added_minute = int(
        minute_match.group(2) or 0
    )

    return normal_minute, added_minute


def format_goal_text(row) -> str:
    """
    Format bàn thắng, ví dụ:
    Reijnders 37’
    Emile Smith Rowe 45+2’
    """
    raw_player_name = row.get(
        "player_name"
    )

    player_name = (
        ""
        if raw_player_name is None
        or pd.isna(raw_player_name)
        else str(raw_player_name).strip()
    )

    parts = [
        player_name or "Không xác định"
    ]

    raw_minute = row.get("minute")

    if (
        raw_minute is not None
        and pd.notna(raw_minute)
    ):
        minute_text = str(
            raw_minute
        ).strip()

        minute_match = re.search(
            r"(\d+)(?:\s*\+\s*(\d+))?",
            minute_text
        )

        if minute_match:
            normal_minute = (
                minute_match.group(1)
            )

            added_minute = (
                minute_match.group(2)
            )

            if added_minute:
                parts.append(
                    f"{normal_minute}+{added_minute}’"
                )
            else:
                parts.append(
                    f"{normal_minute}’"
                )

    tags = []

    if to_bool(row.get("is_own_goal")):
        tags.append("OG")

    if to_bool(row.get("is_penalty")):
        tags.append("pen")

    if tags:
        parts.append(
            f"({', '.join(tags)})"
        )

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


@st.fragment
def render_goal_scorers_for_match(
    match_id: int,
    home_name: str,
    away_name: str
):
    """
    Nút và timeline cầu thủ ghi bàn được đặt trong fragment.

    Khi bấm nút, Streamlit chỉ chạy lại khu vực này,
    không chạy lại toàn bộ trang.
    """
    match_id = int(match_id)

    toggle_key = (
        f"show_goal_scorers_{match_id}"
    )

    is_open = st.session_state.get(
        toggle_key,
        False
    )

    st.button(
        "−" if is_open else "+",
        key=f"goal_scorers_button_{match_id}",
        type="secondary",
        help=(
            "Ẩn danh sách cầu thủ ghi bàn"
            if is_open
            else "Xem cầu thủ ghi bàn"
        ),
        on_click=toggle_goal_scorers,
        args=(match_id,)
    )

    # Khi danh sách đóng, dừng ngay tại đây.
    # Không query database và không dựng timeline.
    if not is_open:
        return

    match_goals = load_goal_scorers_for_match(
        match_id
    )

    if match_goals.empty:
        st.markdown(
            (
                '<div class="wc-goal-scorers-no-data">'
                'Chưa có dữ liệu cầu thủ ghi bàn cho trận này.'
                '</div>'
            ),
            unsafe_allow_html=True
        )
        return

    timeline = match_goals.copy()

    minute_keys = timeline["minute"].map(
        goal_minute_sort_key
    )

    timeline["_minute_normal"] = (
        minute_keys.map(
            lambda value: value[0]
        )
    )

    timeline["_minute_added"] = (
        minute_keys.map(
            lambda value: value[1]
        )
    )

    # Dùng thứ tự nguồn làm khóa phụ
    # khi có nhiều bàn cùng một phút.
    timeline["_source_order"] = range(
        len(timeline)
    )

    timeline = timeline.sort_values(
        by=[
            "_minute_normal",
            "_minute_added",
            "_source_order"
        ],
        ascending=True,
        kind="mergesort"
    )

    def normalize_team_key(value) -> str:
        """
        Chuẩn hóa tên đội để dùng khi team_side
        bị thiếu trong database.
        """
        if value is None or pd.isna(value):
            return ""

        normalized = str(
            value
        ).casefold()

        normalized = re.sub(
            r"\b(?:fc|afc)\b",
            " ",
            normalized
        )

        normalized = re.sub(
            r"[^a-z0-9]+",
            " ",
            normalized
        )

        return re.sub(
            r"\s+",
            " ",
            normalized
        ).strip()

    home_team_keys = {
        normalize_team_key(home_name),
        normalize_team_key(
            get_mobile_team_display_name(
                home_name
            )
        )
    }

    away_team_keys = {
        normalize_team_key(away_name),
        normalize_team_key(
            get_mobile_team_display_name(
                away_name
            )
        )
    }

    home_team_keys.discard("")
    away_team_keys.discard("")

    timeline_rows = []

    for _, goal_row in timeline.iterrows():
        raw_team_side = goal_row.get(
            "team_side"
        )

        team_side = (
            ""
            if raw_team_side is None
            or pd.isna(raw_team_side)
            else str(
                raw_team_side
            ).strip().casefold()
        )

        # Nếu team_side bị thiếu, xác định lại
        # bằng tên đội trong dữ liệu bàn thắng.
        if team_side not in {
            "home",
            "away"
        }:
            goal_team_key = (
                normalize_team_key(
                    goal_row.get(
                        "team_name"
                    )
                )
            )

            if goal_team_key in home_team_keys:
                team_side = "home"

            elif goal_team_key in away_team_keys:
                team_side = "away"

        # Không đoán bừa nếu không xác định được đội.
        if team_side not in {
            "home",
            "away"
        }:
            continue

        safe_goal_text = html.escape(
            format_goal_text(goal_row),
            quote=False
        )

        goal_item_html = (
            '<div class="wc-goal-scorer-item">'
            f'{safe_goal_text}'
            '</div>'
        )

        home_item_html = (
            goal_item_html
            if team_side == "home"
            else ""
        )

        away_item_html = (
            goal_item_html
            if team_side == "away"
            else ""
        )

        timeline_rows.append(
            (
                '<div class="wc-goal-scorer-row">'

                '<div class="wc-goal-scorer-slot is-home">'
                f'{home_item_html}'
                '</div>'

                '<div class="wc-goal-scorer-axis" '
                'aria-hidden="true"></div>'

                '<div class="wc-goal-scorer-slot is-away">'
                f'{away_item_html}'
                '</div>'

                '</div>'
            )
        )

    if not timeline_rows:
        st.markdown(
            (
                '<div class="wc-goal-scorers-no-data">'
                'Chưa xác định được đội của các cầu thủ ghi bàn.'
                '</div>'
            ),
            unsafe_allow_html=True
        )
        return

    safe_home_name = html.escape(
        str(
            get_mobile_team_display_name(
                home_name
            )
        ),
        quote=True
    )

    safe_away_name = html.escape(
        str(
            get_mobile_team_display_name(
                away_name
            )
        ),
        quote=True
    )

    scorers_html = (
        '<div class="wc-goal-scorers-grid" '
        'role="group" '
        f'aria-label="Cầu thủ ghi bàn của '
        f'{safe_home_name} và {safe_away_name}">'
        f'{"".join(timeline_rows)}'
        '</div>'
    )
    
    if hasattr(st, "html"):
        st.html(scorers_html)
    else:
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
    _load_predictions_cached.clear()
    _load_user_predictions_cached.clear()

    try:
        revision_store = (
            get_prediction_cache_revision_store()
        )

        with revision_store["lock"]:
            revision_store[
                "all_predictions"
            ].clear()
            revision_store[
                "all_user_predictions"
            ].clear()
            revision_store[
                "single_user_predictions"
            ].clear()

    except Exception:
        pass

    try:
        _load_user_star_usage_counts_cached.clear()
    except (NameError, AttributeError):
        pass

    try:
        build_leaderboard_df.clear()
    except NameError:
        pass

    try:
        _load_goal_scorers_for_match_cached.clear()
    except NameError:
        pass

    try:
        load_epl_top_scorers.clear()
    except (NameError, AttributeError):
        pass

def clear_prediction_write_cache(
    user_id: int,
    season_slug: str
):
    """
    Chỉ xóa các cache bị ảnh hưởng trực tiếp khi dự đoán thay đổi.
    Không xóa cache cá nhân của user khác hoặc cache mùa khác.
    """
    bump_prediction_cache_revisions(
        season_slug=season_slug,
        user_id=int(user_id),
        all_users=False
    )

    try:
        build_leaderboard_df.clear()
    except (NameError, AttributeError):
        pass


def clear_scoring_cache(
    season_slug: str,
    user_id: int | None = None
):
    """
    Chấm điểm chỉ đổi ba cột điểm trong predictions của đúng phạm vi.
    Giữ cache trạng thái sao vì star_type/kickoff không thay đổi.
    """
    bump_prediction_cache_revisions(
        season_slug=season_slug,
        user_id=user_id,
        all_users=user_id is None
    )

    try:
        build_leaderboard_df.clear()
    except (NameError, AttributeError):
        pass


def _lock_user_for_prediction_write(conn, user_id: int):
    """
    Khóa tuần tự các thao tác ghi prediction của cùng một user.
    Các user khác vẫn thao tác độc lập.
    """
    user_row = conn.execute(
        text(
            """
            SELECT user_id
            FROM users
            WHERE user_id = :user_id
            FOR UPDATE
            """
        ),
        {"user_id": int(user_id)}
    ).mappings().fetchone()

    if user_row is None:
        raise ValueError("Không tìm thấy người dùng.")

def _get_match_in_transaction(conn, match_id: int):
    row = conn.execute(
        text(
            """
            SELECT *
            FROM matches
            WHERE match_id = :match_id
            """
        ),
        {"match_id": int(match_id)}
    ).mappings().fetchone()

    if row is None:
        return None

    return dict(row)

def _get_prediction_for_update(conn, user_id: int, match_id: int):
    row = conn.execute(
        text(
            """
            SELECT *
            FROM predictions
            WHERE user_id = :user_id
              AND match_id = :match_id
            FOR UPDATE
            """
        ),
        {
            "user_id": int(user_id),
            "match_id": int(match_id)
        }
    ).mappings().fetchone()

    if row is None:
        return None

    return dict(row)

def _get_user_star_usage_in_transaction(
    conn,
    user_id: int,
    exclude_match_id: int | None = None,
    season_slug: str | None = None
) -> dict:
    """
    Đọc quota sao bằng chính transaction đang lưu prediction.
    Nhờ đó kết quả validate không bị lệch giữa lúc kiểm tra và lúc ghi.
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

    season_slug = season_slug or get_selected_season_slug()

    query += " AND m.season_slug = :season_slug"

    params = {
        "user_id": int(user_id),
        "season_slug": season_slug
    }

    if exclude_match_id is not None:
        query += " AND p.match_id <> :exclude_match_id"
        params["exclude_match_id"] = int(exclude_match_id)

    rows = conn.execute(
        text(query),
        params
    ).mappings().all()

    hope_locked_used = 0
    super_locked_used = 0
    hope_reserved_used = 0
    super_reserved_used = 0

    for row in rows:
        row_dict = dict(row)
        row_star_type = normalize_star_type(row_dict.get("star_type"))

        is_locked = is_match_locked_for_star(
            row_dict.get("kickoff_time_utc"),
            row_dict.get("is_finished")
        )

        is_reserved = is_match_open_for_star_transfer(
            row_dict.get("kickoff_time_utc"),
            row_dict.get("is_finished")
        )

        if row_star_type == STAR_TYPE_HOPE:
            if is_locked:
                hope_locked_used += 1
            elif is_reserved:
                hope_reserved_used += 1

        elif row_star_type == STAR_TYPE_SUPER:
            if is_locked:
                super_locked_used += 1
            elif is_reserved:
                super_reserved_used += 1

    reward_row = conn.execute(
        text(
            """
            SELECT
                COALESCE(
                    SUM(
                        CASE
                            WHEN reward_type = 'hope' THEN amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS hope_bonus,
                COALESCE(
                    SUM(
                        CASE
                            WHEN reward_type = 'super' THEN amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS super_bonus
            FROM daily_checkin_rewards
            WHERE user_id = :user_id
            """
        ),
        {"user_id": int(user_id)}
    ).mappings().fetchone()

    hope_bonus = int((reward_row or {}).get("hope_bonus") or 0)
    super_bonus = int((reward_row or {}).get("super_bonus") or 0)

    hope_total = int(HOPE_STARS_PER_USER) + hope_bonus
    super_total = int(SUPER_STARS_PER_USER) + super_bonus

    hope_left = max(0, hope_total - hope_locked_used)
    super_left = max(0, super_total - super_locked_used)

    hope_free_left = max(0, hope_left - hope_reserved_used)
    super_free_left = max(0, super_left - super_reserved_used)

    return {
        "hope_used": hope_locked_used,
        "super_used": super_locked_used,
        "hope_locked_used": hope_locked_used,
        "super_locked_used": super_locked_used,
        "hope_reserved_used": hope_reserved_used,
        "super_reserved_used": super_reserved_used,
        "hope_total": hope_total,
        "super_total": super_total,
        "hope_bonus": hope_bonus,
        "super_bonus": super_bonus,
        "hope_left": hope_left,
        "super_left": super_left,
        "hope_free_left": hope_free_left,
        "super_free_left": super_free_left
    }

def _normalize_prediction_for_match(
    match: dict,
    predicted_home_score: int,
    predicted_away_score: int,
    predicted_winner_team_id: int | None
) -> int | None:
    """
    Chuẩn hóa và validate dữ liệu dự đoán theo đúng luật hiện tại.
    """
    predicted_home_score = int(predicted_home_score)
    predicted_away_score = int(predicted_away_score)

    if not 0 <= predicted_home_score <= 20:
        raise ValueError("Tỉ số đội nhà không hợp lệ.")

    if not 0 <= predicted_away_score <= 20:
        raise ValueError("Tỉ số đội khách không hợp lệ.")

    if not can_edit_prediction(
        match.get("kickoff_time_utc"),
        is_finished=match.get("is_finished")
    ):
        raise ValueError(
            "Trận đấu đã có kết quả hoặc đã khóa dự đoán."
        )

    if predicted_winner_team_id is not None:
        predicted_winner_team_id = int(predicted_winner_team_id)

    is_knockout = to_bool(match.get("is_knockout"))

    if not is_knockout:
        # Trận league không dùng trường đội thắng chung cuộc.
        # Luôn chuẩn hóa về NULL để dữ liệu cũ/tampered input không lọt vào.
        return None

    home_team_id = to_optional_int(match.get("home_team_id"))
    away_team_id = to_optional_int(match.get("away_team_id"))

    if (
        home_team_id is None
        or away_team_id is None
        or home_team_id == away_team_id
    ):
        raise ValueError(
            "Thông tin hai đội của trận knockout chưa hợp lệ."
        )

    if predicted_home_score > predicted_away_score:
        return home_team_id

    if predicted_away_score > predicted_home_score:
        return away_team_id

    if predicted_winner_team_id not in [home_team_id, away_team_id]:
        raise ValueError(
            "Trận knockout hòa. Bạn cần chọn đội thắng chung cuộc."
        )

    return predicted_winner_team_id

def is_prediction_unchanged(
    existing: dict | None,
    predicted_home_score: int,
    predicted_away_score: int,
    predicted_winner_team_id: int | None,
    star_type: str
) -> bool:
    """
    Trả về True khi dữ liệu mới giống hoàn toàn dữ liệu đã lưu.
    """
    if existing is None:
        return False

    return (
        to_optional_int(existing.get("predicted_home_score"))
        == int(predicted_home_score)
        and
        to_optional_int(existing.get("predicted_away_score"))
        == int(predicted_away_score)
        and
        to_optional_int(existing.get("predicted_winner_team_id"))
        == to_optional_int(predicted_winner_team_id)
        and
        normalize_star_type(existing.get("star_type"))
        == normalize_star_type(star_type)
    )

def _write_prediction_in_transaction(
    conn,
    existing: dict | None,
    user_id: int,
    match_id: int,
    predicted_home_score: int,
    predicted_away_score: int,
    predicted_winner_team_id: int | None,
    star_type: str,
    now_text: str
) -> dict:
    """
    INSERT hoặc UPDATE prediction trong transaction đang mở.
    Không tự commit và không clear cache.
    """
    if existing is None:
        inserted_row = conn.execute(
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
                RETURNING prediction_id
                """
            ),
            {
                "user_id": int(user_id),
                "match_id": int(match_id),
                "predicted_home_score": int(predicted_home_score),
                "predicted_away_score": int(predicted_away_score),
                "predicted_winner_team_id": predicted_winner_team_id,
                "star_type": normalize_star_type(star_type),
                "submitted_at": now_text,
                "updated_at": now_text
            }
        ).mappings().fetchone()

        return {
            "status": "created",
            "prediction_id": int(inserted_row["prediction_id"])
        }

    prediction_id = int(existing["prediction_id"])

    if is_prediction_unchanged(
        existing=existing,
        predicted_home_score=predicted_home_score,
        predicted_away_score=predicted_away_score,
        predicted_winner_team_id=predicted_winner_team_id,
        star_type=star_type
    ):
        return {
            "status": "unchanged",
            "prediction_id": prediction_id
        }

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
            "old_home_score": existing.get("predicted_home_score"),
            "old_away_score": existing.get("predicted_away_score"),
            "old_winner_team_id": existing.get("predicted_winner_team_id"),
            "new_home_score": int(predicted_home_score),
            "new_away_score": int(predicted_away_score),
            "new_winner_team_id": predicted_winner_team_id,
            "changed_at": now_text
        }
    )

    update_result = conn.execute(
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
              AND user_id = :user_id
              AND match_id = :match_id
            """
        ),
        {
            "predicted_home_score": int(predicted_home_score),
            "predicted_away_score": int(predicted_away_score),
            "predicted_winner_team_id": predicted_winner_team_id,
            "star_type": normalize_star_type(star_type),
            "updated_at": now_text,
            "prediction_id": prediction_id,
            "user_id": int(user_id),
            "match_id": int(match_id)
        }
    )

    if update_result.rowcount != 1:
        raise ValueError(
            "Dự đoán đã thay đổi ở một phiên khác. Vui lòng thao tác lại."
        )

    return {
        "status": "updated",
        "prediction_id": prediction_id
    }


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


def get_user_star_usage_from_db(
    user_id: int,
    exclude_match_id: int | None = None,
    season_slug: str | None = None
) -> dict:
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

    season_slug = season_slug or get_selected_season_slug()

    query += " AND m.season_slug = :season_slug"

    params = {
        "user_id": user_id,
        "season_slug": season_slug
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
        normalized_stars = (
            df["star_type"]
            .fillna(STAR_TYPE_NONE)
            .astype(str)
            .str.strip()
            .str.lower()
        )
        df["star_type"] = normalized_stars.where(
            normalized_stars.isin(STAR_CONFIG),
            STAR_TYPE_NONE
        )

        kickoff_time = pd.to_datetime(
            df["kickoff_time_utc"],
            utc=True,
            errors="coerce"
        )
        is_finished = df["is_finished"].map(to_bool)
        now_utc = pd.Timestamp.now(tz="UTC")

        df["is_star_locked"] = (
            is_finished
            | kickoff_time.isna()
            | kickoff_time.le(now_utc)
        )
        df["is_star_reserved"] = (
            ~is_finished
            & kickoff_time.notna()
            & kickoff_time.gt(now_utc)
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

    return build_star_usage_result(
        user_id=user_id,
        hope_locked_used=hope_locked_used,
        super_locked_used=super_locked_used,
        hope_reserved_used=hope_reserved_used,
        super_reserved_used=super_reserved_used
    )

def update_user_avatar(user_id: int, avatar_key: str):
    """
    Cập nhật avatar cho user hiện tại.

    Chỉ lưu tên file avatar vào database.
    Dùng RETURNING để xác nhận đúng user đã được cập nhật trước khi đổi state
    trên giao diện. Không retry thao tác ghi để tránh một lần bấm bị ghi lặp
    khi trạng thái commit của kết nối không xác định.
    """
    avatar_keys = list(load_avatar_catalog())
    avatar_key = normalize_avatar_key(
        avatar_key,
        avatar_keys=avatar_keys
    )

    if not avatar_key:
        raise ValueError("Chưa có avatar hợp lệ để chọn.")

    with get_engine().begin() as conn:
        updated_row = conn.execute(
            text(
                """
                UPDATE users
                SET avatar_key = :avatar_key
                WHERE user_id = :user_id
                RETURNING avatar_key
                """
            ),
            {
                "avatar_key": avatar_key,
                "user_id": int(user_id)
            }
        ).mappings().fetchone()

    if updated_row is None:
        raise ValueError(
            "Không tìm thấy tài khoản để cập nhật avatar."
        )

    saved_avatar_key = normalize_avatar_key(
        updated_row.get("avatar_key"),
        avatar_keys=avatar_keys
    )

    if saved_avatar_key != avatar_key:
        raise RuntimeError(
            "Database chưa xác nhận đúng avatar vừa chọn."
        )

    try:
        load_users.clear()
    except Exception:
        pass

    try:
        build_leaderboard_df.clear()
    except Exception:
        pass

    return saved_avatar_key

def get_user_prediction(user_id: int, match_id: int):
    """
    Dùng cho UI.
    Lấy từ load_user_predictions() đã cache để tránh tải dự đoán của user khác
    và tránh query database lặp lại cho từng card.
    """
    predictions = load_user_predictions(
        int(user_id),
        get_selected_season_slug()
    )

    if predictions.empty:
        return None

    filtered = predictions[
        predictions["match_id"].astype(int) == int(match_id)
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

    prediction_records = user_predictions.to_dict(
        orient="records"
    )

    return {
        int(prediction["match_id"]): prediction
        for prediction in prediction_records
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
    from google import genai

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

    actual_home = to_optional_int(
        match_row.get("home_score_for_prediction")
    )
    actual_away = to_optional_int(
        match_row.get("away_score_for_prediction")
    )

    round_name = match_row.get("round_name", "")
    date_text = match_row.get(
        "kickoff_date_display_vietnam",
        match_row.get("kickoff_date_vietnam", "")
    )
    time_text = match_row.get("kickoff_time_vietnam", "")
    venue = match_row.get("venue", "")
    city = match_row.get("city", "")

    app_context_parts = [
        f"Trận đấu trong app: {match_name}",
        f"Giải đấu: Premier League",
        f"Vòng đấu: {round_name}",
        f"Thời gian theo Việt Nam: {date_text} {time_text}",
    ]

    if actual_home is not None and actual_away is not None:
        app_context_parts.append(
            f"Tỉ số trong app: {actual_home} - {actual_away}"
        )

    if (
        venue is not None
        and not pd.isna(venue)
        and str(venue).strip()
    ):
        app_context_parts.append(
            f"Sân vận động: {venue}"
        )

    if (
        city is not None
        and not pd.isna(city)
        and str(city).strip()
    ):
        app_context_parts.append(
            f"Thành phố: {city}"
        )

    app_context = "\n".join(app_context_parts)

    return (
        "Bạn là chuyên gia cập nhật tin tức và diễn biến Premier League. "
        "Trước khi trả lời, hãy sử dụng Google Search để tìm và đối chiếu "
        "thông tin đúng trận đấu, đúng vòng và đúng thời điểm được cung cấp. "
        f"Hãy viết phần tóm tắt trận {match_name}, giúp người xem hiểu thêm "
        "diễn biến chính, thế trận, bước ngoặt và những yếu tố đáng chú ý, "
        "thay vì chỉ lặp lại tỉ số hoặc danh sách cầu thủ ghi bàn. "
        "Chỉ trả lời bằng tiếng Việt, không quá 80 từ. "
        "Chỉ dùng văn bản thuần, không HTML, CSS, Markdown, bảng, bullet point, "
        "code block, tiêu đề, nhãn AI hoặc phần nguồn.\n\n"
        "Thông tin từ app để xác định chính xác trận đấu:\n"
        f"{app_context}\n\n"
        "Nếu có nhiều kết quả trùng tên, chỉ dùng dữ liệu của trận Premier League "
        "đúng vòng đấu, thời gian, sân vận động và tỉ số ở trên."
    )


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
    from google.genai import types

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

def build_ai_match_suggestion_prompt(match_row: dict) -> str:
    home_name = match_row.get("home_team_name")
    away_name = match_row.get("away_team_name")
    match_name = f"{home_name} vs {away_name}"

    round_name = match_row.get("round_name", "")
    date_text = match_row.get(
        "kickoff_date_display_vietnam",
        match_row.get("kickoff_date_vietnam", "")
    )
    time_text = match_row.get("kickoff_time_vietnam", "")
    venue = match_row.get("venue", "")
    city = match_row.get("city", "")

    app_context_parts = [
        f"Trận đấu trong app: {match_name}",
        "Giải đấu: Premier League",
        f"Vòng đấu: {round_name}",
        f"Thời gian theo Việt Nam: {date_text} {time_text}",
    ]

    if (
        venue is not None
        and not pd.isna(venue)
        and str(venue).strip()
    ):
        app_context_parts.append(
            f"Sân vận động: {venue}"
        )

    if (
        city is not None
        and not pd.isna(city)
        and str(city).strip()
    ):
        app_context_parts.append(
            f"Thành phố: {city}"
        )

    app_context = "\n".join(app_context_parts)

    return (
        "Bạn là chuyên gia phân tích Premier League và có khả năng cập nhật "
        "thông tin mới nhất bằng Google Search. Hãy phân tích trận đấu được "
        "cung cấp, xác định đội có lợi thế hơn và dự đoán kịch bản kết quả "
        "có khả năng xảy ra nhất.\n\n"

        "Trước khi trả lời, bắt buộc tìm kiếm, kiểm chứng và đối chiếu nhiều "
        "nguồn đáng tin cậy. Ưu tiên trang chính thức của Premier League, "
        "thông báo của câu lạc bộ, huấn luyện viên, hãng tin thể thao uy tín "
        "và nền tảng thống kê chuyên nghiệp. Không tự tạo dữ liệu, chấn thương, "
        "đội hình hoặc thống kê chưa được xác nhận.\n\n"

        "Hãy kết hợp phong độ 5 đến 10 trận gần nhất, hiệu suất ghi bàn và "
        "phòng ngự, xG nếu có nguồn đáng tin cậy, tình hình lực lượng, treo giò, "
        "đội hình dự kiến, chiều sâu đội hình, lịch thi đấu, khả năng xoay vòng, "
        "chiến thuật, bóng cố định, lợi thế sân nhà và bối cảnh cuộc đua trên "
        "bảng xếp hạng.\n\n"

        "Bắt buộc kiểm tra đối đầu trực tiếp theo hai phạm vi: toàn bộ lịch sử "
        "có dữ liệu đáng tin cậy và riêng 3 đến 5 lần gặp gần nhất. Cần nêu số "
        "trận mỗi đội thắng, số trận hòa và xu hướng đáng chú ý. Ưu tiên dữ liệu "
        "gần đây khi lực lượng, huấn luyện viên và bối cảnh vẫn còn phù hợp.\n\n"

        "Không đưa ra dự đoán chỉ dựa trên một yếu tố. Phải giải thích ngắn gọn "
        "vì sao phong độ, lực lượng, chiến thuật, sân đấu và đối đầu dẫn đến "
        "dự đoán cuối cùng. Không khẳng định chắc chắn tuyệt đối.\n\n"

        f"Hãy thực hiện cho trận {match_name} tại Premier League.\n\n"

        "Thông tin từ app để xác định chính xác trận đấu:\n"
        f"{app_context}\n\n"

        "Nếu có nhiều kết quả trùng tên, chỉ sử dụng thông tin của trận "
        "Premier League đúng vòng, thời gian và sân đấu được cung cấp. "
        "Ưu tiên dữ liệu mới nhất trước giờ bóng lăn.\n\n"

        "Yêu cầu đầu ra:\n"
        "- Viết hoàn toàn bằng tiếng Việt và chỉ dùng văn bản thuần.\n"
        "- Tổng độ dài không quá 200 từ, gồm cả dòng dự đoán.\n"
        "- Phân tích thành một đoạn súc tích, mạch lạc.\n"
        "- Nêu riêng đối đầu lịch sử và 3 đến 5 lần gặp gần nhất nếu có dữ liệu.\n"
        "- Sau đoạn phân tích, xuống dòng đúng một lần và viết: Dự đoán: X-Y.\n"
        "- Không dùng HTML, CSS, Markdown, bảng, bullet point hoặc code block "
        "trong câu trả lời cuối cùng.\n"
        "- Không thêm tiêu đề, phần nguồn hoặc mô tả quá trình tìm kiếm."
    )


def get_ai_match_suggestion_from_db(match_id: int):
    return fetch_one(
        """
        SELECT
            match_id,
            suggestion_text,
            model_name,
            created_at,
            updated_at
        FROM match_ai_suggestions
        WHERE match_id = :match_id
        """,
        {
            "match_id": int(match_id)
        }
    )


def save_ai_match_suggestion_to_db(
    match_id: int,
    suggestion_text: str,
    model_name: str
):
    now_text = now_utc_iso()

    execute_sql(
        """
        INSERT INTO match_ai_suggestions (
            match_id,
            suggestion_text,
            model_name,
            created_at,
            updated_at
        )
        VALUES (
            :match_id,
            :suggestion_text,
            :model_name,
            :created_at,
            :updated_at
        )
        ON CONFLICT (match_id)
        DO UPDATE SET
            suggestion_text = EXCLUDED.suggestion_text,
            model_name = EXCLUDED.model_name,
            updated_at = EXCLUDED.updated_at
        """,
        {
            "match_id": int(match_id),
            "suggestion_text": suggestion_text,
            "model_name": model_name,
            "created_at": now_text,
            "updated_at": now_text
        }
    )


def generate_ai_match_suggestion(match_row: dict) -> str:
    from google.genai import types

    client = get_gemini_client()
    prompt = build_ai_match_suggestion_prompt(match_row)

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

    suggestion_text = normalize_ai_summary_text(getattr(response, "text", ""))

    if not suggestion_text:
        raise ValueError("Gemini không trả về nội dung gợi ý hợp lệ.")

    bad_markers = [
        "không tìm thấy thông tin",
        "không có dữ liệu",
        "không thể xác nhận"
    ]

    lowered_suggestion = suggestion_text.lower()

    if any(marker in lowered_suggestion for marker in bad_markers):
        raise ValueError(
            "Gemini chưa tìm được thông tin đủ chắc chắn về trận này. "
            "Gợi ý chưa được lưu để tránh lưu nội dung sai."
        )

    return suggestion_text

# ============================================================
# 7. PREDICTION SAVE + SCORING
# ============================================================
def get_star_transfer_candidates(
    user_id: int,
    target_match_id: int,
    star_type: str,
    season_slug: str | None = None
) -> list[dict]:
    """
    Lấy các trận đang giữ tạm loại sao này và còn mở dự đoán,
    để người chơi có thể chọn chuyển sao sang trận hiện tại.
    """
    star_type = normalize_star_type(star_type)

    if star_type == STAR_TYPE_NONE:
        return []

    season_slug = season_slug or get_selected_season_slug()

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
          AND m.season_slug = :season_slug
        ORDER BY m.kickoff_time_utc
        """,
        {
            "user_id": int(user_id),
            "target_match_id": int(target_match_id),
            "star_type": star_type,
            "season_slug": season_slug
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
) -> dict:
    """
    Lưu hoặc cập nhật dự đoán an toàn trong một transaction.
    """
    user_id = int(user_id)
    match_id = int(match_id)
    predicted_home_score = int(predicted_home_score)
    predicted_away_score = int(predicted_away_score)
    star_type = normalize_star_type(star_type)

    if predicted_winner_team_id is not None:
        predicted_winner_team_id = int(predicted_winner_team_id)

    now_text = now_utc_iso()

    with get_engine().begin() as conn:
        _lock_user_for_prediction_write(
            conn=conn,
            user_id=user_id
        )

        match = _get_match_in_transaction(
            conn=conn,
            match_id=match_id
        )

        if match is None:
            raise ValueError("Không tìm thấy trận đấu.")

        predicted_winner_team_id = _normalize_prediction_for_match(
            match=match,
            predicted_home_score=predicted_home_score,
            predicted_away_score=predicted_away_score,
            predicted_winner_team_id=predicted_winner_team_id
        )

        existing = _get_prediction_for_update(
            conn=conn,
            user_id=user_id,
            match_id=match_id
        )

        if is_prediction_unchanged(
            existing=existing,
            predicted_home_score=predicted_home_score,
            predicted_away_score=predicted_away_score,
            predicted_winner_team_id=predicted_winner_team_id,
            star_type=star_type
        ):
            return {
                "status": "unchanged",
                "prediction_id": int(existing["prediction_id"])
            }

        current_star_type = (
            normalize_star_type(existing.get("star_type"))
            if existing is not None
            else STAR_TYPE_NONE
        )

        if (
            star_type != STAR_TYPE_NONE
            and star_type != current_star_type
        ):
            usage = _get_user_star_usage_in_transaction(
                conn=conn,
                user_id=user_id,
                exclude_match_id=match_id,
                season_slug=match.get("season_slug")
            )

            validate_star_quota(
                user_id=user_id,
                match_id=match_id,
                star_type=star_type,
                usage=usage
            )

        result = _write_prediction_in_transaction(
            conn=conn,
            existing=existing,
            user_id=user_id,
            match_id=match_id,
            predicted_home_score=predicted_home_score,
            predicted_away_score=predicted_away_score,
            predicted_winner_team_id=predicted_winner_team_id,
            star_type=star_type,
            now_text=now_text
        )

    if result.get("status") != "unchanged":
        clear_prediction_write_cache(
            user_id=user_id,
            season_slug=(
                match.get("season_slug")
                or get_selected_season_slug()
            )
        )

    return result

def transfer_star_and_save_prediction(
    user_id: int,
    source_match_id: int,
    target_match_id: int,
    predicted_home_score: int,
    predicted_away_score: int,
    predicted_winner_team_id: int | None,
    star_type: str
) -> dict:
    """
    Chuyển sao và lưu dự đoán đích trong cùng một transaction.
    Nếu bất kỳ bước nào lỗi, toàn bộ thay đổi sẽ rollback.
    """
    user_id = int(user_id)
    source_match_id = int(source_match_id)
    target_match_id = int(target_match_id)
    predicted_home_score = int(predicted_home_score)
    predicted_away_score = int(predicted_away_score)
    star_type = normalize_star_type(star_type)

    if predicted_winner_team_id is not None:
        predicted_winner_team_id = int(predicted_winner_team_id)

    if star_type == STAR_TYPE_NONE:
        raise ValueError("Không có bổ trợ nào cần chuyển.")

    if source_match_id == target_match_id:
        raise ValueError("Trận nguồn và trận đích không thể giống nhau.")

    now_text = now_utc_iso()

    with get_engine().begin() as conn:
        _lock_user_for_prediction_write(
            conn=conn,
            user_id=user_id
        )

        source_match = _get_match_in_transaction(
            conn=conn,
            match_id=source_match_id
        )

        if source_match is None:
            raise ValueError("Không tìm thấy trận đang giữ sao.")

        if not can_edit_prediction(
            source_match.get("kickoff_time_utc"),
            is_finished=source_match.get("is_finished")
        ):
            raise ValueError(
                "Trận đang giữ sao đã khóa, không thể chuyển sao nữa."
            )

        target_match = _get_match_in_transaction(
            conn=conn,
            match_id=target_match_id
        )

        if target_match is None:
            raise ValueError("Không tìm thấy trận đích.")

        if source_match.get("season_slug") != target_match.get("season_slug"):
            raise ValueError(
                "Không thể chuyển bổ trợ giữa hai mùa giải khác nhau."
            )

        predicted_winner_team_id = _normalize_prediction_for_match(
            match=target_match,
            predicted_home_score=predicted_home_score,
            predicted_away_score=predicted_away_score,
            predicted_winner_team_id=predicted_winner_team_id
        )

        source_prediction = _get_prediction_for_update(
            conn=conn,
            user_id=user_id,
            match_id=source_match_id
        )

        if source_prediction is None:
            raise ValueError(
                "Trận được chọn không còn giữ bổ trợ này."
            )

        if (
            normalize_star_type(source_prediction.get("star_type"))
            != star_type
        ):
            raise ValueError(
                "Trận được chọn không còn giữ đúng loại bổ trợ này."
            )

        target_prediction = _get_prediction_for_update(
            conn=conn,
            user_id=user_id,
            match_id=target_match_id
        )

        if is_prediction_unchanged(
            existing=target_prediction,
            predicted_home_score=predicted_home_score,
            predicted_away_score=predicted_away_score,
            predicted_winner_team_id=predicted_winner_team_id,
            star_type=star_type
        ):
            return {
                "status": "unchanged",
                "prediction_id": int(target_prediction["prediction_id"])
            }

        source_update_result = conn.execute(
            text(
                """
                UPDATE predictions
                SET
                    star_type = 'none',
                    base_points = NULL,
                    star_bonus_points = NULL,
                    points = NULL,
                    updated_at = :updated_at
                WHERE prediction_id = :prediction_id
                  AND user_id = :user_id
                  AND match_id = :source_match_id
                  AND star_type = :star_type
                """
            ),
            {
                "updated_at": now_text,
                "prediction_id": int(source_prediction["prediction_id"]),
                "user_id": user_id,
                "source_match_id": source_match_id,
                "star_type": star_type
            }
        )

        if source_update_result.rowcount != 1:
            raise ValueError(
                "Bổ trợ ở trận nguồn đã thay đổi. Vui lòng thao tác lại."
            )

        target_result = _write_prediction_in_transaction(
            conn=conn,
            existing=target_prediction,
            user_id=user_id,
            match_id=target_match_id,
            predicted_home_score=predicted_home_score,
            predicted_away_score=predicted_away_score,
            predicted_winner_team_id=predicted_winner_team_id,
            star_type=star_type,
            now_text=now_text
        )

        result = {
            "status": "transferred",
            "prediction_id": int(target_result["prediction_id"]),
            "target_write_status": target_result["status"]
        }

    clear_prediction_write_cache(
        user_id=user_id,
        season_slug=(
            target_match.get("season_slug")
            or get_selected_season_slug()
        )
    )
    return result

def delete_prediction(user_id: int, match_id: int) -> dict:
    """
    Xóa dự đoán khi trận vẫn còn mở.
    Thao tác đọc, khóa và xóa nằm trong cùng một transaction.
    """
    user_id = int(user_id)
    match_id = int(match_id)

    with get_engine().begin() as conn:
        _lock_user_for_prediction_write(
            conn=conn,
            user_id=user_id
        )

        match = _get_match_in_transaction(
            conn=conn,
            match_id=match_id
        )

        if match is None:
            raise ValueError("Không tìm thấy trận đấu.")

        if not can_edit_prediction(
            match.get("kickoff_time_utc"),
            is_finished=match.get("is_finished")
        ):
            raise ValueError(
                "Trận đấu đã có kết quả hoặc đã khóa, "
                "bạn không thể xóa dự đoán nữa."
            )

        existing = _get_prediction_for_update(
            conn=conn,
            user_id=user_id,
            match_id=match_id
        )

        if existing is None:
            return {
                "status": "not_found",
                "prediction_id": None
            }

        prediction_id = int(existing["prediction_id"])

        conn.execute(
            text(
                """
                DELETE FROM prediction_history
                WHERE prediction_id = :prediction_id
                """
            ),
            {"prediction_id": prediction_id}
        )

        delete_result = conn.execute(
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

        if delete_result.rowcount != 1:
            raise ValueError(
                "Dự đoán đã thay đổi ở một phiên khác. Vui lòng thao tác lại."
            )

    clear_prediction_write_cache(
        user_id=user_id,
        season_slug=(
            match.get("season_slug")
            or get_selected_season_slug()
        )
    )

    return {
        "status": "deleted",
        "prediction_id": prediction_id
    }

@st.cache_data(
    ttl=30,
    max_entries=512,
    show_spinner=False
)
def score_all_predictions(
    season_slug: str | None = None,
    user_id: int | None = None
):
    """
    Chấm điểm lại toàn bộ dự đoán đã có kết quả.

    Tối ưu:
    - Vẫn giữ nguyên logic tính điểm hiện tại.
    - Mặc định vẫn kiểm tra toàn bộ prediction đã có kết quả.
    - Trang cá nhân có thể truyền user_id để chỉ chấm dữ liệu của user đó.
    - Chỉ UPDATE database khi điểm mới khác điểm đang lưu.
    - Nếu không có gì thay đổi thì KHÔNG clear cache, giúp Bảng xếp hạng load nhanh hơn nhiều.
    """
    season_slug = season_slug or get_selected_season_slug()
    matches = load_matches(season_slug)

    if user_id is None:
        predictions = load_predictions(
            season_slug
        )
    else:
        predictions = load_user_predictions(
            int(user_id),
            season_slug
        )

    if predictions.empty:
        return

    match_columns = [
        "match_id",
        "is_finished",
        "home_score_for_prediction",
        "away_score_for_prediction",
        "home_team_name",
        "away_team_name",
        "is_knockout",
        "winner_team_id"
    ]

    df = predictions.merge(
        matches[match_columns],
        on="match_id",
        how="left"
    )

    actual_home = pd.to_numeric(
        df["home_score_for_prediction"],
        errors="coerce"
    )
    actual_away = pd.to_numeric(
        df["away_score_for_prediction"],
        errors="coerce"
    )
    is_finished = df["is_finished"].map(to_bool)

    scored_mask = (
        is_finished
        & actual_home.notna()
        & actual_away.notna()
    )

    if not bool(scored_mask.any()):
        return

    scored = df.loc[scored_mask].copy()
    actual_home = actual_home.loc[scored_mask]
    actual_away = actual_away.loc[scored_mask]

    pred_home = pd.to_numeric(
        scored["predicted_home_score"],
        errors="coerce"
    )
    pred_away = pd.to_numeric(
        scored["predicted_away_score"],
        errors="coerce"
    )
    valid_prediction = pred_home.notna() & pred_away.notna()

    exact_score = (
        valid_prediction
        & pred_home.eq(actual_home)
        & pred_away.eq(actual_away)
    )

    correct_outcome = valid_prediction & (
        (
            pred_home.gt(pred_away)
            & actual_home.gt(actual_away)
        )
        | (
            pred_home.lt(pred_away)
            & actual_home.lt(actual_away)
        )
        | (
            pred_home.eq(pred_away)
            & actual_home.eq(actual_away)
        )
    )

    home_big_six_key = scored[
        "home_team_name"
    ].map(canonicalize_big_six_team_name)

    away_big_six_key = scored[
        "away_team_name"
    ].map(canonicalize_big_six_team_name)

    is_big_match = (
        home_big_six_key.isin(
            BIG_SIX_CANONICAL_TEAMS
        )
        & away_big_six_key.isin(
            BIG_SIX_CANONICAL_TEAMS
        )
        & home_big_six_key.ne(
            away_big_six_key
        )
    )

    new_base_points = pd.Series(
        0,
        index=scored.index,
        dtype="int64"
    )

    # Đúng kết quả nhưng chưa xét đúng hoàn toàn tỉ số.
    new_base_points.loc[
        correct_outcome & ~is_big_match
    ] = NORMAL_MATCH_OUTCOME_POINTS

    new_base_points.loc[
        correct_outcome & is_big_match
    ] = BIG_MATCH_OUTCOME_POINTS

    # Đúng hoàn toàn tỉ số phải ghi đè mức đúng kết quả.
    new_base_points.loc[
        exact_score & ~is_big_match
    ] = NORMAL_MATCH_EXACT_POINTS

    new_base_points.loc[
        exact_score & is_big_match
    ] = BIG_MATCH_EXACT_POINTS

    is_knockout = scored["is_knockout"].map(to_bool)
    predicted_winner = pd.to_numeric(
        scored["predicted_winner_team_id"],
        errors="coerce"
    )
    actual_winner = pd.to_numeric(
        scored["winner_team_id"],
        errors="coerce"
    )
    correct_knockout_winner = (
        is_knockout
        & predicted_winner.notna()
        & actual_winner.notna()
        & predicted_winner.eq(actual_winner)
    )

    new_base_points = (
        new_base_points
        + correct_knockout_winner.astype(int)
    ).astype(int)

    normalized_stars = (
        scored["star_type"]
        .fillna(STAR_TYPE_NONE)
        .astype(str)
        .str.strip()
        .str.lower()
    )
    normalized_stars = normalized_stars.where(
        normalized_stars.isin(STAR_CONFIG),
        STAR_TYPE_NONE
    )
    multipliers = (
        normalized_stars
        .map({
            star_type: int(config["multiplier"])
            for star_type, config in STAR_CONFIG.items()
        })
        .fillna(1)
        .astype(int)
    )

    # Mặc định: dự đoán đúng thì nhân điểm.
    new_star_bonus_points = (
        new_base_points * (multipliers - 1)
    ).astype(int)

    # Sai kết quả thì không nhân 0 mà áp dụng điểm phạt.
    wrong_result = (
        valid_prediction
        & ~correct_outcome
    )

    normal_wrong_penalties = (
        normalized_stars
        .map({
            star_type: int(
                config["wrong_penalty_normal"]
            )
            for star_type, config
            in STAR_CONFIG.items()
        })
        .fillna(0)
        .astype(int)
    )

    big_wrong_penalties = (
        normalized_stars
        .map({
            star_type: int(
                config["wrong_penalty_big"]
            )
            for star_type, config
            in STAR_CONFIG.items()
        })
        .fillna(0)
        .astype(int)
    )

    wrong_penalties = (
        normal_wrong_penalties.where(
            ~is_big_match,
            big_wrong_penalties
        )
    )

    new_star_bonus_points.loc[
        wrong_result
    ] = wrong_penalties.loc[
        wrong_result
    ]

    new_points = (
        new_base_points
        + new_star_bonus_points
    ).astype(int)

    current_base_points = pd.to_numeric(
        scored["base_points"],
        errors="coerce"
    )
    current_star_bonus_points = pd.to_numeric(
        scored["star_bonus_points"],
        errors="coerce"
    )
    current_points = pd.to_numeric(
        scored["points"],
        errors="coerce"
    )

    changed_mask = (
        current_base_points.isna()
        | current_star_bonus_points.isna()
        | current_points.isna()
        | current_base_points.ne(new_base_points)
        | current_star_bonus_points.ne(new_star_bonus_points)
        | current_points.ne(new_points)
    )

    if not bool(changed_mask.any()):
        return

    changed = pd.DataFrame(
        {
            "prediction_id": pd.to_numeric(
                scored.loc[changed_mask, "prediction_id"],
                errors="raise"
            ).astype(int),
            "base_points": new_base_points.loc[changed_mask].astype(int),
            "star_bonus_points": new_star_bonus_points.loc[changed_mask].astype(int),
            "points": new_points.loc[changed_mask].astype(int)
        }
    )

    scored_rows = changed.to_dict("records")

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

    # Chấm điểm chỉ thay đổi bảng predictions.
    # Giữ cache matches/users/goal scorers để tránh query lại không cần thiết.
    clear_scoring_cache(
        season_slug=season_slug,
        user_id=user_id
    )


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

    match_season_slug = (
        str(
            match.get(
                "season_slug",
                get_selected_season_slug()
            )
        ).strip()
        or get_selected_season_slug()
    )

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

    # Bắt buộc bỏ cache kiểm tra chấm điểm sau khi kết quả trận thay đổi.
    try:
        score_all_predictions.clear()
    except AttributeError:
        pass

    score_all_predictions(match_season_slug)


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
                display_name = st.text_input(
                    "Tên hiển thị",
                    max_chars=DISPLAY_NAME_MAX_LENGTH
                )
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
def get_mobile_team_display_name(team_name) -> str:
    """
    Tạo tên CLB ngắn gọn, rõ nghĩa cho toàn bộ giao diện mobile.

    Desktop vẫn sử dụng tên đầy đủ từ database.
    """
    if team_name is None or pd.isna(team_name):
        return "TBD"

    full_name = str(team_name).strip()

    if not full_name:
        return "TBD"

    normalized_name = re.sub(
        r"\s+",
        " ",
        full_name.casefold()
    ).strip()

    if normalized_name in MOBILE_TEAM_NAME_OVERRIDES:
        return MOBILE_TEAM_NAME_OVERRIDES[
            normalized_name
        ]

    # Bỏ hậu tố FC hoặc AFC ở cuối tên.
    short_name = re.sub(
        r"\s+(?:AFC|FC)$",
        "",
        full_name,
        flags=re.IGNORECASE
    ).strip()

    # Bỏ AFC ở đầu tên, ví dụ AFC Bournemouth.
    short_name = re.sub(
        r"^AFC\s+",
        "",
        short_name,
        flags=re.IGNORECASE
    ).strip()

    return short_name or full_name

def render_match_title(
    home_name,
    away_name,
    match_id: int,
    row=None,
    is_big_match: bool = False
):
    """
    Hiển thị tiêu đề trận đấu và băng rôn Premier League.

    Băng rôn có dạng:
    Premier League * Vòng 38
    """
    home_display = (
        "TBD"
        if home_name is None or pd.isna(home_name)
        else str(home_name).strip()
    )

    away_display = (
        "TBD"
        if away_name is None or pd.isna(away_name)
        else str(away_name).strip()
    )

    safe_home = html.escape(
        home_display,
        quote=True
    )

    safe_away = html.escape(
        away_display,
        quote=True
    )

    mobile_home_display = (
        get_mobile_team_display_name(
            home_display
        )
    )
    
    mobile_away_display = (
        get_mobile_team_display_name(
            away_display
        )
    )
    
    safe_mobile_home = html.escape(
        mobile_home_display,
        quote=True
    )
    
    safe_mobile_away = html.escape(
        mobile_away_display,
        quote=True
    )

    # Lấy vòng đấu từ chính row của trận.
    round_value = (
        row.get("round_name")
        if row is not None
        else ""
    )

    round_text = (
        ""
        if (
            round_value is None
            or pd.isna(round_value)
        )
        else str(round_value).strip()
    )

    # Chuẩn hóa cả hai dạng:
    # "Vòng 38" và "Matchday 38"
    # thành "Vòng 38".
    round_number_match = re.search(
        r"\d+",
        round_text
    )

    if round_number_match:
        round_text = (
            f"Vòng {round_number_match.group(0)}"
        )

    safe_round = html.escape(
        round_text,
        quote=True
    )

    ribbon_class_name = (
        "epl-premier-league-ribbon "
        "epl-big-match-ribbon"
        if is_big_match
        else "epl-premier-league-ribbon"
    )

    big_match_prefix_html = ""

    if is_big_match:
        big_match_prefix_html = (
            '<span class="epl-big-match-label">'
            'Big Match'
            '</span>'

            '<span class="epl-premier-league-ribbon-separator">'
            '&bull;'
            '</span>'
        )

    if safe_round:
        ribbon_html = (
            f'<div class="{ribbon_class_name}">'

            f'{big_match_prefix_html}'

            '<span class="epl-premier-league-ribbon-text">'
            'Premier League'
            '</span>'

            '<span class="epl-premier-league-ribbon-separator">'
            '&bull;'
            '</span>'

            '<span class="epl-premier-league-ribbon-round">'
            f'{safe_round}'
            '</span>'

            '</div>'
        )

    else:
        ribbon_html = (
            f'<div class="{ribbon_class_name}">'

            f'{big_match_prefix_html}'

            '<span class="epl-premier-league-ribbon-text">'
            'Premier League'
            '</span>'

            '</div>'
        )

    # Desktop
    with stylable_container(
        key=f"match_title_desktop_{match_id}",
        css_styles="""
        {
            display: block;
        }
        """
    ):
        st.subheader(
            f"{home_display} vs {away_display}"
        )
    
        st.markdown(
            ribbon_html,
            unsafe_allow_html=True
        )

    # Mobile
    mobile_title_html = (
        f'<div '
        f'class="wc-match-title-mobile" '
        f'aria-label="{safe_home} vs {safe_away}">'
    
        f'<div '
        f'class="wc-match-team wc-match-team-home" '
        f'title="{safe_home}">'
        f'{safe_mobile_home}'
        f'</div>'
    
        f'<div class="wc-match-vs">'
        f'vs'
        f'</div>'
    
        f'<div '
        f'class="wc-match-team wc-match-team-away" '
        f'title="{safe_away}">'
        f'{safe_mobile_away}'
        f'</div>'
    
        f'{ribbon_html}'
    
        f'</div>'
    )

    if hasattr(st, "html"):
        st.html(
            mobile_title_html
        )
    else:
        st.markdown(
            mobile_title_html,
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

        if st.button(
            "Đóng",
            use_container_width=True,
            key="close_empty_star_transfer_dialog"
        ):
            st.rerun()

        return

    star_type = normalize_star_type(pending.get("star_type"))
    star_label = format_star_short(star_type)
    target_label = str(
        pending.get("target_label", "trận hiện tại")
    )

    candidates = pending.get("candidates", [])

    if not candidates:
        st.session_state.pop("pending_star_transfer", None)
        st.warning("Không còn trận hợp lệ để chuyển bổ trợ.")

        if st.button(
            "Đóng",
            use_container_width=True,
            key="close_invalid_star_transfer_dialog"
        ):
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

    if not confirm_transfer:
        return

    selected_candidate = candidate_options[selected_source_label]
    target_match_id = int(pending["target_match_id"])

    try:
        transfer_star_and_save_prediction(
            user_id=int(user_id),
            source_match_id=int(selected_candidate["match_id"]),
            target_match_id=target_match_id,
            predicted_home_score=int(
                pending["predicted_home_score"]
            ),
            predicted_away_score=int(
                pending["predicted_away_score"]
            ),
            predicted_winner_team_id=pending.get(
                "predicted_winner_team_id"
            ),
            star_type=star_type
        )

        st.session_state.pop("pending_star_transfer", None)
        st.session_state["star_transfer_success_message"] = (
            "Đã chuyển bổ trợ và lưu dự đoán."
        )

        st.rerun()

    except ValueError as e:
        st.error(str(e))

    except Exception:
        st.error(
            "Không thể chuyển bổ trợ vào lúc này. "
            "Dữ liệu cũ của bạn vẫn được giữ nguyên."
        )


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

@st.dialog("AI phân tích")
def render_ai_match_suggestion_dialog(match_id: int):
    match_id = int(match_id)

    match = get_match_by_id(match_id)

    if match is None:
        st.error("Không tìm thấy trận đấu.")
        if st.button(
            "Đóng",
            use_container_width=True,
            key=f"close_ai_suggestion_missing_{match_id}"
        ):
            st.session_state.pop("ai_suggestion_match_id", None)
            st.rerun()
        return

    is_finished = to_bool(
        match.get("is_finished")
    )
    
    is_editable = can_edit_prediction(
        match.get("kickoff_time_utc")
    )
    
    is_ai_suggestion_available = (
        can_use_ai_match_suggestion(
            match.get("kickoff_time_utc"),
            is_finished=is_finished
        )
    )
    
    if (
        is_finished
        or not is_editable
        or not is_ai_suggestion_available
    ):
        st.warning(
            "AI phân tích chỉ khả dụng "
            "trong vòng 3 ngày trước giờ bóng lăn."
        )
    
        if st.button(
            "Đóng",
            use_container_width=True,
            key=(
                f"close_ai_suggestion_"
                f"unavailable_{match_id}"
            )
        ):
            st.session_state.pop(
                "ai_suggestion_match_id",
                None
            )
    
            st.rerun()
    
        return
        if st.button(
            "Đóng",
            use_container_width=True,
            key=f"close_ai_suggestion_unavailable_{match_id}"
        ):
            st.session_state.pop("ai_suggestion_match_id", None)
            st.rerun()
        return

    home_name = match.get("home_team_name")
    away_name = match.get("away_team_name")

    round_name = match.get("round_name", "")
    date_text = match.get(
        "kickoff_date_display_vietnam",
        match.get("kickoff_date_vietnam", "")
    )
    time_text = match.get("kickoff_time_vietnam", "")

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
            {html.escape(str(round_name))} | {html.escape(str(date_text))} lúc {html.escape(str(time_text))}
        </div>
        """,
        unsafe_allow_html=True
    )

    try:
        existing_suggestion = get_ai_match_suggestion_from_db(match_id)
    except Exception as e:
        st.error(
            "Chưa đọc được bảng match_ai_suggestions. Hãy kiểm tra xem bạn đã tạo bảng trong Supabase chưa."
        )
        st.caption(str(e))
        return

    if existing_suggestion is not None:
        suggestion_text = existing_suggestion.get("suggestion_text", "")
    else:
        with st.spinner("AI đang tìm kiếm và tổng hợp nhận định trước trận..."):
            try:
                suggestion_text = generate_ai_match_suggestion(match)

                save_ai_match_suggestion_to_db(
                    match_id=match_id,
                    suggestion_text=suggestion_text,
                    model_name=GEMINI_MODEL_NAME
                )

            except Exception as e:
                st.error("Không tạo được AI phân tích cho trận này.")
                st.caption(str(e))
                return

    safe_suggestion = html.escape(
        str(suggestion_text)
    ).replace("\n", "<br>")
    
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
            {safe_suggestion}
        </div>
        """,
        unsafe_allow_html=True
    )
    
    if st.button(
        "Đóng",
        use_container_width=True,
        key=f"close_ai_suggestion_{match_id}"
    ):
        st.session_state.pop("ai_suggestion_match_id", None)
        st.rerun()
    
    st.markdown(
        """
        <div style="
            margin-top:7px;
            margin-bottom:0;
            color:#94A3B8;
            font-size:11.5px;
            line-height:1.4;
            font-style:italic;
            font-weight:400;
            text-align:center;
        ">
            Phân tích từ AI mang tính chất tham khảo
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


def render_match_venue_footer(
    row,
    match_id: int
):
    venue = row.get("venue")
    city = row.get("city")

    venue_text = (
        ""
        if venue is None or pd.isna(venue)
        else str(venue).strip()
    )

    city_text = (
        ""
        if city is None or pd.isna(city)
        else str(city).strip()
    )

    if not venue_text:
        return

    location_text = venue_text

    if city_text:
        location_text = (
            f"{venue_text}, {city_text}"
        )

    safe_venue = html.escape(
        location_text,
        quote=True
    )

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

PREDICTION_FEEDBACK_POPUP_KEY = "prediction_feedback_popup_message"


def set_prediction_feedback_message(
    match_id: int,
    message: str,
    tone: str = "success"
):
    """
    Lưu message feedback sau khi lưu/cập nhật dự đoán.

    match_id vẫn giữ trong signature để không phải sửa các chỗ đang gọi hàm.
    Message sẽ được render dạng popup global ngoài card trận đấu.
    """
    st.session_state[PREDICTION_FEEDBACK_POPUP_KEY] = {
        "match_id": int(match_id),
        "message": str(message),
        "tone": str(tone),
        "created_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000)
    }


def render_prediction_feedback_popup():
    """
    Hiển thị thông báo sau khi lưu/cập nhật/xóa dự đoán.

    Nguyên tắc:
    - Render HTML trực tiếp bằng st.html(), không qua Markdown parser.
    - Luôn tạo đúng một phần tử Streamlit ở mỗi lượt render.
    - Khi không có thông báo, render placeholder ẩn.
    - Không ảnh hưởng logic lưu, cập nhật hoặc xóa dự đoán.
    """
    feedback = st.session_state.pop(
        PREDICTION_FEEDBACK_POPUP_KEY,
        None
    )

    # Placeholder giúp giữ ổn định cây render của Streamlit,
    # tránh stale/ghost card sau khi popup biến mất.
    popup_html = """
    <div
        class="wc-prediction-feedback-stable-slot"
        aria-hidden="true"
        style="
            display:none;
            width:0;
            height:0;
            min-height:0;
            margin:0;
            padding:0;
            overflow:hidden;
        "
    ></div>
    """

    if feedback:
        if isinstance(feedback, dict):
            message = str(
                feedback.get("message", "")
            ).strip()

            tone = str(
                feedback.get("tone", "success")
            ).strip().lower()

            created_at_ms = int(
                feedback.get(
                    "created_at_ms",
                    int(
                        datetime.now(
                            timezone.utc
                        ).timestamp() * 1000
                    )
                )
            )

        else:
            message = str(feedback).strip()
            tone = "success"

            created_at_ms = int(
                datetime.now(
                    timezone.utc
                ).timestamp() * 1000
            )

        if message:
            normalized_message = " ".join(
                message.lower().split()
            )

            popup_copy_map = {
                (
                    "đã lưu dự đoán. bạn vẫn có thể cập nhật "
                    "dự đoán cho đến trước giờ bóng lăn."
                ): {
                    "title": "Đã lưu dự đoán",
                    "detail": (
                        "Bạn có thể chỉnh sửa trước giờ bóng lăn."
                    ),
                    "tone": "success"
                },

                "đã cập nhật dự đoán.": {
                    "title": "Đã cập nhật dự đoán",
                    "detail": (
                        "Những lựa chọn mới đã được ghi nhận."
                    ),
                    "tone": "success"
                },

                "dự đoán không có thay đổi.": {
                    "title": "Không có thay đổi",
                    "detail": (
                        "Dự đoán hiện tại vẫn được giữ nguyên."
                    ),
                    "tone": "info"
                },

                "đã xóa dự đoán.": {
                    "title": "Đã xóa dự đoán",
                    "detail": (
                        "Dự đoán của trận đấu đã được gỡ bỏ."
                    ),
                    "tone": "success"
                },

                "dự đoán này đã được xóa trước đó.": {
                    "title": "Dự đoán đã được xóa",
                    "detail": (
                        "Không có dữ liệu nào cần xóa thêm."
                    ),
                    "tone": "info"
                },

                "đã chuyển bổ trợ và lưu dự đoán.": {
                    "title": "Đã lưu dự đoán",
                    "detail": (
                        "Bổ trợ đã được chuyển sang trận đấu này."
                    ),
                    "tone": "success"
                }
            }

            mapped_copy = popup_copy_map.get(
                normalized_message
            )

            if mapped_copy:
                popup_title = mapped_copy["title"]
                popup_detail = mapped_copy["detail"]
                tone = mapped_copy["tone"]

            else:
                # Các thông báo lỗi hoặc nội dung phát sinh:
                # câu đầu là tiêu đề, phần sau là mô tả.
                message_parts = re.split(
                    r"(?<=[.!?])\s+",
                    message,
                    maxsplit=1
                )

                popup_title = (
                    message_parts[0]
                    .strip()
                    .rstrip(".!?")
                )

                popup_detail = (
                    message_parts[1].strip()
                    if len(message_parts) > 1
                    else ""
                )

                if (
                    "không có thay đổi" in normalized_message
                    and tone == "success"
                ):
                    tone = "info"

            tone_config = {
                "success": {
                    "icon": "✓",
                    "accent": "#16A34A",
                    "icon_background": "#DCFCE7",
                    "icon_border": "#86EFAC",
                    "icon_color": "#166534"
                },

                "info": {
                    "icon": "i",
                    "accent": "#2563EB",
                    "icon_background": "#DBEAFE",
                    "icon_border": "#93C5FD",
                    "icon_color": "#1D4ED8"
                },

                "danger": {
                    "icon": "!",
                    "accent": "#E63946",
                    "icon_background": "#FEE2E2",
                    "icon_border": "#FCA5A5",
                    "icon_color": "#B91C1C"
                }
            }

            popup_theme = tone_config.get(
                tone,
                tone_config["success"]
            )

            safe_title = html.escape(
                popup_title
            )

            safe_detail = html.escape(
                popup_detail
            )

            detail_html = ""

            if safe_detail:
                detail_html = (
                    f'<div class="wc-prediction-popup-detail-'
                    f'{created_at_ms}">'
                    f'{safe_detail}'
                    f'</div>'
                )

            animation_name = (
                f"wcPredictionPopupAnimation{created_at_ms}"
            )

            popup_html = f"""
            <style>
            @keyframes {animation_name} {{
                0% {{
                    opacity: 0;
                    transform:
                        translate(
                            -50%,
                            calc(-50% - 14px)
                        )
                        scale(0.96);
                }}

                8% {{
                    opacity: 1;
                    transform:
                        translate(-50%, -50%)
                        scale(1);
                }}

                84% {{
                    opacity: 1;
                    transform:
                        translate(-50%, -50%)
                        scale(1);
                }}

                100% {{
                    opacity: 0;
                    transform:
                        translate(
                            -50%,
                            calc(-50% - 10px)
                        )
                        scale(0.98);
                }}
            }}

            .wc-prediction-feedback-popup-{created_at_ms} {{
                position: fixed;
                left: 50%;
                top: 50%;
                z-index: 2147483647;

                width: min(
                    390px,
                    calc(100vw - 40px)
                );
                max-width: 390px;

                display: grid;
                grid-template-columns:
                    44px
                    minmax(0, 1fr);

                align-items: center;
                gap: 13px;

                padding:
                    15px
                    17px
                    15px
                    15px;

                box-sizing: border-box;
                border-radius: 18px;

                border:
                    1px solid
                    rgba(18, 60, 105, 0.16);

                border-left:
                    4px solid
                    {popup_theme["accent"]};

                background:
                    radial-gradient(
                        circle at top right,
                        rgba(245, 197, 66, 0.14),
                        transparent 44%
                    ),
                    linear-gradient(
                        135deg,
                        rgba(255, 255, 255, 0.99),
                        rgba(248, 250, 252, 0.98)
                    );

                box-shadow:
                    0 24px 58px
                    rgba(7, 17, 31, 0.22),
                    0 6px 18px
                    rgba(15, 23, 42, 0.10);

                backdrop-filter: blur(14px);
                -webkit-backdrop-filter: blur(14px);

                overflow: hidden;
                pointer-events: none;

                animation:
                    {animation_name}
                    5.2s
                    cubic-bezier(
                        0.22,
                        1,
                        0.36,
                        1
                    )
                    forwards;
            }}

            .wc-prediction-feedback-popup-{created_at_ms}::before {{
                content: "";

                position: absolute;
                left: 18px;
                right: 18px;
                top: 0;

                height: 2px;
                border-radius: 999px;

                background:
                    linear-gradient(
                        90deg,
                        transparent,
                        rgba(245, 197, 66, 0.92),
                        transparent
                    );

                pointer-events: none;
            }}

            .wc-prediction-popup-icon-{created_at_ms} {{
                width: 42px;
                height: 42px;

                display: flex;
                align-items: center;
                justify-content: center;

                box-sizing: border-box;
                border-radius: 999px;

                background:
                    {popup_theme["icon_background"]};

                border:
                    1px solid
                    {popup_theme["icon_border"]};

                color:
                    {popup_theme["icon_color"]};

                font-size: 21px;
                font-weight: 950;
                line-height: 1;

                box-shadow:
                    0 7px 16px
                    rgba(15, 23, 42, 0.08);
            }}

            .wc-prediction-popup-content-{created_at_ms} {{
                min-width: 0;
                text-align: left;
            }}

            .wc-prediction-popup-title-{created_at_ms} {{
                color: #07111F;

                font-size: 15px;
                font-weight: 950;
                line-height: 1.25;

                letter-spacing: -0.015em;

                white-space: normal;
                overflow-wrap: break-word;
            }}

            .wc-prediction-popup-detail-{created_at_ms} {{
                margin-top: 4px;

                color: #64748B;

                font-size: 12.5px;
                font-weight: 600;
                line-height: 1.42;

                white-space: normal;
                overflow-wrap: break-word;
            }}

            @media (max-width: 768px) {{
                .wc-prediction-feedback-popup-{created_at_ms} {{
                    width: min(
                        340px,
                        calc(100vw - 28px)
                    );
                    max-width: 340px;

                    grid-template-columns:
                        40px
                        minmax(0, 1fr);

                    gap: 11px;

                    padding:
                        13px
                        14px
                        13px
                        12px;

                    border-radius: 16px;
                }}

                .wc-prediction-popup-icon-{created_at_ms} {{
                    width: 38px;
                    height: 38px;
                    font-size: 19px;
                }}

                .wc-prediction-popup-title-{created_at_ms} {{
                    font-size: 14px;
                }}

                .wc-prediction-popup-detail-{created_at_ms} {{
                    font-size: 12px;
                    line-height: 1.38;
                }}
            }}

            @media (max-width: 390px) {{
                .wc-prediction-feedback-popup-{created_at_ms} {{
                    width: calc(100vw - 24px);
                    max-width: calc(100vw - 24px);
                }}
            }}
            </style>

            <div
                class="wc-prediction-feedback-popup-{created_at_ms}"
                role="status"
                aria-live="polite"
            ><div
                class="wc-prediction-popup-icon-{created_at_ms}"
            >{popup_theme["icon"]}</div><div
                class="wc-prediction-popup-content-{created_at_ms}"
            ><div
                class="wc-prediction-popup-title-{created_at_ms}"
            >{safe_title}</div>{detail_html}</div></div>
            """

    # Loại bỏ toàn bộ mức thụt đầu dòng của chuỗi HTML.
    popup_html = textwrap.dedent(
        popup_html
    ).strip()

    # st.html render HTML trực tiếp, không chạy qua Markdown parser.
    if hasattr(st, "html"):
        st.html(popup_html)

    else:
        # Fallback cho Streamlit cũ.
        # popup_html đã được dedent và không còn block HTML thụt dòng.
        st.markdown(
            popup_html,
            unsafe_allow_html=True
        )


def _get_submitted_prediction_winner_team_id(
    is_knockout: bool,
    home_team_id: int | None,
    away_team_id: int | None,
    home_name: str,
    away_name: str,
    predicted_home_score: int,
    predicted_away_score: int,
    winner_radio_key: str | None
) -> int | None:
    """
    Đọc đội thắng chung cuộc từ state của form tại thời điểm submit.

    Callback phải đọc widget qua st.session_state vì callback chạy trước
    lượt render tiếp theo của trang.
    """
    if not to_bool(is_knockout):
        return None

    home_team_id = to_optional_int(home_team_id)
    away_team_id = to_optional_int(away_team_id)

    if predicted_home_score > predicted_away_score:
        return home_team_id

    if predicted_away_score > predicted_home_score:
        return away_team_id

    selected_winner_name = (
        st.session_state.get(winner_radio_key)
        if winner_radio_key
        else None
    )

    if selected_winner_name == home_name:
        return home_team_id

    if selected_winner_name == away_name:
        return away_team_id

    return None


def handle_prediction_form_submit(
    user_id: int,
    match_id: int,
    home_team_id: int | None,
    away_team_id: int | None,
    home_name: str,
    away_name: str,
    is_knockout: bool,
    current_star_type: str,
    home_score_key: str,
    away_score_key: str,
    star_radio_key: str,
    winner_radio_key: str | None
):
    """
    Callback duy nhất cho nút Lưu/Cập nhật dự đoán.

    Luồng chạy:
    1. Streamlit cập nhật toàn bộ widget của form vào session_state.
    2. Callback này lưu dữ liệu và clear cache cần thiết.
    3. Streamlit thực hiện đúng một lượt render tự nhiên của trang.

    Không gọi st.rerun() trong callback, tránh tạo hai full rerun liên tiếp.
    """
    user_id = int(user_id)
    match_id = int(match_id)
    current_star_type = normalize_star_type(current_star_type)

    try:
        input_home = int(st.session_state.get(home_score_key, 0))
        input_away = int(st.session_state.get(away_score_key, 0))

        selected_star_type = normalize_star_type(
            st.session_state.get(
                star_radio_key,
                current_star_type
            )
        )

        predicted_winner_team_id = (
            _get_submitted_prediction_winner_team_id(
                is_knockout=is_knockout,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                home_name=home_name,
                away_name=away_name,
                predicted_home_score=input_home,
                predicted_away_score=input_away,
                winner_radio_key=winner_radio_key
            )
        )

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
                set_prediction_feedback_message(
                    match_id=match_id,
                    message=f"Bạn đã dùng hết {star_display_name}.",
                    tone="danger"
                )
                return

            if latest_free_left <= 0:
                transfer_candidates = get_star_transfer_candidates(
                    user_id=user_id,
                    target_match_id=match_id,
                    star_type=selected_star_type
                )

                if not transfer_candidates:
                    set_prediction_feedback_message(
                        match_id=match_id,
                        message=(
                            f"Hiện không còn {star_display_name} "
                            "trống để dùng cho trận này."
                        ),
                        tone="danger"
                    )
                    return

                st.session_state["pending_star_transfer"] = {
                    "target_match_id": match_id,
                    "target_label": f"{home_name} vs {away_name}",
                    "predicted_home_score": input_home,
                    "predicted_away_score": input_away,
                    "predicted_winner_team_id": predicted_winner_team_id,
                    "star_type": selected_star_type,
                    "candidates": transfer_candidates
                }
                return

        save_result = save_prediction(
            user_id=user_id,
            match_id=match_id,
            predicted_home_score=input_home,
            predicted_away_score=input_away,
            predicted_winner_team_id=predicted_winner_team_id,
            star_type=selected_star_type
        )

        st.session_state.pop("pending_star_transfer", None)

        save_status = save_result.get("status")

        if save_status == "created":
            feedback_message = (
                "Đã lưu dự đoán. Bạn vẫn có thể cập nhật "
                "dự đoán cho đến trước giờ bóng lăn."
            )
        elif save_status == "updated":
            feedback_message = "Đã cập nhật dự đoán."
        else:
            feedback_message = "Dự đoán không có thay đổi."

        set_prediction_feedback_message(
            match_id=match_id,
            message=feedback_message,
            tone="success"
        )

    except ValueError as exc:
        set_prediction_feedback_message(
            match_id=match_id,
            message=str(exc),
            tone="danger"
        )

    except Exception:
        LOGGER.exception(
            "Failed to save prediction for user_id=%s match_id=%s",
            user_id,
            match_id
        )
        set_prediction_feedback_message(
            match_id=match_id,
            message=(
                "Không thể lưu dự đoán vào lúc này. "
                "Dữ liệu cũ của bạn vẫn được giữ nguyên."
            ),
            tone="danger"
        )


def handle_delete_prediction_form_submit(
    user_id: int,
    match_id: int
):
    """
    Callback cho nút Xóa dự đoán.
    Không gọi st.rerun(); form tự tạo một lượt render sau callback.
    """
    user_id = int(user_id)
    match_id = int(match_id)

    try:
        delete_result = delete_prediction(
            user_id=user_id,
            match_id=match_id
        )

        st.session_state.pop("pending_star_transfer", None)

        if delete_result.get("status") == "deleted":
            message = "Đã xóa dự đoán."
        else:
            message = "Dự đoán này đã được xóa trước đó."

        set_prediction_feedback_message(
            match_id=match_id,
            message=message,
            tone="success"
        )

    except ValueError as exc:
        set_prediction_feedback_message(
            match_id=match_id,
            message=str(exc),
            tone="danger"
        )

    except Exception:
        LOGGER.exception(
            "Failed to delete prediction for user_id=%s match_id=%s",
            user_id,
            match_id
        )
        set_prediction_feedback_message(
            match_id=match_id,
            message=(
                "Không thể xóa dự đoán vào lúc này. "
                "Dữ liệu cũ của bạn vẫn được giữ nguyên."
            ),
            tone="danger"
        )

def render_prediction_team_logo(
    team_name: str,
    logo_path
):
    """
    Hiển thị logo phía trên bộ chọn tỉ số.
    Render trực tiếp bằng st.html để chuỗi Base64
    không bị Markdown biến thành văn bản.
    """
    team_label = str(
        team_name or "Đội bóng"
    ).strip()

    safe_team_name = html.escape(
        team_label,
        quote=True
    )

    if (
        logo_path is None
        or pd.isna(logo_path)
    ):
        normalized_logo_path = ""
    else:
        normalized_logo_path = str(
            logo_path
        ).strip()

    logo_src = (
        resolve_asset_src(normalized_logo_path)
        if normalized_logo_path
        else ""
    )

    logo_is_valid = bool(
        logo_src
        and logo_src.startswith(
            (
                "data:image/",
                "http://",
                "https://",
                "/app/static/"
            )
        )
    )

    if logo_is_valid:
        safe_logo_src = html.escape(
            logo_src,
            quote=True
        )

        logo_content = (
            f'<img src="{safe_logo_src}" '
            f'alt="" '
            f'aria-hidden="true" '
            f'loading="lazy" '
            f'decoding="async">'
        )
    else:
        logo_content = (
            '<span class="epl-prediction-team-logo-fallback">'
            f'{safe_team_name}'
            '</span>'
        )

    logo_html = f"""
    <div
        class="epl-prediction-team-logo"
        role="img"
        aria-label="Logo {safe_team_name}"
        title="{safe_team_name}"
    >
        {logo_content}
    </div>
    """

    logo_html = textwrap.dedent(
        logo_html
    ).strip()

    if hasattr(st, "html"):
        st.html(logo_html)
    else:
        st.markdown(
            logo_html,
            unsafe_allow_html=True
        )

def _build_finished_score_logo_html(
    team_name: str,
    logo_path
) -> str:
    """
    Tạo logo tĩnh cho hàng tỉ số thật.
    Không tạo widget hoặc session state mới.
    """
    team_label = str(
        team_name or "Đội bóng"
    ).strip()

    safe_team_name = html.escape(
        team_label,
        quote=True
    )

    if (
        logo_path is None
        or pd.isna(logo_path)
    ):
        normalized_logo_path = ""
    else:
        normalized_logo_path = str(
            logo_path
        ).strip()

    logo_src = (
        resolve_asset_src(normalized_logo_path)
        if normalized_logo_path
        else ""
    )

    logo_is_valid = bool(
        logo_src
        and logo_src.startswith(
            (
                "data:image/",
                "http://",
                "https://",
                "/app/static/"
            )
        )
    )

    if logo_is_valid:
        safe_logo_src = html.escape(
            logo_src,
            quote=True
        )

        logo_content = (
            f'<img src="{safe_logo_src}" '
            'alt="" '
            'aria-hidden="true" '
            'loading="lazy" '
            'decoding="async">'
        )
    else:
        logo_content = (
            '<span class="epl-finished-score-logo-fallback">'
            f'{safe_team_name}'
            '</span>'
        )

    return (
        '<div class="epl-finished-score-logo" '
        'role="img" '
        f'aria-label="Logo {safe_team_name}" '
        f'title="{safe_team_name}">'
        f'{logo_content}'
        '</div>'
    )


def render_finished_match_score_row(
    match_id: int,
    home_name: str,
    away_name: str,
    home_logo_path,
    away_logo_path,
    actual_home: int,
    actual_away: int
):
    """
    Hiển thị bảng tỉ số thật dạng read-only.

    Hàm này không tạo widget, không cho phép chỉnh sửa
    và chỉ được gọi với trận đã có kết quả.
    """
    actual_home = int(actual_home)
    actual_away = int(actual_away)

    home_logo_html = (
        _build_finished_score_logo_html(
            home_name,
            home_logo_path
        )
    )

    away_logo_html = (
        _build_finished_score_logo_html(
            away_name,
            away_logo_path
        )
    )

    home_display_name = (
        get_mobile_team_display_name(
            home_name
        )
    )

    away_display_name = (
        get_mobile_team_display_name(
            away_name
        )
    )

    safe_home_name = html.escape(
        str(home_display_name),
        quote=True
    )

    safe_away_name = html.escape(
        str(away_display_name),
        quote=True
    )

    home_is_winner = (
        actual_home > actual_away
    )

    away_is_winner = (
        actual_away > actual_home
    )

    home_team_state = (
        " is-winner"
        if home_is_winner
        else ""
    )

    away_team_state = (
        " is-winner"
        if away_is_winner
        else ""
    )

    home_score_state = (
        " is-winner"
        if home_is_winner
        else ""
    )

    away_score_state = (
        " is-winner"
        if away_is_winner
        else ""
    )

    result_aria_label = html.escape(
        (
            f"Kết quả trận đấu: "
            f"{home_name} "
            f"{actual_home} - {actual_away} "
            f"{away_name}"
        ),
        quote=True
    )

    score_row_html = f"""
    <div class="epl-finished-score-wrap">
        <div
            class="epl-finished-score-label"
            aria-hidden="true"
        >
            <span>Kết thúc</span>
        </div>

        <div
            class="epl-finished-score-row"
            role="group"
            aria-label="{result_aria_label}"
            data-match-id="{int(match_id)}"
        >
            <div
                class="epl-finished-score-team{home_team_state}"
            >
                {home_logo_html}

                <div class="epl-finished-score-team-name">
                    {safe_home_name}
                </div>
            </div>

            <div
                class="epl-finished-score-value"
                aria-hidden="true"
            >
                <span
                    class="epl-finished-score-number{home_score_state}"
                >
                    {actual_home}
                </span>

                <span class="epl-finished-score-separator">
                    &minus;
                </span>

                <span
                    class="epl-finished-score-number{away_score_state}"
                >
                    {actual_away}
                </span>
            </div>

            <div
                class="epl-finished-score-team{away_team_state}"
            >
                {away_logo_html}

                <div class="epl-finished-score-team-name">
                    {safe_away_name}
                </div>
            </div>
        </div>
    </div>
    """

    score_row_html = textwrap.dedent(
        score_row_html
    ).strip()

    if hasattr(st, "html"):
        st.html(score_row_html)
    else:
        st.markdown(
            score_row_html,
            unsafe_allow_html=True
        )
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
    
    is_big_match = is_big_six_match(
        home_name,
        away_name
    )
    
    card_container_key = (
        f"match_card_big_{match_id}"
        if is_big_match
        else f"match_card_{match_id}"
    )
    
    is_knockout = to_bool(row.get("is_knockout"))
    is_finished = to_bool(row.get("is_finished"))

    editable = can_edit_prediction(
        row.get("kickoff_time_utc"),
        is_finished=is_finished
    )

    if user_prediction_map is None:
        existing = get_user_prediction(user_id, match_id)
    else:
        existing = user_prediction_map.get(match_id)

    status_info = get_match_status_info(row)
    card_css = get_match_card_css(status_info)

    with stylable_container(
        key=card_container_key,
        css_styles=card_css
    ):
        render_status_badge(status_info, row=row)
    
        top_left, top_right = st.columns([3, 1])

        with top_left:
            render_match_title(
                home_name,
                away_name,
                match_id,
                row=row,
                is_big_match=is_big_match
            )

            date_value = row.get(
                "kickoff_date_display_vietnam",
                row.get(
                    "kickoff_date_vietnam",
                    ""
                )
            )
            
            time_value = row.get(
                "kickoff_time_vietnam",
                ""
            )
            
            date_text = (
                ""
                if (
                    date_value is None
                    or pd.isna(date_value)
                )
                else str(date_value).strip()
            )
            
            time_text = (
                ""
                if (
                    time_value is None
                    or pd.isna(time_value)
                )
                else str(time_value).strip()
            )
            
            schedule_parts = [
                value
                for value in [
                    time_text,
                    date_text
                ]
                if value
            ]
            
            schedule_text = " • ".join(
                schedule_parts
            )
            
            if schedule_text:
                safe_schedule_text = html.escape(
                    schedule_text,
                    quote=True
                )
            
                st.markdown(
                    (
                        '<div class="epl-match-kickoff">'
                        f'{safe_schedule_text}'
                        '</div>'
                    ),
                    unsafe_allow_html=True
                )

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
            if ENABLE_AI_FEATURES and is_finished:
                ai_summary_clicked = st.button(
                    "AI tóm tắt",
                    key=f"ai_summary_button_{match_id}",
                    type="secondary",
                    use_container_width=True
                )
            
                if ai_summary_clicked:
                    st.session_state["ai_summary_match_id"] = match_id
                    st.rerun()
            
            elif (
                ENABLE_AI_FEATURES
                and status_info.get("status_key") == "open"
                and can_use_ai_match_suggestion(
                    row.get("kickoff_time_utc"),
                    is_finished=is_finished
                )
            ):
                ai_suggestion_clicked = st.button(
                    "AI phân tích",
                    key=f"ai_suggestion_button_{match_id}",
                    type="secondary",
                    use_container_width=True
                )
            
                if ai_suggestion_clicked:
                    st.session_state["ai_suggestion_match_id"] = match_id
                    st.rerun()
            if (
                is_finished
                and actual_home is not None
                and actual_away is not None
            ):
                home_outcome_name = (
                    get_mobile_team_display_name(
                        home_name
                    )
                )

                away_outcome_name = (
                    get_mobile_team_display_name(
                        away_name
                    )
                )

                winner_name = row.get(
                    "winner_team_name"
                )

                winner_name_is_valid = (
                    winner_name is not None
                    and not pd.isna(winner_name)
                    and str(winner_name).strip().lower()
                    not in ["", "nan", "none"]
                )

                if actual_home > actual_away:
                    outcome_text = (
                        f"{home_outcome_name} thắng"
                    )

                elif actual_away > actual_home:
                    outcome_text = (
                        f"{away_outcome_name} thắng"
                    )

                elif (
                    is_knockout
                    and has_penalty
                    and score_pen_home > score_pen_away
                ):
                    outcome_text = (
                        f"{home_outcome_name} thắng"
                    )

                elif (
                    is_knockout
                    and has_penalty
                    and score_pen_away > score_pen_home
                ):
                    outcome_text = (
                        f"{away_outcome_name} thắng"
                    )

                elif (
                    is_knockout
                    and winner_name_is_valid
                ):
                    winner_outcome_name = (
                        get_mobile_team_display_name(
                            winner_name
                        )
                    )

                    outcome_text = (
                        f"{winner_outcome_name} thắng"
                    )

                else:
                    outcome_text = "Hòa"

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
                    f'border-left:5px solid {status_info["border_color"]};'
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
                    f'color:{status_info["badge_text"]};'
                    'font-size:clamp(17px,1.6vw,22px);'
                    'font-weight:950;'
                    'line-height:1.25;'
                    'letter-spacing:-0.02em;'
                    'white-space:normal;'
                    'overflow-wrap:anywhere;'
                    '">'
                    f'{html.escape(str(outcome_text))}'
                    '</div>'
                    f'{penalty_line_html}'
                    '</div>'
                )

                st.markdown(
                    result_card_html,
                    unsafe_allow_html=True
                )

            else:
                render_match_status_box(
                    status_info
                )

        if (
            is_unknown_team(home_name)
            or is_unknown_team(away_name)
        ):
            st.info(
                "Chưa xác định đủ đội, "
                "tạm thời chưa mở dự đoán."
            )

            render_match_venue_footer(
                row,
                match_id
            )

            return

        if (
            is_finished
            and actual_home is not None
            and actual_away is not None
        ):
            render_finished_match_score_row(
                match_id=match_id,
                home_name=home_name,
                away_name=away_name,
                home_logo_path=row.get(
                    "home_team_logo_path"
                ),
                away_logo_path=row.get(
                    "away_team_logo_path"
                ),
                actual_home=actual_home,
                actual_away=actual_away
            )

            # Nút và danh sách cầu thủ ghi bàn
            # nằm ngay dưới bảng tỉ số.
            if (actual_home + actual_away) > 0:
                render_goal_scorers_for_match(
                    match_id=match_id,
                    home_name=home_name,
                    away_name=away_name
                )

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
        
            with st.container(
                key=f"prediction_score_row_{match_id}"
            ):
                # Giữ nguyên bố cục desktop ban đầu:
                # đội nhà 2 phần, khoảng giữa 1 phần, đội khách 2 phần.
                col_home, col_mid, col_away = st.columns(
                    [2, 1, 2],
                    gap="small"
                )
            
                with col_home:
                    with st.container(
                        key=f"home_score_shell_{match_id}"
                    ):
                        render_prediction_team_logo(
                            team_name=home_name,
                            logo_path=row.get(
                                "home_team_logo_path"
                            )
                        )
                
                        input_home = st.number_input(
                            home_name,
                            min_value=0,
                            max_value=20,
                            value=pred_home,
                            step=1,
                            key=f"home_score_{match_id}"
                        )
            
                with col_away:
                    with st.container(
                        key=f"away_score_shell_{match_id}"
                    ):
                        render_prediction_team_logo(
                            team_name=away_name,
                            logo_path=row.get(
                                "away_team_logo_path"
                            )
                        )
                
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
            winner_radio_key = None

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
            hope_display_total = int(
                star_usage_for_display.get("hope_total", HOPE_STARS_PER_USER)
            )
            
            super_display_total = int(
                star_usage_for_display.get("super_total", SUPER_STARS_PER_USER)
            )

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
                        f"(Kho còn lại: {hope_display_left}/{hope_display_total}; "
                        f"Đang dùng: {hope_display_using}/{hope_display_total})"
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
                        f"(Kho còn lại: {super_display_left}/{super_display_total}; "
                        f"Đang dùng: {super_display_using}/{super_display_total})"
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

            submit_callback_kwargs = {
                "user_id": int(user_id),
                "match_id": int(match_id),
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "home_name": home_name,
                "away_name": away_name,
                "is_knockout": is_knockout,
                "current_star_type": current_star_type,
                "home_score_key": f"home_score_{match_id}",
                "away_score_key": f"away_score_{match_id}",
                "star_radio_key": star_radio_key,
                "winner_radio_key": winner_radio_key
            }

            if existing:
                with stylable_container(
                    key=f"prediction_action_spacing_shell_{match_id}",
                    css_styles=get_prediction_action_spacing_css()
                ):
                    save_col, delete_col = st.columns(
                        [1, 1],
                        gap="small"
                    )

                    with save_col:
                        with stylable_container(
                            key=f"prediction_primary_button_shell_{match_id}",
                            css_styles=get_prediction_primary_button_css()
                        ):
                            st.form_submit_button(
                                "Cập nhật dự đoán",
                                on_click=handle_prediction_form_submit,
                                kwargs=submit_callback_kwargs
                            )

                    with delete_col:
                        with stylable_container(
                            key=f"delete_prediction_button_shell_{match_id}",
                            css_styles=get_prediction_delete_button_css()
                        ):
                            st.form_submit_button(
                                "Xóa dự đoán",
                                help="Xóa dự đoán",
                                on_click=handle_delete_prediction_form_submit,
                                kwargs={
                                    "user_id": int(user_id),
                                    "match_id": int(match_id)
                                }
                            )

            else:
                with stylable_container(
                    key=f"prediction_action_spacing_shell_{match_id}",
                    css_styles=get_prediction_action_spacing_css()
                ):
                    with stylable_container(
                        key=f"prediction_primary_button_shell_{match_id}",
                        css_styles=get_prediction_primary_button_css()
                    ):
                        st.form_submit_button(
                            "Lưu dự đoán",
                            on_click=handle_prediction_form_submit,
                            kwargs=submit_callback_kwargs
                        )

        render_match_venue_footer(row, match_id)

# ============================================================
# 10. PAGES
# ============================================================
def sync_filter_menu_value(menu_key: str, state_key: str):
    """
    Đồng bộ lựa chọn từ st.menu_button sang session_state của bộ lọc.
    Callback chạy trước khi app render lại nên nhãn dropdown cập nhật ngay.
    """
    selected_value = st.session_state.get(menu_key)

    if selected_value is not None:
        st.session_state[state_key] = selected_value


def render_filter_dropdown(
    label: str,
    options,
    state_key: str,
    menu_key: str,
    format_func=None
):
    """
    Render dropdown thuần túy:
    - Không có ô input.
    - Không thể gõ hoặc xóa chữ.
    - Hiển thị giá trị hiện đang chọn trên nút.
    - Có dấu ✓ trước option đang được chọn.
    """
    if format_func is None:
        format_func = lambda value: str(value)

    current_value = st.session_state[state_key]

    st.markdown(
        f"""
        <div class="wc-filter-dropdown-label">
            {html.escape(str(label))}
        </div>
        """,
        unsafe_allow_html=True
    )

    st.menu_button(
        label=format_func(current_value),
        options=options,
        key=menu_key,
        width="stretch",
        format_func=lambda value: (
            f"✓ {format_func(value)}"
            if value == current_value
            else format_func(value)
        ),
        on_click=sync_filter_menu_value,
        args=(menu_key, state_key)
    )

    return st.session_state[state_key]

def page_matches():
    render_app_hero()
    render_season_selector()

    render_page_title(
        "Lịch thi đấu & dự đoán",
        f"Đang xem {get_selected_season_title()}. Cuộn xuống dưới để xem lịch thi đấu và nhập dự đoán cho từng trận."
    )

    render_prediction_feedback_popup()

    matches = load_matches(get_selected_season_slug())

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
    
    ai_summary_match_id = st.session_state.pop("ai_summary_match_id", None)
    
    if ai_summary_match_id is not None:
        render_ai_match_summary_dialog(
            int(ai_summary_match_id)
        )
    
    ai_suggestion_match_id = st.session_state.pop("ai_suggestion_match_id", None)
    
    if ai_suggestion_match_id is not None:
        render_ai_match_suggestion_dialog(
            int(ai_suggestion_match_id)
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
    default_filter_date = get_default_filter_date_for_season(
        available_dates
    )

    if "filter_date" not in st.session_state:
        st.session_state["filter_date"] = default_filter_date
    
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
    
    min_filter_date = date_options[0]
    max_filter_date = date_options[-1]
    
    current_filter_date = st.session_state["filter_date"]
    
    if (
        current_filter_date < min_filter_date
        or current_filter_date > max_filter_date
    ):
        st.session_state["filter_date"] = default_filter_date
    
    if st.session_state["filter_status"] not in status_options:
        st.session_state["filter_status"] = "Tất cả"
    
    if (
        st.session_state["filter_prediction_status"]
        not in prediction_status_options
    ):
        st.session_state["filter_prediction_status"] = "Tất cả"

    inject_match_datepicker_calendar_theme(
        available_dates
    )
    
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

        .wc-filter-dropdown-label {
            color: #334155 !important;
            font-weight: 850 !important;
            font-size: 13px !important;
            line-height: 1.25 !important;
            margin-bottom: 7px !important;
        }
        /* =========================
           Bộ chọn ngày dạng lịch
           ========================= */
        
        div[data-testid="stDateInput"] {
            width: 100% !important;
            margin: 0 !important;
        }
        
        div[data-testid="stDateInput"] div[data-baseweb="input"] {
            width: 100% !important;
            min-height: 44px !important;
        
            background: rgba(248, 250, 252, 0.95) !important;
        
            border: 1px solid rgba(15, 23, 42, 0.10) !important;
            border-radius: 14px !important;
        
            box-shadow:
                inset 0 1px 0 rgba(255, 255, 255, 0.70),
                0 1px 2px rgba(15, 23, 42, 0.02) !important;
        
            transition:
                border-color 0.16s ease,
                background 0.16s ease,
                box-shadow 0.16s ease !important;
        }
        
        div[data-testid="stDateInput"] div[data-baseweb="input"]:hover {
            background: #FFFFFF !important;
            border-color: rgba(7, 17, 31, 0.55) !important;
        
            box-shadow:
                inset 0 1px 0 rgba(255, 255, 255, 0.85),
                0 5px 14px rgba(15, 23, 42, 0.07) !important;
        }
        
        div[data-testid="stDateInput"] div[data-baseweb="input"]:focus-within {
            background: #FFFFFF !important;
            border-color: #2563EB !important;
        
            box-shadow:
                0 0 0 3px rgba(37, 99, 235, 0.10),
                0 6px 16px rgba(15, 23, 42, 0.08) !important;
        }
        
        div[data-testid="stDateInput"] input {
            min-height: 42px !important;
            padding-left: 14px !important;
        
            background: transparent !important;
            color: #0F172A !important;
        
            border: none !important;
            box-shadow: none !important;
        
            font-size: 14px !important;
            font-weight: 500 !important;
        }
        
        div[data-testid="stDateInput"] input:focus {
            border: none !important;
            box-shadow: none !important;
            outline: none !important;
        }
        /* =========================
           Slicer Ngày thi đấu
           ========================= */
        
        div[class*="st-key-filter_date"] {
            width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        
        div[class*="st-key-filter_date"] div[data-testid="stDateInput"] {
            width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        
        div[class*="st-key-filter_date"] div[data-baseweb="input"] {
            position: relative !important;
        
            width: 100% !important;
            min-height: 44px !important;
        
            background: rgba(248, 250, 252, 0.95) !important;
        
            border: 1px solid rgba(15, 23, 42, 0.10) !important;
            border-radius: 14px !important;
        
            box-shadow:
                inset 0 1px 0 rgba(255, 255, 255, 0.70) !important;
        
            overflow: hidden !important;
        
            transition:
                border-color 0.16s ease,
                background 0.16s ease,
                box-shadow 0.16s ease !important;
        }
        
        div[class*="st-key-filter_date"] div[data-baseweb="input"]:hover {
            background: #FFFFFF !important;
            border-color: rgba(7, 17, 31, 0.55) !important;
        }
        
        div[class*="st-key-filter_date"] div[data-baseweb="input"]:focus-within {
            background: #FFFFFF !important;
            border-color: #2563EB !important;
        
            box-shadow:
                0 0 0 3px rgba(37, 99, 235, 0.10),
                0 6px 16px rgba(15, 23, 42, 0.08) !important;
        }
        
        div[class*="st-key-filter_date"] input {
            width: 100% !important;
            min-height: 42px !important;
        
            padding: 0 44px 0 14px !important;
        
            background: transparent !important;
            color: #0F172A !important;
        
            border: none !important;
            outline: none !important;
            box-shadow: none !important;
        
            font-size: 14px !important;
            font-weight: 500 !important;
            line-height: 1 !important;
        }
        
        /* Ẩn icon lịch native đang bị biến thành chấm tròn */
        div[class*="st-key-filter_date"]
        div[data-baseweb="input"] svg {
            display: none !important;
            visibility: hidden !important;
        }
        
        /* Vẽ lại icon lịch sạch và đúng vị trí */
        div[class*="st-key-filter_date"]
        div[data-baseweb="input"]::after {
            content: "";
        
            position: absolute;
            top: 50%;
            right: 14px;
        
            width: 18px;
            height: 18px;
        
            transform: translateY(-50%);
        
            background: #334155;
        
            -webkit-mask:
                url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='5' width='18' height='16' rx='2'/%3E%3Cpath d='M16 3v4M8 3v4M3 11h18'/%3E%3C/svg%3E")
                center / contain no-repeat;
        
            mask:
                url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='5' width='18' height='16' rx='2'/%3E%3Cpath d='M16 3v4M8 3v4M3 11h18'/%3E%3C/svg%3E")
                center / contain no-repeat;
        
            pointer-events: none;
        }
        
        @media (max-width: 768px) {
            div[class*="st-key-filter_date"]
            div[data-baseweb="input"] {
                min-height: 46px !important;
            }
        
            div[class*="st-key-filter_date"] input {
                min-height: 44px !important;
                font-size: 14px !important;
            }
        }
        @media (max-width: 768px) {
            div[data-testid="stDateInput"] div[data-baseweb="input"] {
                min-height: 46px !important;
            }
        
            div[data-testid="stDateInput"] input {
                min-height: 44px !important;
                font-size: 14px !important;
            }
        }
        
        /* Wrapper của ba dropdown */
        div[class*="st-key-filter_date_menu"],
        div[class*="st-key-filter_status_menu"],
        div[class*="st-key-filter_prediction_status_menu"] {
            width: 100% !important;
            margin: 0 !important;
        }
        
        /* Nút dropdown */
        div[class*="st-key-filter_date_menu"] button,
        div[class*="st-key-filter_status_menu"] button,
        div[class*="st-key-filter_prediction_status_menu"] button {
            position: relative !important;
        
            width: 100% !important;
            min-width: 100% !important;
            min-height: 44px !important;
        
            padding: 0 42px 0 14px !important;
            margin: 0 !important;
        
            border-radius: 14px !important;
            border: 1px solid rgba(15, 23, 42, 0.10) !important;
        
            background: rgba(248, 250, 252, 0.95) !important;
            color: #0F172A !important;
        
            box-shadow:
                inset 0 1px 0 rgba(255, 255, 255, 0.70),
                0 1px 2px rgba(15, 23, 42, 0.02) !important;
        
            display: flex !important;
            align-items: center !important;
            justify-content: flex-start !important;
        
            text-align: left !important;
            font-size: 14px !important;
            font-weight: 500 !important;
            line-height: 1.2 !important;
            white-space: nowrap !important;
        
            cursor: pointer !important;
        
            transition:
                border-color 0.16s ease,
                background 0.16s ease,
                box-shadow 0.16s ease !important;
        }
        
        /* Mũi tên dropdown cố định ở bên phải */
        div[class*="st-key-filter_date_menu"] button::after,
        div[class*="st-key-filter_status_menu"] button::after,
        div[class*="st-key-filter_prediction_status_menu"] button::after {
            content: "";
            position: absolute;
        
            right: 16px;
            top: 50%;
        
            width: 7px;
            height: 7px;
        
            border-right: 2px solid #334155;
            border-bottom: 2px solid #334155;
        
            transform:
                translateY(-70%)
                rotate(45deg);
        
            pointer-events: none;
        }
        
        /* Ẩn mũi tên mặc định của st.menu_button.
           Chỉ giữ mũi tên custom button::after ở góc phải. */
        div[class*="st-key-filter_date_menu"] button svg,
        div[class*="st-key-filter_status_menu"] button svg,
        div[class*="st-key-filter_prediction_status_menu"] button svg,
        
        div[class*="st-key-filter_date_menu"] button [data-testid="stIconMaterial"],
        div[class*="st-key-filter_status_menu"] button [data-testid="stIconMaterial"],
        div[class*="st-key-filter_prediction_status_menu"] button [data-testid="stIconMaterial"],
        
        div[class*="st-key-filter_date_menu"] button span[class*="material-symbols"],
        div[class*="st-key-filter_status_menu"] button span[class*="material-symbols"],
        div[class*="st-key-filter_prediction_status_menu"] button span[class*="material-symbols"] {
            display: none !important;
            visibility: hidden !important;
            width: 0 !important;
            min-width: 0 !important;
            height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
        }
        
        /* Giữ màu chữ cho các phần tử con */
        div[class*="st-key-filter_date_menu"] button *,
        div[class*="st-key-filter_status_menu"] button *,
        div[class*="st-key-filter_prediction_status_menu"] button * {
            color: #0F172A !important;
            font-size: inherit !important;
            font-weight: inherit !important;
            white-space: nowrap !important;
        }
        
        /* Hover */
        div[class*="st-key-filter_date_menu"] button:hover,
        div[class*="st-key-filter_status_menu"] button:hover,
        div[class*="st-key-filter_prediction_status_menu"] button:hover {
            background: #FFFFFF !important;
            border-color: rgba(7, 17, 31, 0.55) !important;
        
            box-shadow:
                inset 0 1px 0 rgba(255, 255, 255, 0.85),
                0 5px 14px rgba(15, 23, 42, 0.07) !important;
        
            transform: none !important;
        }
        
        /* Khi đang mở dropdown */
        div[class*="st-key-filter_date_menu"] button[aria-expanded="true"],
        div[class*="st-key-filter_status_menu"] button[aria-expanded="true"],
        div[class*="st-key-filter_prediction_status_menu"] button[aria-expanded="true"] {
            background: #FFFFFF !important;
            border-color: #2563EB !important;
        
            box-shadow:
                0 0 0 3px rgba(37, 99, 235, 0.10),
                0 6px 16px rgba(15, 23, 42, 0.08) !important;
        }
        
        /* Quay mũi tên khi menu mở */
        div[class*="st-key-filter_date_menu"] button[aria-expanded="true"]::after,
        div[class*="st-key-filter_status_menu"] button[aria-expanded="true"]::after,
        div[class*="st-key-filter_prediction_status_menu"] button[aria-expanded="true"]::after {
            transform:
                translateY(-25%)
                rotate(225deg);
        }
        
        @media (max-width: 768px) {
            .wc-filter-dropdown-label {
                margin-top: 4px !important;
            }
        
            div[class*="st-key-filter_date_menu"] button,
            div[class*="st-key-filter_status_menu"] button,
            div[class*="st-key-filter_prediction_status_menu"] button {
                min-height: 46px !important;
                font-size: 14px !important;
            }
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

        col_filter_1, col_filter_2, col_filter_3 = st.columns(
            [1, 1, 1],
            gap="medium"
        )
        
        with col_filter_1:
            st.markdown(
                """
                <div class="wc-filter-dropdown-label">
                    Ngày thi đấu
                </div>
                """,
                unsafe_allow_html=True
            )
        
            selected_date = st.date_input(
                label="Ngày thi đấu",
                key="filter_date",
                min_value=min_filter_date,
                max_value=max_filter_date,
                format="DD/MM/YYYY",
                help="Bấm để chọn ngày thi đấu trên lịch",
                label_visibility="collapsed"
            )
        
        with col_filter_2:
            status_filter = render_filter_dropdown(
                label="Trạng thái",
                options=status_options,
                state_key="filter_status",
                menu_key="filter_status_menu"
            )
        
        with col_filter_3:
            prediction_status_filter = render_filter_dropdown(
                label="Tình trạng dự đoán",
                options=prediction_status_options,
                state_key="filter_prediction_status",
                menu_key="filter_prediction_status_menu"
            )

    filtered = matches.copy()

    filtered = filtered[
        filtered["kickoff_date_filter"] == selected_date
    ]

    now_utc = pd.Timestamp.now(tz="UTC")
    is_finished_filter = filtered["is_finished"].map(
        to_bool
    )

    if status_filter == "Sắp diễn ra":
        filtered = filtered[
            (filtered["kickoff_time_utc_dt"] > now_utc)
            & (~is_finished_filter)
        ]

    elif status_filter == "Đã khóa":
        filtered = filtered[
            (filtered["kickoff_time_utc_dt"] <= now_utc)
            & (~is_finished_filter)
        ]

    elif status_filter == "Đã có kết quả":
        filtered = filtered[
            is_finished_filter
        ]

    user_predictions = load_user_predictions(
        user_id,
        get_selected_season_slug()
    )
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

    # Khởi tạo đúng một timer sau khi toàn bộ badge đã có trong DOM.
    inject_match_countdown_runtime()

def page_my_predictions():
    render_page_title(
        "Dự đoán của tôi",
        "Theo dõi toàn bộ dự đoán đã lưu và điểm số từng trận."
    )

    user_id = st.session_state["user"]["user_id"]
    season_slug = get_selected_season_slug()

    # Trang cá nhân chỉ cần chấm dự đoán của chính user đang xem.
    score_all_predictions(
        season_slug,
        user_id=int(user_id)
    )

    matches = load_matches(season_slug)
    my_predictions = load_user_predictions(
        int(user_id),
        season_slug
    )

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
        "Điểm bổ trợ": df["star_bonus_points"].apply(
            lambda x: "" if pd.isna(x) else str(int(round(float(x))))
        ),
        "Điểm": df["points"].apply(
            lambda x: "" if pd.isna(x) else str(int(round(float(x))))
        )
    })

    mobile_display_df = display_df.copy()
    mobile_display_df["Trận"] = df.apply(
        lambda row: (
            f"{get_mobile_team_display_name(row.get('home_team_name'))}"
            " vs "
            f"{get_mobile_team_display_name(row.get('away_team_name'))}"
        ),
        axis=1
    )

    leaderboard = build_leaderboard_df(season_slug)

    current_user_summary = leaderboard[
        leaderboard["user_id"].astype(int) == int(user_id)
    ]

    if current_user_summary.empty:
        prediction_points = int(
            pd.to_numeric(df["points"], errors="coerce").fillna(0).sum()
        )
        round_champion_bonus_points = 0
        round_champion_count = 0
        total_points = prediction_points
        current_rank = "-"
    else:
        user_summary_row = current_user_summary.iloc[0]
        prediction_points = int(
            user_summary_row["prediction_points"]
        )
        round_champion_bonus_points = int(
            user_summary_row["round_champion_bonus_points"]
        )
        round_champion_count = int(
            user_summary_row["round_champion_count"]
        )
        total_points = int(
            user_summary_row["total_points"]
        )
        current_rank = int(
            user_summary_row["rank"]
        )

    rank_display = "-" if current_rank == "-" else f"#{current_rank}"

    scored_points = pd.to_numeric(df["points"], errors="coerce")
    scored_match_count = int(scored_points.notna().sum())

    if scored_match_count == 0:
        avg_points_per_scored_match = 0.0
    else:
        avg_points_per_scored_match = (
            prediction_points
            / scored_match_count
        )

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
        st.markdown(
            """
            <style>
            div[class*="st-key-my_predictions_mobile_table"] {
                display: none !important;
            }

            @media (max-width: 768px) {
                div[class*="st-key-my_predictions_desktop_table"] {
                    display: none !important;
                }

                div[class*="st-key-my_predictions_mobile_table"] {
                    display: block !important;
                }
            }
            </style>
            """,
            unsafe_allow_html=True
        )

        with st.container(
            key="my_predictions_desktop_table"
        ):
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True
            )

        with st.container(
            key="my_predictions_mobile_table"
        ):
            st.dataframe(
                mobile_display_df,
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

        st.caption(
            f"Điểm dự đoán: {prediction_points} • "
            f"Thưởng vòng: +{round_champion_bonus_points} • "
            f"Vô địch vòng: {round_champion_count}"
        )

        st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

def build_round_champion_bonus_df(
    predictions: pd.DataFrame,
    matches: pd.DataFrame
) -> pd.DataFrame:
    result_columns = [
        "user_id",
        "round_champion_count",
        "round_champion_bonus_points"
    ]

    if predictions.empty or matches.empty:
        return pd.DataFrame(
            columns=result_columns
        )

    required_match_columns = {
        "match_id",
        "round_name",
        "is_finished",
        "home_score_for_prediction",
        "away_score_for_prediction"
    }

    if not required_match_columns.issubset(
        matches.columns
    ):
        return pd.DataFrame(
            columns=result_columns
        )

    round_matches = (
        matches[
            [
                "match_id",
                "round_name",
                "is_finished",
                "home_score_for_prediction",
                "away_score_for_prediction"
            ]
        ]
        .drop_duplicates(
            subset=["match_id"]
        )
        .copy()
    )

    round_matches["round_name"] = (
        round_matches["round_name"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    round_matches = round_matches[
        round_matches["round_name"].ne("")
    ].copy()

    if round_matches.empty:
        return pd.DataFrame(
            columns=result_columns
        )

    actual_home = pd.to_numeric(
        round_matches[
            "home_score_for_prediction"
        ],
        errors="coerce"
    )

    actual_away = pd.to_numeric(
        round_matches[
            "away_score_for_prediction"
        ],
        errors="coerce"
    )

    round_matches["is_complete"] = (
        round_matches["is_finished"].map(
            to_bool
        )
        & actual_home.notna()
        & actual_away.notna()
    )

    round_status = (
        round_matches
        .groupby(
            "round_name",
            as_index=False
        )
        .agg(
            match_count=(
                "match_id",
                "nunique"
            ),
            completed_match_count=(
                "is_complete",
                "sum"
            )
        )
    )

    # Chỉ chốt vô địch khi:
    # - database đã có đủ 10 trận của vòng;
    # - cả 10 trận đều đã có kết quả hợp lệ.
    eligible_round_names = round_status.loc[
        (
            round_status["match_count"]
            .eq(EPL_MATCHES_PER_ROUND)
        )
        & (
            round_status[
                "completed_match_count"
            ].eq(
                round_status["match_count"]
            )
        ),
        "round_name"
    ]

    if eligible_round_names.empty:
        return pd.DataFrame(
            columns=result_columns
        )

    eligible_matches = round_matches.loc[
        round_matches["round_name"].isin(
            eligible_round_names
        ),
        [
            "match_id",
            "round_name"
        ]
    ]

    round_predictions = (
        predictions[
            [
                "prediction_id",
                "user_id",
                "match_id",
                "points"
            ]
        ]
        .merge(
            eligible_matches,
            on="match_id",
            how="inner"
        )
    )

    round_predictions["points"] = pd.to_numeric(
        round_predictions["points"],
        errors="coerce"
    )

    # Chỉ xét người thực sự tham gia vòng,
    # tức có ít nhất một dự đoán đã được chấm.
    round_predictions = round_predictions[
        round_predictions["points"].notna()
    ].copy()

    if round_predictions.empty:
        return pd.DataFrame(
            columns=result_columns
        )

    round_totals = (
        round_predictions
        .groupby(
            [
                "round_name",
                "user_id"
            ],
            as_index=False
        )
        .agg(
            round_points=(
                "points",
                "sum"
            ),
            prediction_count=(
                "prediction_id",
                "nunique"
            )
        )
    )

    round_totals = round_totals[
        round_totals[
            "prediction_count"
        ].gt(0)
    ].copy()

    if round_totals.empty:
        return pd.DataFrame(
            columns=result_columns
        )

    round_totals["top_round_points"] = (
        round_totals
        .groupby("round_name")[
            "round_points"
        ]
        .transform("max")
    )

    # Không dùng rank hoặc drop_duplicates:
    # tất cả người bằng điểm cao nhất đều là đồng vô địch.
    champions = round_totals[
        round_totals["round_points"].eq(
            round_totals[
                "top_round_points"
            ]
        )
    ].copy()

    champion_summary = (
        champions
        .groupby(
            "user_id",
            as_index=False
        )
        .agg(
            round_champion_count=(
                "round_name",
                "nunique"
            )
        )
    )

    champion_summary[
        "round_champion_count"
    ] = (
        champion_summary[
            "round_champion_count"
        ]
        .astype(int)
    )

    champion_summary[
        "round_champion_bonus_points"
    ] = (
        champion_summary[
            "round_champion_count"
        ]
        * ROUND_CHAMPION_BONUS_POINTS
    )

    return champion_summary[
        result_columns
    ]

@st.cache_data(
    ttl=10,
    max_entries=8,
    show_spinner=False
)
def build_leaderboard_df(season_slug: str | None = None):
    users = load_users()
    season_slug = season_slug or get_selected_season_slug()
    predictions = load_predictions(season_slug)
    matches = load_matches(season_slug)

    if users.empty:
        return pd.DataFrame()

    if predictions.empty:
        result = users.copy()
        result["prediction_points"] = 0
        result["round_champion_count"] = 0
        result["round_champion_bonus_points"] = 0
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
        result["wrong_prediction_count"] = 0
        result["wrong_prediction_rate"] = 0.0
        result["average_points_per_scored_match"] = 0.0
        result["knockout_winner_rate"] = 0.0
        result["result_prediction_checkable"] = 0
        result["result_prediction_correct"] = 0
        result["result_prediction_rate"] = 0.0

        if "avatar_key" not in result.columns:
            result["avatar_key"] = DEFAULT_AVATAR_KEY

        result = result.sort_values("display_name").reset_index(drop=True)
        result["rank"] = range(1, len(result) + 1)

        return result

    match_columns = [
        "match_id",
        "home_score_for_prediction",
        "away_score_for_prediction",
        "is_finished",
        "is_knockout",
        "winner_team_id",
        "kickoff_time_utc"
    ]

    # Chỉ ghép predictions với dữ liệu trận ở bước tính toán.
    # Thông tin user được ghép lại sau khi aggregate để giảm kích thước
    # DataFrame trung gian và vẫn giữ người chơi chưa có dự đoán.
    df = predictions.merge(
        matches[match_columns],
        on="match_id",
        how="left"
    )

    pred_home = pd.to_numeric(
        df["predicted_home_score"],
        errors="coerce"
    )
    pred_away = pd.to_numeric(
        df["predicted_away_score"],
        errors="coerce"
    )
    actual_home = pd.to_numeric(
        df["home_score_for_prediction"],
        errors="coerce"
    )
    actual_away = pd.to_numeric(
        df["away_score_for_prediction"],
        errors="coerce"
    )
    is_finished = df["is_finished"].map(to_bool)

    df["is_scored"] = (
        pred_home.notna()
        & pred_away.notna()
        & actual_home.notna()
        & actual_away.notna()
        & is_finished
    )

    df["exact_score"] = (
        df["is_scored"]
        & pred_home.eq(actual_home)
        & pred_away.eq(actual_away)
    )

    df["correct_outcome"] = df["is_scored"] & (
        (
            pred_home.gt(pred_away)
            & actual_home.gt(actual_away)
        )
        | (
            pred_home.lt(pred_away)
            & actual_home.lt(actual_away)
        )
        | (
            pred_home.eq(pred_away)
            & actual_home.eq(actual_away)
        )
    )

    is_knockout = df["is_knockout"].map(to_bool)
    predicted_winner = pd.to_numeric(
        df["predicted_winner_team_id"],
        errors="coerce"
    )
    actual_winner = pd.to_numeric(
        df["winner_team_id"],
        errors="coerce"
    )

    df["knockout_winner_checkable"] = (
        df["is_scored"]
        & is_knockout
        & actual_winner.notna()
    )

    df["knockout_winner_correct"] = (
        df["knockout_winner_checkable"]
        & predicted_winner.eq(actual_winner)
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

    normalized_stars = (
        df["star_type"]
        .fillna(STAR_TYPE_NONE)
        .astype(str)
        .str.strip()
        .str.lower()
    )
    df["star_type"] = normalized_stars.where(
        normalized_stars.isin(STAR_CONFIG),
        STAR_TYPE_NONE
    )

    # Chỉ tính sao là đã dùng thật khi trận đã khóa dự đoán.
    # Sao đang đặt ở trận chưa diễn ra không bị trừ khỏi kho sao thực tế.
    kickoff_time = pd.to_datetime(
        df["kickoff_time_utc"],
        utc=True,
        errors="coerce"
    )
    df["is_star_locked_for_usage"] = (
        is_finished
        | kickoff_time.isna()
        | kickoff_time.le(pd.Timestamp.now(tz="UTC"))
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
            ["user_id"],
            as_index=False
        )
        .agg(
            prediction_points=("points", "sum"),
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

    round_champion_bonus = (
        build_round_champion_bonus_df(
            predictions=predictions,
            matches=matches
        )
    )

    # Left join từ users để người chơi chưa dự đoán vẫn xuất hiện trên BXH
    # với toàn bộ chỉ số bằng 0. Bản cũ làm họ biến mất khi đã có ít nhất
    # một người chơi khác gửi dự đoán.
    summary = users.merge(
        summary,
        on="user_id",
        how="left"
    )

    summary = summary.merge(
        round_champion_bonus,
        on="user_id",
        how="left"
    )

    if "avatar_key" not in summary.columns:
        summary["avatar_key"] = DEFAULT_AVATAR_KEY
    else:
        summary["avatar_key"] = (
            summary["avatar_key"]
            .fillna(DEFAULT_AVATAR_KEY)
        )

    numeric_cols = [
        "prediction_points",
        "round_champion_count",
        "round_champion_bonus_points",
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

    summary["total_points"] = (
        summary["prediction_points"]
        + summary["round_champion_bonus_points"]
    ).astype(int)

    summary["exact_score_rate"] = (
        summary["exact_score_count"].astype(float)
        .div(
            summary["num_scored"].astype(float).where(
                summary["num_scored"].ne(0)
            )
        )
        .fillna(0.0)
    )

    summary["result_prediction_checkable"] = summary["num_scored"]
    
    summary["result_prediction_correct"] = summary["correct_outcome_count"]
    
    summary["result_prediction_rate"] = (
        summary["result_prediction_correct"]
        .astype(float)
        .div(
            summary["result_prediction_checkable"]
            .astype(float)
            .where(
                summary[
                    "result_prediction_checkable"
                ].ne(0)
            )
        )
        .fillna(0.0)
    )

    summary["outcome_rate"] = (
        summary["result_prediction_rate"]
    )

    summary["wrong_prediction_count"] = (
        summary["num_scored"]
        - summary["correct_outcome_count"]
    ).clip(lower=0).astype(int)

    summary["wrong_prediction_rate"] = (
        summary["wrong_prediction_count"]
        .astype(float)
        .div(
            summary["num_scored"]
            .astype(float)
            .where(
                summary["num_scored"].ne(0)
            )
        )
        .fillna(0.0)
    )

    # Điểm trung bình chỉ dùng điểm của các trận đã chấm.
    # Thưởng vô địch vòng không được chia ngược vào từng trận.
    summary["average_points_per_scored_match"] = (
        summary["prediction_points"]
        .astype(float)
        .div(
            summary["num_scored"]
            .astype(float)
            .where(
                summary["num_scored"].ne(0)
            )
        )
        .fillna(0.0)
    )

    summary["knockout_winner_rate"] = (
        summary["knockout_winner_correct"]
        .astype(float)
        .div(
            summary["knockout_winner_checkable"]
            .astype(float)
            .where(
                summary["knockout_winner_checkable"].ne(0)
            )
        )
        .fillna(0.0)
    )

    summary = summary.sort_values(
        [
            "total_points",
            "exact_score_count",
            "correct_outcome_count",
            "display_name"
        ],
        ascending=[False, False, False, True]
    ).reset_index(drop=True)

    summary["rank"] = range(1, len(summary) + 1)

    return summary

def build_epl_standings_df(matches: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Logo",
        "Đội bóng",
        "Trận",
        "Thắng",
        "Hòa",
        "Thua",
        "Bàn thắng",
        "Bàn thua",
        "Hiệu số",
        "Điểm",
        "Phong độ"
    ]

    if matches.empty:
        return pd.DataFrame(columns=columns)

    table = {}

    def ensure_team(team_id, team_name, logo_path=None):
        team_id_int = to_optional_int(team_id)
        team_key = f"id:{team_id_int}" if team_id_int is not None else f"name:{str(team_name).strip().lower()}"

        if team_key not in table:
            table[team_key] = {
                "Logo": str(logo_path).strip() if logo_path and not pd.isna(logo_path) else "",
                "Đội bóng": str(team_name).strip(),
                "Trận": 0,
                "Thắng": 0,
                "Hòa": 0,
                "Thua": 0,
                "Bàn thắng": 0,
                "Bàn thua": 0,
                "Hiệu số": 0,
                "Điểm": 0,
                "Phong độ": []
            }
        elif not table[team_key]["Logo"] and logo_path and not pd.isna(logo_path):
            table[team_key]["Logo"] = str(logo_path).strip()

        return table[team_key]

    for _, row in matches.iterrows():
        if pd.notna(row.get("home_team_name")):
            ensure_team(row.get("home_team_id"), row.get("home_team_name"), row.get("home_team_logo_path"))

        if pd.notna(row.get("away_team_name")):
            ensure_team(row.get("away_team_id"), row.get("away_team_name"), row.get("away_team_logo_path"))

    ordered_matches = matches.copy()
    ordered_matches["_form_source_order"] = range(
        len(ordered_matches)
    )

    if "kickoff_time_utc_dt" in ordered_matches.columns:
        ordered_matches["_form_kickoff"] = pd.to_datetime(
            ordered_matches["kickoff_time_utc_dt"],
            utc=True,
            errors="coerce"
        )
    elif "kickoff_time_utc" in ordered_matches.columns:
        ordered_matches["_form_kickoff"] = pd.to_datetime(
            ordered_matches["kickoff_time_utc"],
            utc=True,
            errors="coerce"
        )
    else:
        ordered_matches["_form_kickoff"] = pd.NaT

    ordered_matches = ordered_matches.sort_values(
        by=[
            "_form_kickoff",
            "_form_source_order"
        ],
        ascending=[True, True],
        na_position="last",
        kind="mergesort"
    )

    for _, row in ordered_matches.iterrows():
        if not to_bool(row.get("is_finished")):
            continue

        home_goals = to_optional_int(row.get("home_score_for_prediction"))
        away_goals = to_optional_int(row.get("away_score_for_prediction"))

        if home_goals is None or away_goals is None:
            continue

        home_team = ensure_team(row.get("home_team_id"), row.get("home_team_name"), row.get("home_team_logo_path"))
        away_team = ensure_team(row.get("away_team_id"), row.get("away_team_name"), row.get("away_team_logo_path"))

        home_team["Trận"] += 1
        away_team["Trận"] += 1
        home_team["Bàn thắng"] += home_goals
        home_team["Bàn thua"] += away_goals
        away_team["Bàn thắng"] += away_goals
        away_team["Bàn thua"] += home_goals

        if home_goals > away_goals:
            home_team["Thắng"] += 1
            away_team["Thua"] += 1
            home_team["Điểm"] += 3
            home_team["Phong độ"].append("W")
            away_team["Phong độ"].append("L")
        elif away_goals > home_goals:
            away_team["Thắng"] += 1
            home_team["Thua"] += 1
            away_team["Điểm"] += 3
            home_team["Phong độ"].append("L")
            away_team["Phong độ"].append("W")
        else:
            home_team["Hòa"] += 1
            away_team["Hòa"] += 1
            home_team["Điểm"] += 1
            away_team["Điểm"] += 1
            home_team["Phong độ"].append("D")
            away_team["Phong độ"].append("D")

    for team_stats in table.values():
        team_stats["Phong độ"] = (
            team_stats["Phong độ"][-5:]
        )

    standings = pd.DataFrame(table.values())

    if standings.empty:
        return pd.DataFrame(columns=columns)

    standings["Hiệu số"] = standings["Bàn thắng"] - standings["Bàn thua"]

    finished_count = int(matches["is_finished"].apply(to_bool).sum())
    
    if finished_count == 0:
        standings = standings.sort_values(
            ["Đội bóng"],
            ascending=[True]
        ).reset_index(drop=True)
    else:
        standings = standings.sort_values(
            ["Điểm", "Hiệu số", "Bàn thắng", "Đội bóng"],
            ascending=[False, False, False, True]
        ).reset_index(drop=True)

    return standings[columns]

def render_page_native_sticky_table(
    table_html: str,
    root_id: str,
    mobile_frozen_columns: tuple[str, ...] = ()
):
    """
    Render bảng trực tiếp vào trang Streamlit:

    - Không dùng iframe.
    - Không tạo cuộn dọc riêng.
    - Header bám theo trang chính.
    - Header đồng bộ khi vuốt ngang trên mobile.
    - Có thể tạo lớp giao điểm riêng cho các cột freeze trên mobile.
    """
    safe_root_id = json.dumps(str(root_id))
    safe_mobile_frozen_columns = json.dumps(
        [
            str(column_key)
            for column_key
            in mobile_frozen_columns
        ]
    )

    sticky_script = """
    <script>
    (() => {
        const rootId = __ROOT_ID__;
        const mobileFrozenColumns =
            __MOBILE_FROZEN_COLUMNS__;

        const root = document.getElementById(rootId);

        if (!root) {
            return;
        }

        const tableScroller =
            root.querySelector(
                "[data-page-table-scroll]"
            ) || root;

        const sourceTable =
            root.querySelector("table");

        const sourceHead =
            sourceTable
                ? sourceTable.tHead
                : null;

        if (!sourceTable || !sourceHead) {
            return;
        }

        const overlayId =
            rootId + "__sticky_header";

        const oldOverlay =
            document.getElementById(overlayId);

        if (oldOverlay) {
            oldOverlay.remove();
        }

        const overlay =
            document.createElement("div");

        overlay.id = overlayId;

        overlay.setAttribute(
            "aria-hidden",
            "true"
        );

        Object.assign(
            overlay.style,
            {
                position: "fixed",
                display: "none",
                overflow: "hidden",
                pointerEvents: "none",
                background: "transparent",
                zIndex: "999"
            }
        );

        const overlayTable =
            sourceTable.cloneNode(false);

        overlayTable.removeAttribute("id");

        const overlayHead =
            sourceHead.cloneNode(true);

        overlayTable.appendChild(overlayHead);
        overlay.appendChild(overlayTable);

        /*
         * Lớp header riêng cho phần giao nhau giữa:
         * - header đang freeze theo chiều dọc;
         * - các cột đang freeze theo chiều ngang.
         *
         * Không dựa vào position: sticky bên trong bảng đã transform,
         * vì Safari/Chrome mobile có thể tính sai left khi vuốt ngang.
         */
        const frozenOverlayTable =
            sourceTable.cloneNode(false);

        frozenOverlayTable.removeAttribute(
            "id"
        );

        const frozenOverlayHead =
            document.createElement("thead");

        const frozenOverlayRow =
            document.createElement("tr");

        frozenOverlayHead.appendChild(
            frozenOverlayRow
        );

        frozenOverlayTable.appendChild(
            frozenOverlayHead
        );

        overlay.appendChild(
            frozenOverlayTable
        );

        document.body.appendChild(overlay);

        Object.assign(
            overlayTable.style,
            {
                margin: "0",
                tableLayout: "fixed",
                transformOrigin: "left top"
            }
        );

        Object.assign(
            frozenOverlayTable.style,
            {
                position: "absolute",
                display: "none",
                top: "0",
                left: "0",
                margin: "0",
                tableLayout: "fixed",
                transform: "none",
                zIndex: "3"
            }
        );

        const mobileQuery =
            window.matchMedia(
                "(max-width: 768px)"
            );

        const findVerticalScrollParent = (
            node
        ) => {
            let parent = node.parentElement;

            while (
                parent
                && parent !== document.body
            ) {
                const overflowY =
                    window.getComputedStyle(
                        parent
                    ).overflowY;

                if (
                    /auto|scroll|overlay/.test(
                        overflowY
                    )
                ) {
                    return parent;
                }

                parent = parent.parentElement;
            }

            return window;
        };

        const pageScrollTarget =
            findVerticalScrollParent(root);

        let animationFrame = 0;
        let cleaned = false;
        let mutationObserver = null;
        let resizeObserver = null;
        let overlayOrderSignature = "";

        const syncColumnWidths = () => {
            const sourceCells =
                Array.from(
                sourceHead.rows[0]?.cells || []
            );

            const currentOrderSignature =
                sourceCells
                    .map(
                        (cell) =>
                            cell.dataset.col || ""
                    )
                    .join("|");

            if (
                currentOrderSignature
                !== overlayOrderSignature
            ) {
                overlayHead.replaceChildren(
                    ...Array.from(
                        sourceHead.rows
                    ).map(
                        (sourceRow) =>
                            sourceRow.cloneNode(true)
                    )
                );

                frozenOverlayRow
                    .replaceChildren();

                mobileFrozenColumns
                    .forEach(
                        (columnKey) => {
                            const sourceCell =
                                sourceCells.find(
                                    (cell) =>
                                        cell.dataset.col
                                        === columnKey
                                );

                            if (!sourceCell) {
                                return;
                            }

                            frozenOverlayRow
                                .appendChild(
                                    sourceCell
                                        .cloneNode(true)
                                );
                        }
                    );

                overlayOrderSignature =
                    currentOrderSignature;
            }

            const overlayCells =
                Array.from(
                overlayHead.rows[0]?.cells || []
            );

            sourceCells.forEach(
                (sourceCell, index) => {
                    const overlayCell =
                        overlayCells[index];

                    if (!overlayCell) {
                        return;
                    }

                    const width =
                        sourceCell
                            .getBoundingClientRect()
                            .width;

                    Object.assign(
                        overlayCell.style,
                        {
                            width: width + "px",
                            minWidth: width + "px",
                            maxWidth: width + "px",
                            boxSizing: "border-box",
                            position: "static",
                            left: "auto",
                            right: "auto",
                            zIndex: "1",
                            boxShadow: "none"
                        }
                    );
                }
            );

            const tableWidth =
                sourceTable
                    .getBoundingClientRect()
                    .width;

            overlayTable.style.width =
                tableWidth + "px";

            overlayTable.style.minWidth =
                tableWidth + "px";

            overlayTable.style.maxWidth =
                tableWidth + "px";

            const sourceCellsByColumn =
                new Map(
                    sourceCells.map(
                        (cell) => [
                            cell.dataset.col,
                            cell
                        ]
                    )
                );

            const frozenCells =
                Array.from(
                    frozenOverlayRow.cells || []
                );

            let frozenWidth = 0;

            frozenCells.forEach(
                (frozenCell, index) => {
                    const columnKey =
                        mobileFrozenColumns[index];

                    const sourceCell =
                        sourceCellsByColumn.get(
                            columnKey
                        );

                    if (!sourceCell) {
                        return;
                    }

                    const width =
                        sourceCell
                            .getBoundingClientRect()
                            .width;

                    frozenWidth += width;

                    Object.assign(
                        frozenCell.style,
                        {
                            width: width + "px",
                            minWidth: width + "px",
                            maxWidth: width + "px",
                            boxSizing: "border-box",
                            position: "static",
                            left: "auto",
                            right: "auto",
                            zIndex: "4"
                        }
                    );
                }
            );

            frozenOverlayTable.style.width =
                frozenWidth + "px";

            frozenOverlayTable.style.minWidth =
                frozenWidth + "px";

            frozenOverlayTable.style.maxWidth =
                frozenWidth + "px";
        };

        const cleanup = () => {
            if (cleaned) {
                return;
            }

            cleaned = true;

            cancelAnimationFrame(
                animationFrame
            );

            pageScrollTarget
                .removeEventListener(
                    "scroll",
                    schedule
                );

            tableScroller
                .removeEventListener(
                    "scroll",
                    schedule
                );

            window.removeEventListener(
                "resize",
                schedule
            );

            if (mutationObserver) {
                mutationObserver.disconnect();
            }

            if (resizeObserver) {
                resizeObserver.disconnect();
            }

            overlay.remove();
        };

        const update = () => {
            if (!root.isConnected) {
                cleanup();
                return;
            }

            const rootRect =
                root.getBoundingClientRect();

            const sourceHeadRect =
                sourceHead
                    .getBoundingClientRect();

            const appHeader =
                document.querySelector(
                    '[data-testid="stHeader"]'
                );

            const stickyTop = Math.max(
                0,
                appHeader
                    ? appHeader
                        .getBoundingClientRect()
                        .bottom
                    : 0
            );

            const headerHeight =
                sourceHeadRect.height;

            const shouldShow = (
                sourceHeadRect.top <= stickyTop
                && rootRect.bottom
                    > stickyTop + headerHeight
            );

            if (!shouldShow) {
                overlay.style.display = "none";
                return;
            }

            syncColumnWidths();

            const scrollerRect =
                tableScroller
                    .getBoundingClientRect();

            Object.assign(
                overlay.style,
                {
                    display: "block",
                    top: stickyTop + "px",
                    left: scrollerRect.left + "px",
                    width: scrollerRect.width + "px",
                    height: headerHeight + "px"
                }
            );

            overlayTable.style.transform =
                "translate3d("
                + (-tableScroller.scrollLeft)
                + "px, 0, 0)";

            const showFrozenIntersection = (
                mobileQuery.matches
                && mobileFrozenColumns.length > 0
                && frozenOverlayRow.cells.length > 0
            );

            frozenOverlayTable.style.display =
                showFrozenIntersection
                    ? "table"
                    : "none";

            frozenOverlayTable.style.height =
                headerHeight + "px";
        };

        function schedule() {
            cancelAnimationFrame(
                animationFrame
            );

            animationFrame =
                requestAnimationFrame(update);
        }

        pageScrollTarget.addEventListener(
            "scroll",
            schedule,
            { passive: true }
        );

        tableScroller.addEventListener(
            "scroll",
            schedule,
            { passive: true }
        );

        window.addEventListener(
            "resize",
            schedule,
            { passive: true }
        );

        mutationObserver =
            new MutationObserver(() => {
                if (!root.isConnected) {
                    cleanup();
                }
            });

        mutationObserver.observe(
            document.body,
            {
                childList: true,
                subtree: true
            }
        );

        if ("ResizeObserver" in window) {
            resizeObserver =
                new ResizeObserver(schedule);

            resizeObserver.observe(root);
            resizeObserver.observe(sourceTable);
        }

        schedule();
    })();
    </script>
    """.replace(
        "__ROOT_ID__",
        safe_root_id
    ).replace(
        "__MOBILE_FROZEN_COLUMNS__",
        safe_mobile_frozen_columns
    )

    st.html(
        table_html + sticky_script,
        unsafe_allow_javascript=True
    )

def render_epl_standings_table(standings_df: pd.DataFrame):
    if standings_df.empty:
        return

    stat_columns = ["Trận", "Thắng", "Hòa", "Thua", "Bàn thắng", "Bàn thua", "Hiệu số", "Điểm"]
    column_keys = {
        "Trận": "played",
        "Thắng": "wins",
        "Hòa": "draws",
        "Thua": "losses",
        "Bàn thắng": "gf",
        "Bàn thua": "ga",
        "Hiệu số": "gd",
        "Điểm": "points"
    }
    rows_html = []

    for index, row in standings_df.reset_index(drop=True).iterrows():
        rank = index + 1
        raw_team_name = str(
            row.get("Đội bóng", "")
        ).strip()
        team_name = html.escape(raw_team_name)
        mobile_team_name = html.escape(
            get_mobile_team_display_name(
                raw_team_name
            )
        )
        logo_path = str(row.get("Logo", "") or "").strip()
        logo_src = resolve_asset_src(logo_path) if logo_path else ""

        if logo_src:
            logo_html = f'<img class="epl-team-logo" src="{html.escape(logo_src, quote=True)}" alt="{team_name}">'
        else:
            logo_html = ""

        cells_html = []

        for col in stat_columns:
            value = to_optional_int(row.get(col)) or 0

            if col == "Hiệu số":
                display_value = f"+{value}" if value > 0 else str(value)
                value_class = "positive" if value > 0 else "negative" if value < 0 else ""
            else:
                display_value = str(value)
                value_class = ""

            if col == "Điểm":
                value_class = f"{value_class} points-cell".strip()

            cells_html.append(
                f'<td data-col="{column_keys[col]}" '
                f'class="{value_class}">'
                f'{html.escape(display_value)}'
                f'</td>'
            )

        raw_form = row.get("Phong độ", [])

        if isinstance(raw_form, (list, tuple)):
            form_results = [
                str(result).strip().upper()
                for result in raw_form
                if str(result).strip().upper()
                in {"W", "D", "L"}
            ][-5:]
        else:
            form_results = []

        form_labels = {
            "W": "Thắng",
            "D": "Hòa",
            "L": "Thua"
        }
        form_symbol_html = (
            '<span class="form-result-icon" '
            'aria-hidden="true"></span>'
        )
        form_classes = {
            "W": "form-win",
            "D": "form-draw",
            "L": "form-loss"
        }

        if form_results:
            form_items_html = "".join(
                (
                    '<span '
                    f'class="form-result {form_classes[result]}" '
                    'role="listitem" '
                    f'title="{form_labels[result]}" '
                    f'aria-label="{form_labels[result]}">'
                    f'{form_symbol_html}'
                    '</span>'
                )
                for result in form_results
            )

            form_summary = ", ".join(
                form_labels[result]
                for result in form_results
            )

            form_html = (
                '<div class="form-sequence" '
                'role="list" '
                f'aria-label="Phong độ gần nhất: '
                f'{html.escape(form_summary, quote=True)}">'
                f'{form_items_html}'
                '</div>'
            )
        else:
            form_html = (
                '<span class="form-empty" '
                'aria-label="Chưa có dữ liệu phong độ">'
                '&mdash;'
                '</span>'
            )

        rows_html.append(
            f"""
            <tr>
                <td data-col="rank" class="rank-cell">
                    {rank}
                </td>
                
                <td data-col="team" class="team-cell">
                    <div class="team-wrap">
                        {logo_html}
                        <span class="epl-team-name-desktop">
                            {team_name}
                        </span>
                        <span class="epl-team-name-mobile">
                            {mobile_team_name}
                        </span>
                    </div>
                </td>
                {''.join(cells_html)}
                <td data-col="form" class="form-cell">
                    {form_html}
                </td>
            </tr>
            """
        )

    standings_html = f"""
    <style>
    .epl-standings-box {{
        margin-top: 0;
        border-radius: 18px;
        overflow: hidden;
        border: 1px solid rgba(15, 23, 42, 0.08);
        background: #FFFFFF;
        box-shadow: 0 18px 45px rgba(15, 23, 42, 0.10);
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .epl-standings-scroll {{
        overflow-x: auto;
        width: 100%;
    }}
    .epl-standings-table {{
        width: 100%;
        min-width: 1040px;
        border-collapse: collapse;
        font-size: 14px;
        color: #0F172A;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .epl-standings-table th {{
        background: linear-gradient(135deg, #07111F, #14213A);
        color: #F8FAFC;
        padding: 14px 12px;
        font-size: 12px;
        font-weight: 900;
        text-align: center;
        white-space: nowrap;
    }}
    .epl-standings-table th[data-col="team"] {{
        text-align: left;
    }}
    .epl-standings-table td {{
        padding: 13px 12px;
        border-bottom: 1px solid rgba(15, 23, 42, 0.08);
        text-align: center;
        background: rgba(255, 255, 255, 0.94);
    }}
    .epl-standings-table tr:hover td {{
        background: #EAF6FF;
    }}
    .rank-cell {{
        width: 64px;
        font-weight: 900;
        color: #334155;
    }}
    .team-cell {{
        text-align: left !important;
        min-width: 260px;
        font-weight: 850;
    }}
    .team-wrap {{
        display: flex;
        align-items: center;
        gap: 11px;
    }}
    .epl-team-name-mobile {{
        display: none;
    }}
    html.epl-mobile-team-names
    .epl-team-name-desktop {{
        display: none;
    }}
    html.epl-mobile-team-names
    .epl-team-name-mobile {{
        display: inline;
    }}
    .epl-team-logo {{
        width: 30px;
        height: 30px;
        flex: 0 0 30px;
        object-fit: contain;
        display: block;
        border: 0;
        border-radius: 0;
        background: transparent;
        box-shadow: none;
    }}
    .points-cell {{
        font-weight: 950;
        color: #07111F;
        background: rgba(245, 197, 66, 0.22) !important;
    }}
    .epl-standings-table th[data-col="form"] {{
        width: 150px;
        min-width: 150px;
    }}
    .form-cell {{
        width: 150px;
        min-width: 150px;
        padding-left: 14px !important;
        padding-right: 14px !important;
    }}
    .form-sequence {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        min-width: 118px;
        white-space: nowrap;
        vertical-align: middle;
    }}
    .form-result {{
        --form-color: #94A3B8;
        display: inline-grid;
        width: 19px;
        height: 19px;
        flex: 0 0 19px;
        place-items: center;
        box-sizing: border-box;
        border-radius: 50%;
        background: var(--form-color);
        color: #FFFFFF;
        font-size: 0;
        line-height: 0;
    }}
    .form-result-icon {{
        position: relative;
        display: block;
        width: 12px;
        height: 12px;
        flex: 0 0 12px;
        margin: 0;
        padding: 0;
        overflow: hidden;
        color: #FFFFFF;
    }}
    .form-result-icon::before,
    .form-result-icon::after {{
        content: "";
        position: absolute;
        display: block;
        box-sizing: border-box;
        background: currentColor;
        transform-origin: center;
    }}
    .form-win .form-result-icon::before {{
        left: 5%;
        top: 58%;
        width: 42%;
        height: 18%;
        transform: rotate(45deg);
    }}
    .form-win .form-result-icon::after {{
        left: 30%;
        top: 44%;
        width: 72%;
        height: 18%;
        transform: rotate(-45deg);
    }}
    .form-draw .form-result-icon::before {{
        left: 12%;
        top: 41%;
        width: 76%;
        height: 18%;
    }}
    .form-draw .form-result-icon::after {{
        display: none;
    }}
    .form-loss .form-result-icon::before,
    .form-loss .form-result-icon::after {{
        left: 7.5%;
        top: 41%;
        width: 85%;
        height: 18%;
    }}
    .form-loss .form-result-icon::before {{
        transform: rotate(45deg);
    }}
    .form-loss .form-result-icon::after {{
        transform: rotate(-45deg);
    }}
    .form-result:last-child {{
        box-shadow:
            0 0 0 2px #FFFFFF,
            0 0 0 3px var(--form-color);
    }}
    .form-win {{
        --form-color: #2FA663;
    }}
    .form-draw {{
        --form-color: #9CA3AF;
    }}
    .form-loss {{
        --form-color: #EF4444;
    }}
    .form-empty {{
        color: #94A3B8;
        font-size: 17px;
        font-weight: 700;
    }}
    .positive {{
        color: #047857;
        font-weight: 400;
    }}
    .negative {{
        color: #B91C1C;
        font-weight: 400;
    }}
    @media (max-width: 768px) {{
        .epl-standings-box {{
            margin-top:
                0;
    
            border-radius:
                13px;
        }}
    
        .epl-standings-scroll {{
            width:
                100%;
    
            overflow-x:
                auto;
    
            overflow-y:
                hidden;
    
            -webkit-overflow-scrolling:
                touch;
    
            overscroll-behavior-x:
                contain;
    
            touch-action:
                pan-x pan-y;
        }}
    
        /*
         * Tổng chiều rộng bảng khoảng 482–496px.
         *
         * Năm cột đầu chiếm khoảng 274–288px,
         * vừa phần hiển thị của màn hình mobile.
         */
        .epl-standings-table {{
            --rank-width:
                36px;
    
            --team-width:
                clamp(108px, 32vw, 122px);
    
            --points-width:
                46px;
    
            --gd-width:
                44px;
    
            --small-width:
                40px;
    
            --goal-width:
                44px;

            --form-width:
                128px;
    
            width:
                calc(
                    var(--team-width) + 502px
                );
    
            min-width:
                calc(
                    var(--team-width) + 502px
                );
    
            table-layout:
                fixed;
    
            border-collapse:
                separate;
    
            border-spacing:
                0;
    
            font-size:
                11.5px;
        }}
    
        .epl-standings-table th {{
            height:
                38px;
    
            padding:
                7px 3px;
    
            box-sizing:
                border-box;
    
            font-size:
                10px;
    
            line-height:
                1;
    
            text-align:
                center;
        }}
    
        .epl-standings-table td {{
            height:
                52px;
    
            padding:
                7px 3px;
    
            box-sizing:
                border-box;
    
            font-size:
                11.5px;
    
            vertical-align:
                middle;
        }}
    
        /* =========================
           CHIỀU RỘNG TỪNG CỘT
           ========================= */
    
        .epl-standings-table
        [data-col="rank"] {{
            width:
                var(--rank-width) !important;
    
            min-width:
                var(--rank-width) !important;
    
            max-width:
                var(--rank-width) !important;
        }}
    
        .epl-standings-table
        [data-col="team"] {{
            width:
                var(--team-width) !important;
    
            min-width:
                var(--team-width) !important;
    
            max-width:
                var(--team-width) !important;
        }}
    
        .epl-standings-table
        [data-col="points"] {{
            width:
                var(--points-width) !important;
    
            min-width:
                var(--points-width) !important;
    
            max-width:
                var(--points-width) !important;
        }}
    
        .epl-standings-table
        [data-col="gd"] {{
            width:
                var(--gd-width) !important;
    
            min-width:
                var(--gd-width) !important;
    
            max-width:
                var(--gd-width) !important;
        }}
    
        .epl-standings-table
        [data-col="played"],
    
        .epl-standings-table
        [data-col="wins"],
    
        .epl-standings-table
        [data-col="draws"],
    
        .epl-standings-table
        [data-col="losses"] {{
            width:
                var(--small-width) !important;
    
            min-width:
                var(--small-width) !important;
    
            max-width:
                var(--small-width) !important;
        }}
    
        .epl-standings-table
        [data-col="gf"],
    
        .epl-standings-table
        [data-col="ga"] {{
            width:
                var(--goal-width) !important;
    
            min-width:
                var(--goal-width) !important;
    
            max-width:
                var(--goal-width) !important;
        }}

        .epl-standings-table
        [data-col="form"] {{
            width:
                var(--form-width) !important;

            min-width:
                var(--form-width) !important;

            max-width:
                var(--form-width) !important;
        }}

        .epl-standings-table
        .form-cell {{
            padding:
                7px 6px !important;
        }}

        .epl-standings-table
        .form-sequence {{
            min-width:
                108px;

            gap:
                5px;
        }}

        .epl-standings-table
        .form-result {{
            width:
                17px;

            height:
                17px;

            flex-basis:
                17px;

            font-size:
                0;
        }}

        .epl-standings-table
        .form-result-icon {{
            width:
                10.5px;

            height:
                10.5px;
        }}
    
        /* =========================
           CỘT ĐỘI BÓNG
           ========================= */
    
        .epl-standings-table
        .team-cell {{
            padding:
                6px 5px !important;
    
            overflow:
                hidden;
    
            text-align:
                left !important;
        }}
    
        .epl-standings-table
        .team-wrap {{
            display:
                flex;
    
            width:
                100%;
    
            min-width:
                0;
    
            align-items:
                center;
    
            gap:
                6px;
        }}
    
        .epl-standings-table
        .team-wrap
        .epl-team-name-mobile {{
            display:
                block;
    
            min-width:
                0;
    
            flex:
                1 1 auto;
    
            overflow:
                hidden;
    
            text-overflow:
                ellipsis;
    
            white-space:
                nowrap;
        }}
    
        .epl-standings-table
        .epl-team-logo {{
            width:
                24px;
    
            height:
                24px;
    
            flex:
                0 0 24px;
        }}
    
        /* =========================
           FREEZE #, ĐỘI VÀ PTS
           ========================= */
    
        .epl-standings-table
        [data-col="rank"],
    
        .epl-standings-table
        [data-col="team"],
    
        .epl-standings-table
        [data-col="points"] {{
            position:
                sticky;
        }}
    
        .epl-standings-table
        [data-col="rank"] {{
            left:
                0;
        }}
    
        .epl-standings-table
        [data-col="team"] {{
            left:
                var(--rank-width);
        }}
    
        .epl-standings-table
        [data-col="points"] {{
            left:
                calc(
                    var(--rank-width) +
                    var(--team-width)
                );
        }}
    
        /* Header của ba cột được freeze */
        .epl-standings-table th[data-col="rank"],
        .epl-standings-table th[data-col="team"],
        .epl-standings-table th[data-col="points"] {{
            z-index:
                5;
    
            background:
                linear-gradient(
                    135deg,
                    #07111F,
                    #14213A
                );
        }}
    
        /* Nội dung của ba cột được freeze */
        .epl-standings-table td[data-col="rank"],
        .epl-standings-table td[data-col="team"] {{
            z-index:
                3;
    
            background:
                #FFFFFF;
        }}
    
        .epl-standings-table td[data-col="points"] {{
            z-index:
                4;
    
            background:
                #FFF8D9 !important;
        }}
    
        /*
         * Đường phân cách nhẹ sau PTS,
         * giúp nhận biết vùng đang được freeze.
         */
        .epl-standings-table
        [data-col="points"] {{
            box-shadow:
                7px 0 10px -9px
                rgba(15, 23, 42, 0.65);
        }}
    
        .epl-standings-table
        .rank-cell {{
            font-size:
                11px;
    
            text-align:
                center;
        }}
    
        .epl-standings-table
        .points-cell {{
            color:
                #07111F;
    
            font-size:
                12.5px;
    
            font-weight:
                950;
        }}
    }}
    </style>

    <div
        id="epl-standings-table-root"
        class="epl-standings-box"
    >
        <div
            class="epl-standings-scroll"
            data-page-table-scroll
        >
            <table class="epl-standings-table">
                <thead>
                    <tr>
                        <th data-col="rank" title="Hạng">#</th>
                        <th data-col="team" title="Đội bóng">Đội</th>
                        <th data-col="played" title="Trận">P</th>
                        <th data-col="wins" title="Thắng">W</th>
                        <th data-col="draws" title="Hòa">D</th>
                        <th data-col="losses" title="Thua">L</th>
                        <th data-col="gf" title="Bàn thắng">GF</th>
                        <th data-col="ga" title="Bàn thua">GA</th>
                        <th data-col="gd" title="Hiệu số">GD</th>
                        <th data-col="points" title="Điểm">PTS</th>
                        <th data-col="form" title="Phong độ 5 trận gần nhất">FORM</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows_html)}
                </tbody>
            </table>
        </div>
    </div>

    <script>
    (() => {{
        const parentWindow =
            window.parent;
    
        const mobileQuery =
            parentWindow.matchMedia(
                "(max-width: 768px)"
            );
    
        const desktopColumnOrder = [
            "rank",
            "team",
            "played",
            "wins",
            "draws",
            "losses",
            "gf",
            "ga",
            "gd",
            "points",
            "form"
        ];
    
        const mobileColumnOrder = [
            "rank",
            "team",
            "points",
            "gd",
            "played",
            "wins",
            "draws",
            "losses",
            "gf",
            "ga",
            "form"
        ];
    
        const reorderColumns = (
            columnOrder
        ) => {{
            document
                .querySelectorAll(
                    ".epl-standings-table tr"
                )
                .forEach((row) => {{
                    const cellsByColumn =
                        new Map(
                            Array.from(
                                row.children
                            ).map((cell) => [
                                cell.dataset.col,
                                cell
                            ])
                        );
    
                    columnOrder.forEach(
                        (columnKey) => {{
                            const cell =
                                cellsByColumn.get(
                                    columnKey
                                );
    
                            if (cell) {{
                                row.appendChild(
                                    cell
                                );
                            }}
                        }}
                    );
                }});
        }};
    
        const applyStandingsMode = () => {{
            const isMobile =
                mobileQuery.matches;
    
            document.documentElement
                .classList.toggle(
                    "epl-mobile-team-names",
                    isMobile
                );
    
            reorderColumns(
                isMobile
                    ? mobileColumnOrder
                    : desktopColumnOrder
            );
        }};
    
        applyStandingsMode();
    
        mobileQuery.addEventListener(
            "change",
            applyStandingsMode
        );
    
        window.addEventListener(
            "unload",
            () => {{
                mobileQuery.removeEventListener(
                    "change",
                    applyStandingsMode
                );
            }}
        );
    }})();
    </script>
    """

    render_page_native_sticky_table(
        standings_html,
        "epl-standings-table-root",
        mobile_frozen_columns=(
            "rank",
            "team",
            "points"
        )
    )

def render_competition_stats_view_switcher() -> str:
    """
    Nút chuyển giữa:
    - Bảng xếp hạng câu lạc bộ
    - Bảng Vua phá lưới
    """
    valid_views = {
        "standings",
        "top_scorers"
    }

    active_view = st.session_state.get(
        "competition_stats_view",
        "standings"
    )

    if active_view not in valid_views:
        active_view = "standings"
        st.session_state[
            "competition_stats_view"
        ] = active_view

    st.markdown(
        """
        <style>
        div[class*="st-key-competition_stats_tabs"] {
            width: min(450px, 100%) !important;
            margin: 0 0 20px 0 !important;
            padding: 5px !important;

            border:
                1px solid rgba(72, 24, 120, 0.16)
                !important;

            border-radius: 14px !important;

            background:
                rgba(255, 255, 255, 0.88)
                !important;

            box-shadow:
                0 10px 28px rgba(37, 15, 62, 0.07),
                inset 0 1px 0 rgba(255, 255, 255, 0.92)
                !important;

            backdrop-filter: blur(10px);
        }

        div[class*="st-key-competition_stats_tabs"]
        div[data-testid="stHorizontalBlock"] {
            gap: 5px !important;
        }

        div[class*="st-key-competition_stats_tabs"]
        div[data-testid="stColumn"] {
            min-width: 0 !important;
            padding: 0 !important;
        }

        div[class*="st-key-competition_stats_tabs"]
        div[class*="st-key-competition_stats_tab_"] {
            width: 100% !important;
            margin: 0 !important;
        }

        div[class*="st-key-competition_stats_tabs"]
        div[class*="st-key-competition_stats_tab_"]
        button {
            position: relative !important;

            width: 100% !important;
            min-height: 42px !important;

            padding:
                0 15px !important;

            border:
                1px solid transparent !important;

            border-radius:
                10px !important;

            background:
                transparent !important;

            color:
                #5D5268 !important;

            box-shadow:
                none !important;

            font-size:
                13.5px !important;

            font-weight:
                850 !important;

            line-height:
                1 !important;

            opacity:
                1 !important;

            transform:
                none !important;

            transition:
                background 0.16s ease,
                color 0.16s ease,
                box-shadow 0.16s ease
                !important;
        }

        /* Nút chưa được chọn */
        div[class*="st-key-competition_stats_tabs"]
        div[class*="st-key-competition_stats_tab_"]
        button:not(:disabled):hover {
            border-color:
                rgba(72, 24, 120, 0.12)
                !important;

            background:
                rgba(72, 24, 120, 0.055)
                !important;

            color:
                #301060 !important;

            transform:
                none !important;
        }

        /* Nút đang được chọn */
        div[class*="st-key-competition_stats_tabs"]
        div[class*="st-key-competition_stats_tab_"]
        button:disabled {
            border-color:
                #3A0F70 !important;

            background:
                linear-gradient(
                    135deg,
                    #301060 0%,
                    #4B148C 100%
                )
                !important;

            color:
                #FFFFFF !important;

            box-shadow:
                0 7px 18px rgba(56, 15, 105, 0.20),
                inset 0 1px 0 rgba(255, 255, 255, 0.14)
                !important;

            cursor:
                default !important;

            opacity:
                1 !important;
        }

        div[class*="st-key-competition_stats_tabs"]
        div[class*="st-key-competition_stats_tab_"]
        button:disabled * {
            color:
                #FFFFFF !important;

            opacity:
                1 !important;
        }

        /* Vạch vàng tinh tế ở tab đang chọn */
        div[class*="st-key-competition_stats_tabs"]
        div[class*="st-key-competition_stats_tab_"]
        button:disabled::after {
            content: "";

            position: absolute;
            left: 34%;
            right: 34%;
            bottom: 0;

            height: 2px;

            border-radius:
                2px 2px 0 0;

            background:
                #F5C542;

            box-shadow:
                0 -1px 5px
                rgba(245, 197, 66, 0.28);
        }

        @media (max-width: 768px) {
            div[class*="st-key-competition_stats_tabs"] {
                width:
                    100% !important;

                margin-bottom:
                    16px !important;

                border-radius:
                    13px !important;
            }

            div[class*="st-key-competition_stats_tabs"]
            div[class*="st-key-competition_stats_tab_"]
            button {
                min-height:
                    40px !important;

                padding:
                    0 10px !important;

                font-size:
                    12.5px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    with st.container(
        key="competition_stats_tabs"
    ):
        standings_col, scorers_col = st.columns(2)

        with standings_col:
            if st.button(
                "Bảng xếp hạng",
                key="competition_stats_tab_standings",
                use_container_width=True,
                disabled=active_view == "standings"
            ):
                st.session_state[
                    "competition_stats_view"
                ] = "standings"

                st.rerun()

        with scorers_col:
            if st.button(
                "Vua phá lưới",
                key="competition_stats_tab_top_scorers",
                use_container_width=True,
                disabled=active_view == "top_scorers"
            ):
                st.session_state[
                    "competition_stats_view"
                ] = "top_scorers"

                st.rerun()

    return active_view

def build_epl_season_clubs_df(
    matches: pd.DataFrame
) -> pd.DataFrame:
    """
    Lấy các CLB xuất hiện trong lịch thi đấu của mùa.

    Không lấy từ match_goals vì một CLB chưa ghi bàn
    vẫn phải xuất hiện trong bộ lọc.
    """
    columns = [
        "team_id",
        "club_name",
        "club_logo"
    ]

    if matches.empty:
        return pd.DataFrame(columns=columns)

    clubs = {}

    for _, row in matches.iterrows():
        for side in ["home", "away"]:
            team_id = to_optional_int(
                row.get(f"{side}_team_id")
            )

            raw_name = row.get(
                f"{side}_team_name"
            )

            if (
                team_id is None
                or raw_name is None
                or pd.isna(raw_name)
            ):
                continue

            club_name = str(raw_name).strip()

            if (
                not club_name
                or is_unknown_team(club_name)
            ):
                continue

            raw_logo = row.get(
                f"{side}_team_logo_path"
            )

            if (
                raw_logo is None
                or pd.isna(raw_logo)
            ):
                club_logo = ""
            else:
                club_logo = str(raw_logo).strip()

            if team_id not in clubs:
                clubs[team_id] = {
                    "team_id": team_id,
                    "club_name": club_name,
                    "club_logo": club_logo
                }

            elif (
                not clubs[team_id]["club_logo"]
                and club_logo
            ):
                clubs[team_id][
                    "club_logo"
                ] = club_logo

    clubs_df = pd.DataFrame(
        clubs.values(),
        columns=columns
    )

    if clubs_df.empty:
        return clubs_df

    clubs_df["_sort_name"] = (
        clubs_df["club_name"]
        .astype(str)
        .str.casefold()
    )

    clubs_df = (
        clubs_df
        .sort_values("_sort_name")
        .drop(columns="_sort_name")
        .reset_index(drop=True)
    )

    return clubs_df

def render_epl_top_scorers_club_filter(
    clubs_df: pd.DataFrame,
    season_slug: str
) -> dict:
    """
    Hiển thị bộ lọc CLB dạng popover.

    Giá trị mặc định của mỗi mùa là Tất cả.
    """
    clubs = []

    for _, row in clubs_df.iterrows():
        team_id = to_optional_int(
            row.get("team_id")
        )

        if team_id is None:
            continue

        club_name = str(
            row.get("club_name", "")
        ).strip()

        raw_logo = row.get(
            "club_logo",
            ""
        )

        if (
            raw_logo is None
            or pd.isna(raw_logo)
        ):
            club_logo = ""
        else:
            club_logo = str(raw_logo).strip()

        clubs.append(
            {
                "team_id": team_id,
                "club_name": club_name,
                "club_logo": club_logo
            }
        )

    clubs.sort(
        key=lambda club: club[
            "club_name"
        ].casefold()
    )

    season_key = season_slug.replace(
        "-",
        "_"
    )

    state_key = (
        f"top_scorers_club_filter_{season_key}"
    )

    raw_selected_id = (
        st.session_state.get(
            state_key,
            "all"
        )
    )

    if raw_selected_id == "all":
        selected_id = None
    else:
        selected_id = to_optional_int(
            raw_selected_id
        )

    valid_team_ids = {
        club["team_id"]
        for club in clubs
    }

    if (
        selected_id is not None
        and selected_id not in valid_team_ids
    ):
        selected_id = None
        st.session_state[state_key] = "all"

    selected_club = {
        "team_id": None,
        "club_name": "Toàn giải",
        "club_logo": "data/static/epl.png"
    }

    if selected_id is not None:
        selected_club = next(
            (
                club
                for club in clubs
                if club["team_id"] == selected_id
            ),
            selected_club
        )

    def build_logo_html(
        club: dict,
        option_logo: bool = False
    ) -> str:
        club_name = str(
            club.get(
                "club_name",
                ""
            )
        ).strip()

        logo_path = str(
            club.get(
                "club_logo",
                ""
            )
            or ""
        ).strip()

        logo_src = (
            resolve_asset_src(logo_path)
            if logo_path
            else ""
        )

        class_name = (
            "epl-club-filter-option-logo"
            if option_logo
            else "epl-club-filter-current-logo"
        )

        if logo_src:
            return (
                f'<div class="{class_name}">'
                f'<img '
                f'src="{html.escape(logo_src, quote=True)}" '
                f'alt="{html.escape(club_name, quote=True)}">'
                f'</div>'
            )

        fallback = (
            "ALL"
            if club.get("team_id") is None
            else "".join(
                part[0]
                for part in club_name.split()
                if part
            )[:3].upper()
        )

        return (
            f'<div class="{class_name} '
            f'epl-club-filter-fallback">'
            f'{html.escape(fallback)}'
            f'</div>'
        )

    st.markdown(
        """
        <style>
        div[class*="st-key-epl_scorers_club_filter_"] {
            width: 100% !important;
            max-width: 300px !important;

            padding: 7px 9px !important;

            border:
                1px solid rgba(72, 24, 120, 0.16)
                !important;

            border-radius: 14px !important;

            background:
                rgba(255, 255, 255, 0.92)
                !important;

            box-shadow:
                0 10px 28px rgba(37, 15, 62, 0.08),
                inset 0 1px 0 rgba(255, 255, 255, 0.90)
                !important;
        }

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stHorizontalBlock"] {
            align-items: center !important;
            gap: 7px !important;
            min-height: 42px !important;
        }

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stColumn"] {
            padding: 0 !important;
            min-width: 0 !important;
        }

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stHorizontalBlock"]
        > div[data-testid="stColumn"]
        > div[data-testid="stVerticalBlock"] {
            height: 100% !important;
            justify-content: center !important;
        }

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stPopover"] {
            width: 100% !important;
        }

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stPopover"] > button,

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stPopover"] > div > button {
            width: 100% !important;
            min-height: 42px !important;

            justify-content:
                flex-start !important;

            padding:
                0 12px !important;

            border:
                0 !important;

            border-radius:
                10px !important;

            background:
                transparent !important;

            color:
                #301060 !important;

            box-shadow:
                none !important;

            font-size:
                13px !important;

            font-weight:
                850 !important;

            white-space:
                nowrap !important;

            overflow:
                hidden !important;

            text-overflow:
                ellipsis !important;

            text-align:
                left !important;
        }

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stPopover"] > button
        [data-testid="stMarkdownContainer"],

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stPopover"] > div > button
        [data-testid="stMarkdownContainer"] {
            width: 100% !important;
            min-width: 0 !important;
            text-align: left !important;
        }

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stPopover"] > button p,

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stPopover"] > div > button p {
            width: 100% !important;
            margin: 0 !important;
            overflow: hidden !important;
            text-align: left !important;
            text-overflow: ellipsis !important;
            white-space: nowrap !important;
        }

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stPopover"] > button svg:last-child,

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stPopover"] > div > button
        svg:last-child {
            flex: 0 0 auto !important;
            margin-left: auto !important;
        }

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stPopover"] > button:hover,

        div[class*="st-key-epl_scorers_club_filter_"]
        div[data-testid="stPopover"] > div > button:hover {
            background:
                rgba(72, 24, 120, 0.06)
                !important;
        }

        .epl-club-filter-current-logo,
        .epl-club-filter-option-logo {
            display: flex;

            align-items: center;
            justify-content: center;

            overflow: visible;
            background: transparent;
            border: 0;
            border-radius: 0;

            color:
                #3A0F70;

            font-weight:
                950;
        }

        .epl-club-filter-current-logo {
            width: 40px;
            height: 42px;
            margin: 0 auto;

            font-size:
                9px;
        }

        .epl-club-filter-option-logo {
            width: 31px;
            height: 39px;

            margin:
                0 auto;

            font-size:
                8px;
        }

        .epl-club-filter-current-logo img,
        .epl-club-filter-option-logo img {
            display: block;
            object-fit:
                contain;
        }

        .epl-club-filter-current-logo img {
            width: 34px;
            height: 34px;
        
            /* Đẩy riêng logo hiện tại lên trên */
            transform: translateY(-7px);
        }

        .epl-club-filter-option-logo img {
            width: 29px;
            height: 29px;
        }

        div[class*="st-key-epl_scorer_club_option_"]
        button {
            min-height:
                39px !important;

            justify-content:
                flex-start !important;

            padding:
                0 11px !important;

            border:
                1px solid transparent !important;

            border-radius:
                9px !important;

            background:
                transparent !important;

            color:
                #334155 !important;

            box-shadow:
                none !important;

            font-size:
                13px !important;

            font-weight:
                780 !important;
        }

        div[class*="st-key-epl_scorer_club_option_"]
        button:hover {
            border-color:
                rgba(72, 24, 120, 0.10)
                !important;

            background:
                rgba(72, 24, 120, 0.055)
                !important;

            color:
                #301060 !important;
        }

        div[class*="st-key-epl_scorer_club_option_"]
        button:disabled {
            border-color:
                rgba(72, 24, 120, 0.16)
                !important;

            background:
                rgba(72, 24, 120, 0.10)
                !important;

            color:
                #301060 !important;

            opacity:
                1 !important;
        }

        /* =====================================================
           FILTER VUA PHÁ LƯỚI — CHỈ DÀNH CHO MOBILE
           ===================================================== */
        @media (max-width: 768px) {
            /*
             * Giữ khung tổng rộng 258px.
             * Nút chọn sẽ chiếm toàn bộ phần còn lại sau logo.
             */
            div[class*="st-key-epl_scorers_club_filter_"] {
                width:
                    258px !important;
        
                max-width:
                    100% !important;
        
                margin:
                    0 auto 0 0 !important;
        
                padding:
                    3px 5px !important;
        
                box-sizing:
                    border-box !important;
        
                border:
                    1px solid rgba(55, 0, 60, 0.13)
                    !important;
        
                border-radius:
                    12px !important;
        
                background:
                    #FFFFFF !important;
        
                box-shadow:
                    0 5px 16px rgba(15, 23, 42, 0.055)
                    !important;
            }
        
            div[class*="st-key-epl_scorers_club_filter_"]:focus-within {
                border-color:
                    rgba(55, 0, 60, 0.35)
                    !important;
        
                box-shadow:
                    0 0 0 3px rgba(55, 0, 60, 0.07)
                    !important;
            }
        
            /* Hàng chứa logo và nút filter */
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stHorizontalBlock"]:has(
                .epl-club-filter-current-logo
            ):has(
                div[data-testid="stPopover"]
            ) {
                display:
                    flex !important;
        
                width:
                    100% !important;
        
                height:
                    36px !important;
        
                min-height:
                    36px !important;
        
                align-items:
                    center !important;
        
                gap:
                    2px !important;
            }
        
            /*
             * Hỗ trợ cả hai tên selector cột của Streamlit:
             * stColumn và column.
             */
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stHorizontalBlock"]:has(
                .epl-club-filter-current-logo
            ):has(
                div[data-testid="stPopover"]
            )
            > :is(
                div[data-testid="stColumn"],
                div[data-testid="column"]
            ) {
                min-width:
                    0 !important;
        
                padding:
                    0 !important;
            }
        
            /* Cột logo được thu hẹp để nút dịch sang trái */
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stHorizontalBlock"]:has(
                .epl-club-filter-current-logo
            ):has(
                div[data-testid="stPopover"]
            )
            > :is(
                div[data-testid="stColumn"],
                div[data-testid="column"]
            ):first-child {
                width:
                    38px !important;
        
                min-width:
                    38px !important;
        
                max-width:
                    38px !important;
        
                flex:
                    0 0 38px !important;
            }
        
            /*
             * Cột filter chiếm toàn bộ phần còn lại.
             * Đây là phần giúp nút dài tương xứng với khung ngoài.
             */
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stHorizontalBlock"]:has(
                .epl-club-filter-current-logo
            ):has(
                div[data-testid="stPopover"]
            )
            > :is(
                div[data-testid="stColumn"],
                div[data-testid="column"]
            ):last-child {
                width:
                    calc(100% - 40px) !important;
        
                min-width:
                    0 !important;
        
                max-width:
                    none !important;
        
                flex:
                    1 1 0 !important;
            }
        
            /* Cho các wrapper bên trong cột filter giãn đủ chiều rộng */
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stHorizontalBlock"]:has(
                .epl-club-filter-current-logo
            )
            > :is(
                div[data-testid="stColumn"],
                div[data-testid="column"]
            ):last-child
            div[data-testid="stVerticalBlock"],
        
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stHorizontalBlock"]:has(
                .epl-club-filter-current-logo
            )
            > :is(
                div[data-testid="stColumn"],
                div[data-testid="column"]
            ):last-child
            div[data-testid="stElementContainer"],
        
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stPopover"] {
                width:
                    100% !important;
        
                min-width:
                    0 !important;
            }
        
            /* Căn logo chính giữa */
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stElementContainer"]:has(
                .epl-club-filter-current-logo
            ),
        
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stMarkdownContainer"]:has(
                .epl-club-filter-current-logo
            ) {
                display:
                    flex !important;
        
                width:
                    100% !important;
        
                height:
                    36px !important;
        
                align-items:
                    center !important;
        
                justify-content:
                    center !important;
        
                margin:
                    0 !important;
        
                padding:
                    0 !important;
        
                line-height:
                    0 !important;
            }
        
            div[class*="st-key-epl_scorers_club_filter_"]
            .epl-club-filter-current-logo {
                display:
                    flex !important;
        
                width:
                    36px !important;
        
                height:
                    36px !important;
        
                align-items:
                    center !important;
        
                justify-content:
                    center !important;
        
                margin:
                    0 !important;
        
                padding:
                    0 !important;
        
                transform:
                    none !important;
            }
        
            div[class*="st-key-epl_scorers_club_filter_"]
            .epl-club-filter-current-logo img {
                display:
                    block !important;
        
                width:
                    28px !important;
        
                height:
                    28px !important;
        
                margin:
                    0 !important;
        
                object-fit:
                    contain !important;
        
                object-position:
                    center !important;
        
                transform:
                    none !important;
            }
        
            /* Nút chọn đội giãn hết cột */
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stPopover"] > button,
        
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stPopover"] > div > button {
                display:
                    flex !important;
        
                width:
                    100% !important;
        
                min-width:
                    0 !important;
        
                height:
                    36px !important;
        
                min-height:
                    36px !important;
        
                box-sizing:
                    border-box !important;
        
                align-items:
                    center !important;
        
                justify-content:
                    flex-start !important;
        
                padding:
                    0 8px 0 7px !important;
        
                border-radius:
                    9px !important;
        
                background:
                    rgba(72, 24, 120, 0.045)
                    !important;
        
                color:
                    #37105F !important;
        
                font-size:
                    13px !important;
        
                font-weight:
                    800 !important;
        
                text-align:
                    left !important;
            }
        
            /* Chữ nằm sát bên trái nút */
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stPopover"] > button
            [data-testid="stMarkdownContainer"],
        
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stPopover"] > div > button
            [data-testid="stMarkdownContainer"] {
                width:
                    auto !important;
        
                min-width:
                    0 !important;
        
                flex:
                    1 1 auto !important;
        
                margin:
                    0 !important;
        
                text-align:
                    left !important;
            }
        
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stPopover"] button p {
                width:
                    auto !important;
        
                margin:
                    0 !important;
        
                overflow:
                    hidden !important;
        
                text-align:
                    left !important;
        
                text-overflow:
                    ellipsis !important;
        
                white-space:
                    nowrap !important;
            }
        
            /* Đặt mũi tên ở cuối nút */
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stPopover"] > button svg:last-child,
        
            div[class*="st-key-epl_scorers_club_filter_"]
            div[data-testid="stPopover"] > div > button
            svg:last-child {
                margin-left:
                    auto !important;
        
                margin-right:
                    0 !important;
        
                flex:
                    0 0 auto !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    with st.container(
        key=(
            "epl_scorers_club_filter_"
            f"{season_key}"
        )
    ):
        logo_col, menu_col = st.columns(
            [0.19, 0.81]
        )

        with logo_col:
            st.markdown(
                build_logo_html(
                    selected_club
                ),
                unsafe_allow_html=True
            )

        with menu_col:
            with st.popover(
                selected_club["club_name"],
                use_container_width=True
            ):
                st.markdown(
                    """
                    <div style="
                        color:#07111F;
                        font-size:14px;
                        font-weight:900;
                        margin-bottom:2px;
                    ">
                        Lọc theo câu lạc bộ
                    </div>

                    <div style="
                        color:#64748B;
                        font-size:12px;
                        line-height:1.4;
                        margin-bottom:10px;
                    ">
                        Chọn một đội để xem danh sách ghi bàn.
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                all_club = {
                    "team_id": None,
                    "club_name": "Toàn giải",
                    "club_logo": "data/static/epl.png"
                }

                option_logo_col, option_button_col = (
                    st.columns([0.16, 0.84])
                )

                with option_logo_col:
                    st.markdown(
                        build_logo_html(
                            all_club,
                            option_logo=True
                        ),
                        unsafe_allow_html=True
                    )

                with option_button_col:
                    if st.button(
                        "Tất cả",
                        key=(
                            "epl_scorer_club_option_"
                            f"{season_key}_all"
                        ),
                        use_container_width=True,
                        disabled=selected_id is None
                    ):
                        st.session_state[
                            state_key
                        ] = "all"

                        st.rerun()

                for club in clubs:
                    (
                        option_logo_col,
                        option_button_col
                    ) = st.columns(
                        [0.16, 0.84]
                    )

                    with option_logo_col:
                        st.markdown(
                            build_logo_html(
                                club,
                                option_logo=True
                            ),
                            unsafe_allow_html=True
                        )

                    with option_button_col:
                        if st.button(
                            club["club_name"],
                            key=(
                                "epl_scorer_club_option_"
                                f"{season_key}_"
                                f"{club['team_id']}"
                            ),
                            use_container_width=True,
                            disabled=(
                                selected_id
                                == club["team_id"]
                            )
                        ):
                            st.session_state[
                                state_key
                            ] = club["team_id"]

                            st.rerun()

    return selected_club

def render_epl_top_scorers_table(
    top_scorers_df: pd.DataFrame
):
    if top_scorers_df.empty:
        return

    rows_html = []

    for _, row in (
        top_scorers_df
        .reset_index(drop=True)
        .iterrows()
    ):
        rank = (
            to_optional_int(
                row.get("rank")
            )
            or 0
        )

        goals = (
            to_optional_int(
                row.get("goals")
            )
            or 0
        )

        player_name = html.escape(
            str(
                row.get(
                    "player_name",
                    ""
                )
            ).strip()
        )

        raw_club_name = str(
            row.get(
                "club_name",
                ""
            )
        ).strip()

        club_name = html.escape(
            raw_club_name
        )

        mobile_club_name = html.escape(
            get_mobile_team_display_name(
                raw_club_name
            )
        )

        logo_path = str(
            row.get(
                "club_logo",
                ""
            )
            or ""
        ).strip()

        logo_src = (
            resolve_asset_src(logo_path)
            if logo_path
            else ""
        )

        if logo_src:
            logo_html = (
                '<img class="epl-scorer-club-logo" '
                f'src="{html.escape(logo_src, quote=True)}" '
                f'alt="{club_name}">'
            )
        else:
            logo_html = ""

        if rank == 1:
            rank_class = "rank-gold"

        elif rank == 2:
            rank_class = "rank-silver"

        elif rank == 3:
            rank_class = "rank-bronze"

        else:
            rank_class = ""

        rows_html.append(
            f"""
            <tr>
                <td class="epl-scorer-rank-cell">
                    <span class="
                        epl-scorer-rank
                        {rank_class}
                    ">
                        {rank}
                    </span>
                </td>

                <td class="epl-scorer-player-cell">
                    <span class="epl-scorer-player-name">
                        {player_name}
                    </span>
                </td>

                <td class="epl-scorer-club-cell">
                    <div class="epl-scorer-club-wrap">
                        {logo_html}
                        <span class="epl-team-name-desktop">
                            {club_name}
                        </span>
                        <span class="epl-team-name-mobile">
                            {mobile_club_name}
                        </span>
                    </div>
                </td>

                <td class="epl-scorer-goals-cell">
                    {goals}
                </td>
            </tr>
            """
        )

    scorers_html = """
    <style>
    #epl-scorers-table-root,
    #epl-scorers-table-root * {
        box-sizing: border-box;
    }

    .epl-scorers-box {
        margin-top: 18px;

        overflow: hidden;

        border:
            1px solid rgba(15, 23, 42, 0.08);

        border-radius:
            18px;

        background:
            #FFFFFF;

        box-shadow:
            0 18px 45px
            rgba(15, 23, 42, 0.10);
    }

    .epl-scorers-scroll {
        width: 100%;
        max-height: none;
        overflow: visible;
    }

    .epl-scorers-table {
        width: 100%;
        min-width: 620px;

        border-collapse:
            collapse;

        color:
            #0F172A;

        font-size:
            14px;

        font-family:
            system-ui,
            -apple-system,
            BlinkMacSystemFont,
            "Segoe UI",
            sans-serif;
    }

    .epl-scorers-table th {
        position: static;

        padding:
            14px 16px;

        background:
            linear-gradient(
                135deg,
                #07111F,
                #14213A
            );

        color:
            #F8FAFC;

        font-size:
            12px;

        font-weight:
            900;

        text-align:
            left;

        white-space:
            nowrap;
    }

    .epl-scorers-table th:first-child,
    .epl-scorers-table th:last-child {
        text-align:
            center;
    }

    .epl-scorers-table td {
        height:
            58px;

        padding:
            11px 16px;

        border-bottom:
            1px solid rgba(15, 23, 42, 0.08);

        background:
            rgba(255, 255, 255, 0.96);

        vertical-align:
            middle;
    }

    .epl-scorers-table
    tbody
    tr:last-child
    td {
        border-bottom:
            0;
    }

    .epl-scorers-table
    tbody
    tr:hover
    td {
        background:
            #F5F0FA;
    }

    .epl-scorer-rank-cell {
        width:
            86px;

        text-align:
            center;
    }

    .epl-scorer-rank {
        width:
            31px;

        height:
            31px;

        display:
            inline-flex;

        align-items:
            center;

        justify-content:
            center;

        border:
            1px solid
            rgba(100, 116, 139, 0.16);

        border-radius:
            50%;

        background:
            #F4F7FA;

        color:
            #334155;

        font-size:
            13px;

        font-weight:
            950;
    }

    .epl-scorer-rank.rank-gold {
        border-color:
            #D6A83F;

        background:
            linear-gradient(
                145deg,
                #FFF3B6,
                #D9A93E
            );

        color:
            #4B2B00;

        box-shadow:
            0 5px 12px
            rgba(214, 168, 63, 0.24);
    }

    .epl-scorer-rank.rank-silver {
        border-color:
            #AEB7C2;

        background:
            linear-gradient(
                145deg,
                #F8FAFC,
                #CBD5E1
            );

        color:
            #334155;
    }

    .epl-scorer-rank.rank-bronze {
        border-color:
            #B97943;

        background:
            linear-gradient(
                145deg,
                #F1C19B,
                #B8733D
            );

        color:
            #4A2108;
    }

    .epl-scorer-player-cell {
        min-width:
            230px;

        color:
            #101828;

        font-weight:
            900;

        letter-spacing:
            -0.01em;
    }

    .epl-scorer-club-cell {
        min-width:
            260px;

        color:
            #475569;

        font-weight:
            750;
    }

    .epl-scorer-club-wrap {
        display:
            flex;

        align-items:
            center;

        gap:
            11px;
    }

    .epl-team-name-mobile {
        display:
            none;
    }

    html.epl-mobile-team-names
    .epl-team-name-desktop {
        display:
            none;
    }

    html.epl-mobile-team-names
    .epl-team-name-mobile {
        display:
            inline;
    }

    .epl-scorer-club-logo {
        width:
            29px;

        height:
            29px;

        flex:
            0 0 29px;

        display:
            block;

        object-fit:
            contain;
    }

    .epl-scorer-goals-cell {
        width:
            128px;

        background:
            rgba(245, 197, 66, 0.22)
            !important;

        color:
            #07111F;

        font-size:
            16px;

        font-weight:
            950;

        text-align:
            center;
    }
    .epl-scorers-head-mobile {
        display:
            none;
    }
    /* =====================================================
       BẢNG VUA PHÁ LƯỚI — CHỈ DÀNH CHO MOBILE
       ===================================================== */
    
    /* Đổi header sang chữ ngắn trên mobile */
    html.epl-mobile-team-names
    .epl-scorers-head-desktop {
        display:
            none !important;
    }
    
    html.epl-mobile-team-names
    .epl-scorers-head-mobile {
        display:
            inline !important;
    }
    
    html.epl-mobile-team-names
    .epl-scorers-box {
        margin-top:
            12px;
    
        border-radius:
            14px;
    
        box-shadow:
            0 8px 22px rgba(15, 23, 42, 0.07);
    }
    
    html.epl-mobile-team-names
    .epl-scorers-scroll {
        width: 100%;
        overflow: visible;
    }
    
    html.epl-mobile-team-names
    .epl-scorers-table {
        width:
            100%;
    
        min-width:
            0;
    
        table-layout:
            fixed;
    
        font-size:
            12px;
    }
    
    html.epl-mobile-team-names
    .epl-scorers-table th {
        height:
            38px;
    
        padding:
            8px 4px;
    
        font-size:
            9.5px;
    
        font-weight:
            900;
    
        line-height:
            1.1;
    
        letter-spacing:
            0;
    
        text-align:
            center;
    }
    
    html.epl-mobile-team-names
    .epl-scorers-table
    th:nth-child(2) {
        text-align:
            left;
    }
    
    html.epl-mobile-team-names
    .epl-scorers-table td {
        height:
            55px;
    
        padding:
            7px 4px;
    
        vertical-align:
            middle;
    }
    
    /*
     * Chia lại theo tỷ lệ linh hoạt:
     *
     * Hạng:    15%
     * Cầu thủ: 50%
     * CLB:     18%
     * Bàn:     17%
     *
     * Tổng:   100%
     */
    html.epl-mobile-team-names
    .epl-scorers-table
    :is(th, td):nth-child(1) {
        width:
            15%;
    }
    
    html.epl-mobile-team-names
    .epl-scorers-table
    :is(th, td):nth-child(2) {
        width:
            50%;
    }
    
    html.epl-mobile-team-names
    .epl-scorers-table
    :is(th, td):nth-child(3) {
        width:
            18%;
    }
    
    html.epl-mobile-team-names
    .epl-scorers-table
    :is(th, td):nth-child(4) {
        width:
            17%;
    }
    
    /* Hạng */
    html.epl-mobile-team-names
    .epl-scorer-rank-cell {
        width:
            15%;
    
        padding:
            4px 3px !important;
    
        text-align:
            center;
    }
    
    html.epl-mobile-team-names
    .epl-scorer-rank {
        width:
            27px;
    
        height:
            27px;
    
        font-size:
            11.5px;
    }
    
    /* Cầu thủ */
    html.epl-mobile-team-names
    .epl-scorer-player-cell {
        width:
            50%;
    
        min-width:
            0;
    
        padding-left:
            8px !important;
    
        padding-right:
            7px !important;
    
        color:
            #101828;
    
        font-size:
            11.5px;
    
        font-weight:
            850;
    
        line-height:
            1.22;
    
        overflow-wrap:
            anywhere;
    }
    
    html.epl-mobile-team-names
    .epl-scorer-player-name {
        display:
            -webkit-box;
    
        overflow:
            hidden;
    
        -webkit-box-orient:
            vertical;
    
        -webkit-line-clamp:
            2;
    
        line-clamp:
            2;
    }
    
    /* CLB: chỉ giữ lại logo */
    html.epl-mobile-team-names
    .epl-scorer-club-cell {
        width:
            18%;
    
        min-width:
            0;
    
        padding:
            4px 6px !important;
    
        text-align:
            center;
    }
    
    html.epl-mobile-team-names
    .epl-scorer-club-wrap {
        display:
            flex;
    
        width:
            100%;
    
        height:
            100%;
    
        align-items:
            center;
    
        justify-content:
            center;
    
        gap:
            0;
    }
    
    html.epl-mobile-team-names
    .epl-scorer-club-wrap
    .epl-team-name-desktop,
    
    html.epl-mobile-team-names
    .epl-scorer-club-wrap
    .epl-team-name-mobile {
        display:
            none !important;
    }
    
    html.epl-mobile-team-names
    .epl-scorer-club-logo {
        display:
            block;
    
        width:
            28px;
    
        height:
            28px;
    
        flex:
            0 0 28px;
    
        margin:
            0 auto;
    
        object-fit:
            contain;
    
        object-position:
            center;
    }
    
    /* Bàn: chỉ hiển thị số */
    html.epl-mobile-team-names
    .epl-scorer-goals-cell {
        width:
            17%;
    
        padding:
            4px 6px !important;
    
        border-radius:
            0 !important;
    
        background:
            inherit !important;
    
        color:
            #37105F;
    
        font-size:
            15px;
    
        font-weight:
            950;
    
        line-height:
            1;
    
        text-align:
            center;
    
        box-shadow:
            none !important;
    }
    
    /* Nền xen kẽ giữa các hàng */
    html.epl-mobile-team-names
    .epl-scorers-table
    tbody
    tr:nth-child(odd) {
        background:
            #FFFFFF;
    }
    
    html.epl-mobile-team-names
    .epl-scorers-table
    tbody
    tr:nth-child(even) {
        background:
            #F8FAFC;
    }
    
    html.epl-mobile-team-names
    .epl-scorers-table
    tbody
    tr
    td {
        background:
            inherit !important;
    }
    
    /* Điều chỉnh nhẹ cho điện thoại rất nhỏ */
    @media (max-width: 390px) {
        html.epl-mobile-team-names
        .epl-scorers-table th {
            font-size:
                9.2px;
        }
    
        html.epl-mobile-team-names
        .epl-scorer-player-cell {
            padding-left:
                7px !important;
    
            padding-right:
                5px !important;
    
            font-size:
                11px;
        }
    
        html.epl-mobile-team-names
        .epl-scorer-club-logo {
            width:
                26px;
    
            height:
                26px;
    
            flex-basis:
                26px;
        }
    
        html.epl-mobile-team-names
        .epl-scorer-goals-cell {
            font-size:
                14px;
        }
    }
    </style>

    <div
        id="epl-scorers-table-root"
        class="epl-scorers-box"
    >
        <div
            class="epl-scorers-scroll"
            data-page-table-scroll
        >
            <table class="epl-scorers-table">
                <thead>
                    <tr>
                        <th>Hạng</th>
                
                        <th>Cầu thủ</th>
                
                        <th>
                            <span class="epl-scorers-head-desktop">
                                Câu lạc bộ
                            </span>
                
                            <span class="epl-scorers-head-mobile">
                                CLB
                            </span>
                        </th>
                
                        <th>
                            <span class="epl-scorers-head-desktop">
                                Bàn thắng
                            </span>
                
                            <span class="epl-scorers-head-mobile">
                                Bàn
                            </span>
                        </th>
                    </tr>
                </thead>

                <tbody>
    """ + "".join(rows_html) + """
                </tbody>
            </table>
        </div>
    </div>

    <script>
    (() => {
        const parentWindow = window.parent;
        const mobileQuery = parentWindow.matchMedia(
            "(max-width: 768px)"
        );

        const applyTeamNameMode = () => {
            document.documentElement.classList.toggle(
                "epl-mobile-team-names",
                mobileQuery.matches
            );
        };

        applyTeamNameMode();

        mobileQuery.addEventListener(
            "change",
            applyTeamNameMode
        );

        window.addEventListener(
            "unload",
            () => {
                mobileQuery.removeEventListener(
                    "change",
                    applyTeamNameMode
                );
            }
        );
    })();
    </script>
    """

    render_page_native_sticky_table(
        scorers_html,
        "epl-scorers-table-root"
    )

def page_competition_stats():
    active_view = (
        render_competition_stats_view_switcher()
    )

    season_slug = (
        get_selected_season_slug()
    )

    season_label = (
        get_selected_season_label()
    )

    # =====================================================
    # VUA PHÁ LƯỚI
    # =====================================================
    if active_view == "top_scorers":
        matches = load_matches(
            season_slug
        )

        clubs_df = (
            build_epl_season_clubs_df(
                matches
            )
        )

        st.markdown(
            """
            <style>
            /* Desktop giữ nguyên */
            div[class*="st-key-epl_top_scorers_header_"]
            div[data-testid="stHorizontalBlock"] {
                align-items:
                    center !important;
            }

            div[class*="st-key-epl_top_scorers_title_"]
            .wc-page-title {
                margin-bottom:
                    0 !important;
            }

            /* Nội dung dành riêng cho mobile mặc định bị ẩn */
            div[class*="st-key-epl_top_scorers_title_"]
            .epl-scorers-title-mobile,

            div[class*="st-key-epl_top_scorers_title_"]
            .epl-scorers-subtitle-mobile {
                display:
                    none;
            }

            @media (max-width: 768px) {
                /*
                 * Chỉ bắt hàng ngoài cùng có cả tiêu đề và filter.
                 * Không ảnh hưởng các stHorizontalBlock nằm bên trong filter.
                 */
                div[class*="st-key-epl_top_scorers_header_"]
                div[data-testid="stHorizontalBlock"]:has(
                    div[class*="st-key-epl_top_scorers_title_"]
                ):has(
                    div[class*="st-key-epl_top_scorers_filter_slot_"]
                ) {
                    display:
                        flex !important;

                    flex-direction:
                        column !important;

                    align-items:
                        stretch !important;

                    gap:
                        10px !important;
                }

                div[class*="st-key-epl_top_scorers_header_"]
                div[data-testid="stHorizontalBlock"]:has(
                    div[class*="st-key-epl_top_scorers_title_"]
                ):has(
                    div[class*="st-key-epl_top_scorers_filter_slot_"]
                )
                > div[data-testid="stColumn"] {
                    width:
                        100% !important;

                    min-width:
                        100% !important;

                    max-width:
                        100% !important;

                    flex:
                        0 0 100% !important;
                }

                /* Tiêu đề luôn nằm trước */
                div[data-testid="stColumn"]:has(
                    div[class*="st-key-epl_top_scorers_title_"]
                ) {
                    order:
                        1 !important;
                }

                /* Filter luôn nằm dưới tiêu đề */
                div[data-testid="stColumn"]:has(
                    div[class*="st-key-epl_top_scorers_filter_slot_"]
                ) {
                    order:
                        2 !important;
                }

                div[class*="st-key-epl_top_scorers_title_"]
                .wc-page-title {
                    margin:
                        0 !important;
                }

                div[class*="st-key-epl_top_scorers_title_"]
                .wc-page-title h2 {
                    margin:
                        0 0 5px !important;

                    color:
                        #07111F !important;

                    font-size:
                        clamp(21px, 6vw, 24px) !important;

                    font-weight:
                        950 !important;

                    line-height:
                        1.08 !important;

                    letter-spacing:
                        -0.035em !important;
                }

                div[class*="st-key-epl_top_scorers_title_"]
                .wc-page-title p {
                    margin:
                        0 !important;

                    font-size:
                        12.5px !important;

                    line-height:
                        1.35 !important;
                }

                /* Đổi nội dung tiêu đề riêng trên mobile */
                div[class*="st-key-epl_top_scorers_title_"]
                .epl-scorers-title-desktop,

                div[class*="st-key-epl_top_scorers_title_"]
                .epl-scorers-subtitle-desktop {
                    display:
                        none !important;
                }

                div[class*="st-key-epl_top_scorers_title_"]
                .epl-scorers-title-mobile,

                div[class*="st-key-epl_top_scorers_title_"]
                .epl-scorers-subtitle-mobile {
                    display:
                        inline !important;
                }

                div[class*="st-key-epl_top_scorers_filter_slot_"] {
                    width:
                        100% !important;

                    margin:
                        0 !important;
                }
            }
            </style>
            """,
            unsafe_allow_html=True
        )

        season_key = season_slug.replace(
            "-",
            "_"
        )

        with st.container(
            key=(
                "epl_top_scorers_header_"
                f"{season_key}"
            )
        ):
            title_col, filter_col = st.columns(
                [3.25, 1]
            )

            # Render bộ lọc trước để lấy chính xác
            # trạng thái đang được chọn.
            with filter_col:
                with st.container(
                    key=(
                        "epl_top_scorers_filter_slot_"
                        f"{season_key}"
                    )
                ):
                    selected_club = (
                        render_epl_top_scorers_club_filter(
                            clubs_df,
                            season_slug
                        )
                    )

            selected_team_id = (
                selected_club["team_id"]
            )

            selected_club_name = (
                selected_club["club_name"]
            )

            with title_col:
                with st.container(
                    key=(
                        "epl_top_scorers_title_"
                        f"{season_key}"
                    )
                ):
                    if selected_team_id is None:
                        desktop_page_title = (
                            "VUA PHÁ LƯỚI "
                            "PREMIER LEAGUE "
                            f"{season_label}"
                        )

                        desktop_page_subtitle = (
                            "Top 20 chân sút hàng đầu giải"
                        )

                        mobile_page_title = (
                            "VUA PHÁ LƯỚI"
                        )

                        mobile_page_subtitle = (
                            "Premier League "
                            f"{season_label} · Top 20"
                        )

                    else:
                        desktop_page_title = (
                            "DANH SÁCH GHI BÀN "
                            f"{selected_club_name} "
                            f"{season_label}"
                        ).upper()

                        desktop_page_subtitle = (
                            "Danh sách cầu thủ "
                            "ghi bàn cho câu lạc bộ"
                        )

                        mobile_club_name = (
                            get_mobile_team_display_name(
                                selected_club_name
                            )
                        )

                        mobile_page_title = (
                            "DANH SÁCH GHI BÀN"
                        )

                        mobile_page_subtitle = (
                            f"{mobile_club_name} "
                            f"· {season_label}"
                        )

                    page_title_html = (
                        '<span '
                        'class="epl-scorers-title-desktop">'
                        f'{html.escape(desktop_page_title)}'
                        '</span>'

                        '<span '
                        'class="epl-scorers-title-mobile">'
                        f'{html.escape(mobile_page_title)}'
                        '</span>'
                    )

                    page_subtitle_html = (
                        '<span '
                        'class="epl-scorers-subtitle-desktop">'
                        f'{html.escape(desktop_page_subtitle)}'
                        '</span>'

                        '<span '
                        'class="epl-scorers-subtitle-mobile">'
                        f'{html.escape(mobile_page_subtitle)}'
                        '</span>'
                    )

                    render_page_title(
                        page_title_html,
                        page_subtitle_html
                    )

        top_scorers = (
            load_epl_top_scorers(
                season_slug=season_slug,
                team_id=selected_team_id
            )
        )

        if top_scorers.empty:
            if selected_team_id is None:
                st.info(
                    "Chưa có dữ liệu cầu thủ "
                    "ghi bàn cho mùa giải này."
                )

            else:
                st.info(
                    f"Chưa có dữ liệu cầu thủ "
                    f"ghi bàn cho "
                    f"{selected_club_name}."
                )

            return

        render_epl_top_scorers_table(
            top_scorers
        )

        return

    # =====================================================
    # BẢNG XẾP HẠNG CÂU LẠC BỘ
    # =====================================================
    st.markdown(
        f"""
        <style>
        .wc-page-title.epl-standings-page-title {{
            margin:
                6px 0 0 !important;
        }}
    
        .wc-page-title.epl-standings-page-title h2 {{
            margin:
                0 !important;
        }}
    
        @media (max-width: 768px) {{
            .wc-page-title.epl-standings-page-title {{
                margin:
                    2px 0 0 !important;
            }}
        }}
        </style>
    
        <div class="wc-page-title epl-standings-page-title">
            <h2>
                BẢNG XẾP HẠNG PREMIER LEAGUE
                {html.escape(str(season_label))}
            </h2>
        </div>
        """,
        unsafe_allow_html=True
    )

    matches = load_matches(
        season_slug
    )

    standings = build_epl_standings_df(
        matches
    )

    if standings.empty:
        st.info(
            "Chưa có đủ dữ liệu trận đấu "
            "để tính bảng xếp hạng."
        )

        return

    render_epl_standings_table(
        standings
    )

def normalize_prediction_round_name(value) -> str:
    """
    Chuẩn hóa tên vòng để dữ liệu "Vòng 1" và "Matchday 1"
    được gom vào cùng một lựa chọn.
    """
    if value is None or pd.isna(value):
        return ""

    round_text = str(value).strip()

    if not round_text:
        return ""

    round_number_match = re.search(
        r"\d+",
        round_text
    )

    if round_number_match:
        return (
            f"Vòng {int(round_number_match.group(0))}"
        )

    return round_text


def get_prediction_round_sort_key(
    round_name: str
) -> tuple:
    round_number_match = re.search(
        r"\d+",
        str(round_name)
    )

    if round_number_match:
        return (
            0,
            int(round_number_match.group(0)),
            str(round_name).casefold()
        )

    return (
        1,
        10**9,
        str(round_name).casefold()
    )


def get_available_prediction_rounds(
    matches: pd.DataFrame
) -> list[str]:
    if (
        matches.empty
        or "round_name" not in matches.columns
    ):
        return []

    normalized_rounds = (
        matches["round_name"]
        .map(normalize_prediction_round_name)
    )

    return sorted(
        {
            round_name
            for round_name in normalized_rounds
            if round_name
        },
        key=get_prediction_round_sort_key
    )


def get_default_prediction_round(
    matches: pd.DataFrame,
    round_names: list[str]
) -> str | None:
    """
    Mặc định:
    - vòng chưa hoàn tất gần nhất đã bắt đầu;
    - nếu mùa chưa bắt đầu, chọn vòng đầu tiên;
    - nếu mùa đã kết thúc, chọn vòng cuối cùng.
    """
    if not round_names:
        return None

    if matches.empty:
        return round_names[0]

    working_matches = matches.copy()
    working_matches["_round_key"] = (
        working_matches["round_name"]
        .map(normalize_prediction_round_name)
    )

    kickoff_source = (
        working_matches["kickoff_time_utc_dt"]
        if "kickoff_time_utc_dt" in working_matches.columns
        else working_matches.get(
            "kickoff_time_utc",
            pd.Series(
                pd.NaT,
                index=working_matches.index
            )
        )
    )

    working_matches["_kickoff"] = pd.to_datetime(
        kickoff_source,
        utc=True,
        errors="coerce"
    )

    actual_home = pd.to_numeric(
        working_matches.get(
            "home_score_for_prediction",
            pd.Series(
                pd.NA,
                index=working_matches.index
            )
        ),
        errors="coerce"
    )

    actual_away = pd.to_numeric(
        working_matches.get(
            "away_score_for_prediction",
            pd.Series(
                pd.NA,
                index=working_matches.index
            )
        ),
        errors="coerce"
    )

    finished_source = working_matches.get(
        "is_finished",
        pd.Series(
            False,
            index=working_matches.index
        )
    )

    working_matches["_is_complete"] = (
        finished_source.map(to_bool)
        & actual_home.notna()
        & actual_away.notna()
    )

    round_status = (
        working_matches[
            working_matches["_round_key"].isin(
                round_names
            )
        ]
        .groupby(
            "_round_key",
            as_index=False
        )
        .agg(
            match_count=(
                "match_id",
                "nunique"
            ),
            completed_match_count=(
                "_is_complete",
                "sum"
            ),
            first_kickoff=(
                "_kickoff",
                "min"
            )
        )
        .set_index("_round_key")
    )

    now_utc = pd.Timestamp.now(tz="UTC")
    started_incomplete_rounds = []
    future_incomplete_rounds = []

    for round_name in round_names:
        if round_name not in round_status.index:
            continue

        status_row = round_status.loc[round_name]
        match_count = int(
            status_row["match_count"]
        )
        completed_match_count = int(
            status_row["completed_match_count"]
        )
        is_complete = (
            match_count == EPL_MATCHES_PER_ROUND
            and completed_match_count == match_count
        )

        if is_complete:
            continue

        first_kickoff = status_row["first_kickoff"]

        if (
            pd.notna(first_kickoff)
            and first_kickoff <= now_utc
        ):
            started_incomplete_rounds.append(
                round_name
            )
        else:
            future_incomplete_rounds.append(
                round_name
            )

    if started_incomplete_rounds:
        return started_incomplete_rounds[-1]

    if future_incomplete_rounds:
        return future_incomplete_rounds[0]

    return round_names[-1]


def render_prediction_leaderboard_view_switcher() -> str:
    """
    Bộ chọn đầu trang giữa BXH tổng và BXH theo vòng.
    CSS được khóa trong key riêng để không tác động nút header/menu.
    """
    valid_views = {
        "overall",
        "round"
    }

    active_view = st.session_state.get(
        "prediction_leaderboard_view",
        "overall"
    )

    if active_view not in valid_views:
        active_view = "overall"
        st.session_state[
            "prediction_leaderboard_view"
        ] = active_view

    st.markdown(
        """
        <style>
        div[class*="st-key-prediction_leaderboard_tabs"] {
            width: min(450px, 100%) !important;
            margin: 0 0 18px 0 !important;
            padding: 5px !important;
            border: 1px solid rgba(7,17,31,0.12) !important;
            border-radius: 14px !important;
            background: rgba(255,255,255,0.90) !important;
            box-shadow:
                0 10px 28px rgba(7,17,31,0.07),
                inset 0 1px 0 rgba(255,255,255,0.94)
                !important;
            backdrop-filter: blur(10px);
        }

        div[class*="st-key-prediction_leaderboard_tabs"]
        div[data-testid="stHorizontalBlock"] {
            gap: 5px !important;
        }

        div[class*="st-key-prediction_leaderboard_tabs"]
        div[data-testid="stColumn"] {
            min-width: 0 !important;
            padding: 0 !important;
        }

        div[class*="st-key-prediction_leaderboard_tabs"]
        div[class*="st-key-prediction_leaderboard_tab_"] {
            width: 100% !important;
            margin: 0 !important;
        }

        div[class*="st-key-prediction_leaderboard_tabs"]
        div[class*="st-key-prediction_leaderboard_tab_"]
        button {
            position: relative !important;
            width: 100% !important;
            min-height: 42px !important;
            padding: 0 15px !important;
            border: 1px solid transparent !important;
            border-radius: 10px !important;
            background: transparent !important;
            color: #536679 !important;
            box-shadow: none !important;
            font-size: 13.5px !important;
            font-weight: 850 !important;
            line-height: 1 !important;
            opacity: 1 !important;
            transform: none !important;
        }

        div[class*="st-key-prediction_leaderboard_tabs"]
        div[class*="st-key-prediction_leaderboard_tab_"]
        button:not(:disabled):hover {
            border-color: rgba(7,17,31,0.10) !important;
            background: rgba(7,17,31,0.05) !important;
            color: #07111F !important;
            transform: none !important;
        }

        div[class*="st-key-prediction_leaderboard_tabs"]
        div[class*="st-key-prediction_leaderboard_tab_"]
        button:disabled {
            border-color: #0B263C !important;
            background:
                linear-gradient(
                    135deg,
                    #07111F 0%,
                    #12324B 100%
                )
                !important;
            color: #FFFFFF !important;
            box-shadow:
                0 7px 18px rgba(7,17,31,0.18),
                inset 0 1px 0 rgba(255,255,255,0.12)
                !important;
            cursor: default !important;
            opacity: 1 !important;
        }

        div[class*="st-key-prediction_leaderboard_tabs"]
        div[class*="st-key-prediction_leaderboard_tab_"]
        button:disabled * {
            color: #FFFFFF !important;
            opacity: 1 !important;
        }

        div[class*="st-key-prediction_leaderboard_tabs"]
        div[class*="st-key-prediction_leaderboard_tab_"]
        button:disabled::after {
            content: "";
            position: absolute;
            left: 34%;
            right: 34%;
            bottom: 0;
            height: 2px;
            border-radius: 2px 2px 0 0;
            background: #F5C542;
            box-shadow:
                0 -1px 5px rgba(245,197,66,0.28);
        }

        @media (max-width: 768px) {
            div[class*="st-key-prediction_leaderboard_tabs"] {
                width: 100% !important;
                margin-bottom: 12px !important;
                padding: 4px !important;
                border-radius: 12px !important;
                box-shadow: 0 7px 20px rgba(7,17,31,0.06) !important;
            }

            div[class*="st-key-prediction_leaderboard_tabs"]
            div[data-testid="stHorizontalBlock"] {
                display: grid !important;
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                gap: 4px !important;
                align-items: stretch !important;
            }

            div[class*="st-key-prediction_leaderboard_tabs"]
            div[data-testid="stColumn"] {
                width: 100% !important;
                min-width: 0 !important;
                max-width: none !important;
                flex: none !important;
            }

            div[class*="st-key-prediction_leaderboard_tabs"]
            div[class*="st-key-prediction_leaderboard_tab_"]
            button {
                min-height: 38px !important;
                padding: 0 8px !important;
                border-radius: 9px !important;
                font-size: 12.5px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    with st.container(
        key="prediction_leaderboard_tabs"
    ):
        overall_column, round_column = st.columns(2)

        with overall_column:
            if st.button(
                "BXH tổng",
                key="prediction_leaderboard_tab_overall",
                use_container_width=True,
                disabled=active_view == "overall"
            ):
                st.session_state[
                    "prediction_leaderboard_view"
                ] = "overall"
                st.rerun()

        with round_column:
            if st.button(
                "BXH theo vòng",
                key="prediction_leaderboard_tab_round",
                use_container_width=True,
                disabled=active_view == "round"
            ):
                st.session_state[
                    "prediction_leaderboard_view"
                ] = "round"
                st.rerun()

    return active_view


def render_prediction_round_filter(
    matches: pd.DataFrame,
    season_slug: str
) -> str | None:
    round_names = get_available_prediction_rounds(
        matches
    )

    if not round_names:
        return None

    select_state_key = (
        "round_leaderboard_select_"
        + season_slug.replace("-", "_")
    )

    selected_round = st.session_state.get(
        select_state_key
    )

    if selected_round not in round_names:
        selected_round = get_default_prediction_round(
            matches,
            round_names
        )
        st.session_state[
            select_state_key
        ] = selected_round

    selected_index = round_names.index(
        selected_round
    )
    container_suffix = season_slug.replace(
        "-",
        "_"
    )

    st.markdown(
        """
        <style>
        div[class*="st-key-round_leaderboard_filter_"] {
            width: min(520px, 100%) !important;
            margin: -2px 0 18px 0 !important;
            padding: 0 !important;
            border: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }

        div[class*="st-key-round_leaderboard_filter_"]
        div[data-testid="stHorizontalBlock"] {
            gap: 8px !important;
            align-items: center !important;
        }

        div[class*="st-key-round_leaderboard_filter_"]
        div[data-testid="stColumn"] {
            min-width: 0 !important;
            padding: 0 !important;
        }

        div[class*="st-key-round_leaderboard_filter_"]
        div[data-baseweb="select"] > div {
            min-height: 40px !important;
            border-color: rgba(7,17,31,0.16) !important;
            border-radius: 10px !important;
            background: #FFFFFF !important;
            box-shadow: none !important;
        }

        div[class*="st-key-round_leaderboard_filter_"]
        div[data-testid="stSelectbox"] input[readonly] {
            caret-color: transparent !important;
            cursor: pointer !important;
            user-select: none !important;
            -webkit-user-select: none !important;
            -webkit-touch-callout: none !important;
        }

        div[class*="st-key-round_leaderboard_filter_"]
        div[class*="st-key-round_leaderboard_arrow_"]
        button {
            width: 40px !important;
            min-width: 40px !important;
            height: 40px !important;
            min-height: 40px !important;
            padding: 0 !important;
            border: 1px solid rgba(7,17,31,0.16) !important;
            border-radius: 10px !important;
            background: #FFFFFF !important;
            color: #0D2940 !important;
            box-shadow: none !important;
            font-size: 21px !important;
            font-weight: 900 !important;
            line-height: 1 !important;
            transform: none !important;
        }

        div[class*="st-key-round_leaderboard_filter_"]
        div[class*="st-key-round_leaderboard_arrow_"]
        button:hover:not(:disabled) {
            border-color: #E0AE15 !important;
            background: #F8D863 !important;
            color: #07111F !important;
            transform: none !important;
        }

        div[class*="st-key-round_leaderboard_filter_"]
        div[class*="st-key-round_leaderboard_arrow_"]
        button:disabled {
            border-color: #E2E8EE !important;
            background: #F4F7F9 !important;
            color: #AEBAC4 !important;
            opacity: 1 !important;
        }

        @media (max-width: 768px) {
            div[class*="st-key-round_leaderboard_filter_"] {
                width: 100% !important;
                margin: 0 0 13px 0 !important;
                padding: 0 !important;
            }

            div[class*="st-key-round_leaderboard_filter_"]
            div[data-testid="stHorizontalBlock"] {
                display: grid !important;
                grid-template-columns: 40px minmax(0, 1fr) 40px !important;
                gap: 8px !important;
                align-items: center !important;
            }

            div[class*="st-key-round_leaderboard_filter_"]
            div[data-testid="stColumn"] {
                width: 100% !important;
                min-width: 0 !important;
                max-width: none !important;
                flex: none !important;
            }

            div[class*="st-key-round_leaderboard_filter_"]
            div[data-baseweb="select"] > div {
                min-height: 40px !important;
                border-radius: 10px !important;
            }

            div[class*="st-key-round_leaderboard_filter_"]
            div[class*="st-key-round_leaderboard_arrow_"]
            button {
                width: 40px !important;
                min-width: 40px !important;
                height: 40px !important;
                min-height: 40px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    with st.container(
        key=(
            "round_leaderboard_filter_"
            + container_suffix
        )
    ):
        previous_column, select_column, next_column = (
            st.columns(
                [0.7, 4.6, 0.7]
            )
        )

        with previous_column:
            with st.container(
                key=(
                    "round_leaderboard_arrow_previous_"
                    + container_suffix
                )
            ):
                previous_clicked = st.button(
                    "‹",
                    key=(
                        "round_leaderboard_previous_"
                        + container_suffix
                    ),
                    help="Vòng trước",
                    disabled=selected_index <= 0
                )

        with next_column:
            with st.container(
                key=(
                    "round_leaderboard_arrow_next_"
                    + container_suffix
                )
            ):
                next_clicked = st.button(
                    "›",
                    key=(
                        "round_leaderboard_next_"
                        + container_suffix
                    ),
                    help="Vòng sau",
                    disabled=(
                        selected_index
                        >= len(round_names) - 1
                    )
                )

        # Hai nút mũi tên được xử lý trước khi selectbox được tạo.
        # Streamlit không cho phép sửa session_state của một widget
        # sau khi widget đó đã xuất hiện trong cùng một lượt chạy.
        if previous_clicked:
            st.session_state[
                select_state_key
            ] = round_names[
                selected_index - 1
            ]
            st.rerun()

        if next_clicked:
            st.session_state[
                select_state_key
            ] = round_names[
                selected_index + 1
            ]
            st.rerun()

        with select_column:
            selected_round = st.selectbox(
                "Chọn vòng",
                options=round_names,
                key=select_state_key,
                label_visibility="collapsed"
            )

    components.html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;

            const inputSelector = [
                'div[class*="st-key-round_leaderboard_filter_"]',
                'div[data-testid="stSelectbox"] input'
            ].join(" ");

            const readonlyStateKey =
                "__eplRoundLeaderboardSelectReadonly";

            const previousState =
                parentWindow[readonlyStateKey];

            if (previousState?.observer) {
                previousState.observer.disconnect();
            }

            if (previousState?.listeners) {
                for (const [eventName, listener] of Object.entries(
                    previousState.listeners
                )) {
                    parentDocument.removeEventListener(
                        eventName,
                        listener,
                        true
                    );
                }
            }

            const isRoundInput = (target) => {
                return (
                    target
                    && target instanceof parentWindow.HTMLInputElement
                    && target.matches(inputSelector)
                );
            };

            const blockKeyboardTextEditing = (event) => {
                if (!isRoundInput(event.target)) {
                    return;
                }

                const blockedKeys = new Set([
                    "Backspace",
                    "Delete"
                ]);

                if (
                    event.key.length === 1
                    || blockedKeys.has(event.key)
                ) {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                }
            };

            const blockManualTextInput = (event) => {
                if (!isRoundInput(event.target)) {
                    return;
                }

                event.preventDefault();
                event.stopImmediatePropagation();
            };

            const listeners = {
                keydown: blockKeyboardTextEditing,
                beforeinput: blockManualTextInput,
                paste: blockManualTextInput,
                drop: blockManualTextInput
            };

            for (const [eventName, listener] of Object.entries(
                listeners
            )) {
                parentDocument.addEventListener(
                    eventName,
                    listener,
                    true
                );
            }

            const lockInput = (input) => {
                if (!isRoundInput(input)) {
                    return;
                }

                input.readOnly = true;
                input.setAttribute("readonly", "");
                input.setAttribute("aria-readonly", "true");
                input.setAttribute("inputmode", "none");
                input.setAttribute("autocomplete", "off");
                input.setAttribute("spellcheck", "false");
            };

            const applyReadonly = () => {
                parentDocument
                    .querySelectorAll(inputSelector)
                    .forEach(lockInput);
            };

            let updateScheduled = false;

            const scheduleUpdate = () => {
                if (updateScheduled) {
                    return;
                }

                updateScheduled = true;

                parentWindow.requestAnimationFrame(() => {
                    updateScheduled = false;
                    applyReadonly();
                });
            };

            applyReadonly();

            const observer =
                new parentWindow.MutationObserver(
                    scheduleUpdate
                );

            observer.observe(
                parentDocument.body,
                {
                    childList: true,
                    subtree: true
                }
            );

            parentWindow[readonlyStateKey] = {
                observer,
                listeners
            };
        })();
        </script>
        """,
        height=0,
        scrolling=False
    )

    return selected_round


def build_round_leaderboard_df(
    season_slug: str,
    round_name: str
) -> pd.DataFrame:
    """
    Tính BXH riêng cho một vòng.

    Điểm vòng là tổng points sau bổ trợ của các trận trong vòng.
    Khoản +5 thưởng vô địch vòng không được cộng vào đây để tránh
    dùng chính phần thưởng làm thay đổi người vô địch.
    """
    users = load_users()
    matches = load_matches(season_slug)
    predictions = load_predictions(season_slug)

    if users.empty:
        return pd.DataFrame()

    normalized_round_name = (
        normalize_prediction_round_name(
            round_name
        )
    )

    if (
        matches.empty
        or not normalized_round_name
        or "round_name" not in matches.columns
    ):
        return pd.DataFrame()

    round_keys = matches["round_name"].map(
        normalize_prediction_round_name
    )

    round_matches = matches.loc[
        round_keys.eq(normalized_round_name)
    ].copy()

    if round_matches.empty:
        return pd.DataFrame()

    actual_home = pd.to_numeric(
        round_matches[
            "home_score_for_prediction"
        ],
        errors="coerce"
    )
    actual_away = pd.to_numeric(
        round_matches[
            "away_score_for_prediction"
        ],
        errors="coerce"
    )

    round_matches["_is_complete"] = (
        round_matches["is_finished"].map(
            to_bool
        )
        & actual_home.notna()
        & actual_away.notna()
    )

    round_match_count = int(
        round_matches["match_id"].nunique()
    )
    completed_match_count = int(
        round_matches["_is_complete"].sum()
    )
    is_round_complete = (
        round_match_count == EPL_MATCHES_PER_ROUND
        and completed_match_count == round_match_count
    )

    summary = users.copy()
    numeric_defaults = [
        "round_points",
        "base_points",
        "star_bonus_points",
        "hope_stars_used",
        "super_stars_used",
        "num_predictions",
        "num_scored",
        "exact_score_count",
        "correct_outcome_count"
    ]

    if not predictions.empty:
        match_columns = [
            "match_id",
            "home_score_for_prediction",
            "away_score_for_prediction",
            "is_finished",
            "kickoff_time_utc"
        ]

        round_predictions = predictions.merge(
            round_matches[match_columns],
            on="match_id",
            how="inner"
        )

        if not round_predictions.empty:
            pred_home = pd.to_numeric(
                round_predictions[
                    "predicted_home_score"
                ],
                errors="coerce"
            )
            pred_away = pd.to_numeric(
                round_predictions[
                    "predicted_away_score"
                ],
                errors="coerce"
            )
            actual_home = pd.to_numeric(
                round_predictions[
                    "home_score_for_prediction"
                ],
                errors="coerce"
            )
            actual_away = pd.to_numeric(
                round_predictions[
                    "away_score_for_prediction"
                ],
                errors="coerce"
            )
            is_finished = (
                round_predictions[
                    "is_finished"
                ].map(to_bool)
            )

            round_predictions["is_scored"] = (
                pred_home.notna()
                & pred_away.notna()
                & actual_home.notna()
                & actual_away.notna()
                & is_finished
            )

            round_predictions["exact_score"] = (
                round_predictions["is_scored"]
                & pred_home.eq(actual_home)
                & pred_away.eq(actual_away)
            )

            round_predictions[
                "correct_outcome"
            ] = (
                round_predictions["is_scored"]
                & (
                    (
                        pred_home.gt(pred_away)
                        & actual_home.gt(actual_away)
                    )
                    | (
                        pred_home.lt(pred_away)
                        & actual_home.lt(actual_away)
                    )
                    | (
                        pred_home.eq(pred_away)
                        & actual_home.eq(actual_away)
                    )
                )
            )

            round_predictions["points"] = (
                pd.to_numeric(
                    round_predictions["points"],
                    errors="coerce"
                )
            )
            round_predictions[
                "base_points"
            ] = pd.to_numeric(
                round_predictions["base_points"],
                errors="coerce"
            ).fillna(0)
            round_predictions[
                "star_bonus_points"
            ] = pd.to_numeric(
                round_predictions[
                    "star_bonus_points"
                ],
                errors="coerce"
            ).fillna(0)

            normalized_stars = (
                round_predictions["star_type"]
                .fillna(STAR_TYPE_NONE)
                .astype(str)
                .str.strip()
                .str.lower()
            )
            round_predictions["star_type"] = (
                normalized_stars.where(
                    normalized_stars.isin(
                        STAR_CONFIG
                    ),
                    STAR_TYPE_NONE
                )
            )

            kickoff_time = pd.to_datetime(
                round_predictions[
                    "kickoff_time_utc"
                ],
                utc=True,
                errors="coerce"
            )
            is_star_locked = (
                is_finished
                | kickoff_time.isna()
                | kickoff_time.le(
                    pd.Timestamp.now(tz="UTC")
                )
            )
            round_predictions[
                "hope_star_used"
            ] = (
                round_predictions[
                    "star_type"
                ].eq(STAR_TYPE_HOPE)
                & is_star_locked
            )
            round_predictions[
                "super_star_used"
            ] = (
                round_predictions[
                    "star_type"
                ].eq(STAR_TYPE_SUPER)
                & is_star_locked
            )

            round_summary = (
                round_predictions
                .groupby(
                    "user_id",
                    as_index=False
                )
                .agg(
                    round_points=(
                        "points",
                        lambda values: (
                            pd.to_numeric(
                                values,
                                errors="coerce"
                            )
                            .fillna(0)
                            .sum()
                        )
                    ),
                    base_points=(
                        "base_points",
                        "sum"
                    ),
                    star_bonus_points=(
                        "star_bonus_points",
                        "sum"
                    ),
                    hope_stars_used=(
                        "hope_star_used",
                        "sum"
                    ),
                    super_stars_used=(
                        "super_star_used",
                        "sum"
                    ),
                    num_predictions=(
                        "prediction_id",
                        "nunique"
                    ),
                    num_scored=(
                        "is_scored",
                        "sum"
                    ),
                    exact_score_count=(
                        "exact_score",
                        "sum"
                    ),
                    correct_outcome_count=(
                        "correct_outcome",
                        "sum"
                    )
                )
            )

            summary = summary.merge(
                round_summary,
                on="user_id",
                how="left"
            )

    for column_name in numeric_defaults:
        if column_name not in summary.columns:
            summary[column_name] = 0

        summary[column_name] = (
            pd.to_numeric(
                summary[column_name],
                errors="coerce"
            )
            .fillna(0)
            .round()
            .astype(int)
        )

    if "avatar_key" not in summary.columns:
        summary["avatar_key"] = (
            DEFAULT_AVATAR_KEY
        )
    else:
        summary["avatar_key"] = (
            summary["avatar_key"]
            .fillna(DEFAULT_AVATAR_KEY)
        )

    summary[
        "average_points_per_scored_match"
    ] = (
        summary["round_points"]
        .astype(float)
        .div(
            summary["num_scored"]
            .astype(float)
            .where(
                summary["num_scored"].ne(0)
            )
        )
        .fillna(0.0)
    )

    summary["result_prediction_rate"] = (
        summary["correct_outcome_count"]
        .astype(float)
        .div(
            summary["num_scored"]
            .astype(float)
            .where(
                summary["num_scored"].ne(0)
            )
        )
        .fillna(0.0)
    )

    summary["is_champion"] = False

    if is_round_complete:
        participating_mask = (
            summary["num_scored"].gt(0)
        )

        if bool(participating_mask.any()):
            top_round_points = int(
                summary.loc[
                    participating_mask,
                    "round_points"
                ].max()
            )
            summary["is_champion"] = (
                participating_mask
                & summary["round_points"].eq(
                    top_round_points
                )
            )

    summary["round_match_count"] = (
        round_match_count
    )
    summary[
        "completed_match_count"
    ] = completed_match_count
    summary["is_round_complete"] = (
        is_round_complete
    )

    summary = summary.sort_values(
        [
            "round_points",
            "exact_score_count",
            "correct_outcome_count",
            "display_name"
        ],
        ascending=[
            False,
            False,
            False,
            True
        ]
    ).reset_index(drop=True)

    summary["rank"] = (
        summary["round_points"]
        .rank(
            method="min",
            ascending=False
        )
        .astype(int)
    )

    return summary


def render_round_leaderboard_table(
    leaderboard: pd.DataFrame,
    season_slug: str,
    season_label: str,
    round_name: str,
    current_user_id: int | None,
    current_display_name: str
):
    total_players = len(leaderboard)
    round_token = re.sub(
        r"[^0-9A-Za-z]+",
        "_",
        str(round_name)
    ).strip("_").lower() or "round"
    season_token = season_slug.replace(
        "-",
        "_"
    )
    pagination_token = (
        f"{season_token}_{round_token}"
    )

    total_pages = max(
        1,
        (
            total_players
            + LEADERBOARD_PAGE_SIZE
            - 1
        )
        // LEADERBOARD_PAGE_SIZE
    )
    page_state_key = (
        "round_leaderboard_page_"
        + pagination_token
    )
    current_page = to_optional_int(
        st.session_state.get(page_state_key)
    )

    if current_page is None:
        current_page = 1

    current_page = min(
        max(current_page, 1),
        total_pages
    )
    st.session_state[
        page_state_key
    ] = current_page

    page_start = (
        current_page - 1
    ) * LEADERBOARD_PAGE_SIZE
    page_end = min(
        page_start + LEADERBOARD_PAGE_SIZE,
        total_players
    )
    page_df = (
        leaderboard
        .iloc[page_start:page_end]
        .copy()
        .reset_index(drop=True)
    )

    available_avatar_keys = load_avatar_catalog()
    sprite_src, sprite_columns, sprite_rows = (
        build_avatar_sprite_payload()
    )

    def safe_int(row, column_name):
        value = pd.to_numeric(
            pd.Series(
                [row.get(column_name)]
            ),
            errors="coerce"
        ).iloc[0]

        if pd.isna(value):
            return 0

        return int(round(float(value)))

    def safe_float(row, column_name):
        value = pd.to_numeric(
            pd.Series(
                [row.get(column_name)]
            ),
            errors="coerce"
        ).iloc[0]

        if pd.isna(value):
            return 0.0

        return float(value)

    def format_signed(value):
        value = int(value)
        return f"+{value}" if value > 0 else str(value)

    def build_avatar_style(avatar_key):
        normalized_avatar_key = normalize_avatar_key(
            avatar_key,
            avatar_keys=list(
                available_avatar_keys
            )
        )

        if (
            sprite_src
            and sprite_columns > 0
            and sprite_rows > 0
        ):
            sprite_position = (
                get_avatar_sprite_position(
                    normalized_avatar_key,
                    avatar_keys=(
                        available_avatar_keys
                    )
                )
            )

            if sprite_position is not None:
                x_position, y_position = (
                    sprite_position
                )

                return (
                    "background-image:url('"
                    f"{html.escape(sprite_src, quote=True)}"
                    "');"
                    "background-size:"
                    f"{sprite_columns * 100}% "
                    f"{sprite_rows * 100}%;"
                    "background-position:"
                    f"{x_position:.6f}% "
                    f"{y_position:.6f}%;"
                    "background-repeat:no-repeat;"
                )

        avatar_src = get_avatar_src(
            normalized_avatar_key,
            avatar_keys=list(
                available_avatar_keys
            )
        )

        if not avatar_src:
            return ""

        return (
            "background-image:url('"
            f"{html.escape(avatar_src, quote=True)}"
            "');"
            "background-size:cover;"
            "background-position:center;"
            "background-repeat:no-repeat;"
        )

    table_rows = []
    mobile_rows = []

    for _, row in page_df.iterrows():
        rank_value = safe_int(
            row,
            "rank"
        )
        row_user_id = to_optional_int(
            row.get("user_id")
        )
        display_name = str(
            row.get(
                "display_name",
                ""
            )
        ).strip()
        is_current_user = (
            (
                current_user_id is not None
                and row_user_id == current_user_id
            )
            or (
                current_user_id is None
                and display_name
                == current_display_name
            )
        )
        is_champion = to_bool(
            row.get("is_champion")
        )
        row_classes = [
            "epl-round-leaderboard-row"
        ]

        if is_current_user:
            row_classes.append(
                "is-current-user"
            )

        if is_champion:
            row_classes.append(
                "is-round-champion"
            )

        if rank_value in [1, 2, 3]:
            row_classes.append(
                f"is-rank-{rank_value}"
            )

        player_badge = (
            '<span class="epl-round-you-badge">'
            'Bạn'
            '</span>'
            if is_current_user
            else ""
        )
        champion_crown = (
            '<span '
            'class="round-champion-crown" '
            f'title="Vô địch {html.escape(str(round_name), quote=True)}" '
            f'aria-label="Vô địch {html.escape(str(round_name), quote=True)}">'
            '👑'
            '</span>'
            if is_champion
            else ""
        )
        avatar_style = build_avatar_style(
            row.get(
                "avatar_key",
                DEFAULT_AVATAR_KEY
            )
        )
        round_points = safe_int(
            row,
            "round_points"
        )
        base_points = safe_int(
            row,
            "base_points"
        )
        star_bonus_points = safe_int(
            row,
            "star_bonus_points"
        )
        hope_stars_used = safe_int(
            row,
            "hope_stars_used"
        )
        super_stars_used = safe_int(
            row,
            "super_stars_used"
        )
        num_scored = safe_int(
            row,
            "num_scored"
        )
        average_points = safe_float(
            row,
            "average_points_per_scored_match"
        )
        exact_score_count = safe_int(
            row,
            "exact_score_count"
        )
        correct_outcome_count = safe_int(
            row,
            "correct_outcome_count"
        )
        result_prediction_rate = safe_float(
            row,
            "result_prediction_rate"
        )
        star_bonus_class = (
            "is-negative"
            if star_bonus_points < 0
            else (
                "is-positive"
                if star_bonus_points > 0
                else "is-zero"
            )
        )
        escaped_name = html.escape(
            display_name
        )

        table_rows.append(
            f"""
            <tr class="{' '.join(row_classes)}">
                <td class="col-rank sticky-rank">
                    <span class="rank-badge">{rank_value}</span>
                </td>
                <td class="col-player sticky-player">
                    <div class="player-cell">
                        <span
                            class="player-avatar"
                            style="{avatar_style}"
                            aria-hidden="true"
                        ></span>
                        <span class="player-name">{escaped_name}</span>
                        {champion_crown}
                        {player_badge}
                    </div>
                </td>
                <td class="col-score">
                    <span class="round-score-badge">
                        {round_points}
                    </span>
                </td>
                <td class="col-breakdown">
                    <div
                        class="score-breakdown"
                        title="Điểm gốc: {base_points} • Điểm bổ trợ: {format_signed(star_bonus_points)}"
                    >
                        <span class="breakdown-item">
                            <span class="breakdown-label">Gốc</span>
                            <strong>{base_points}</strong>
                        </span>
                        <span class="breakdown-item">
                            <span class="breakdown-label">Sao</span>
                            <strong class="bonus-value {star_bonus_class}">
                                {format_signed(star_bonus_points)}
                            </strong>
                        </span>
                    </div>
                </td>
                <td class="col-boosters">
                    <div class="boosters-cell">
                        <span
                            class="star-used hope-star"
                            title="Ngôi sao hy vọng đã dùng trong vòng"
                        >
                            ⭐ {hope_stars_used}
                        </span>
                        <span
                            class="star-used super-star"
                            title="Siêu sao đã dùng trong vòng"
                        >
                            ✨ {super_stars_used}
                        </span>
                    </div>
                </td>
                <td class="col-matches">{num_scored}</td>
                <td class="col-average average-value">
                    {average_points:.1f}
                </td>
                <td class="col-exact">{exact_score_count}</td>
                <td class="col-outcome">
                    {correct_outcome_count}
                </td>
                <td class="col-rate percentage-value">
                    {result_prediction_rate * 100:.1f}%
                </td>
            </tr>
            """
        )

        mobile_rows.append(
            f"""
            <article class="epl-round-mobile-row {' '.join(row_classes)}">
                <div class="epl-round-mobile-main">
                    <span
                        class="epl-round-mobile-rank"
                        aria-label="Hạng {rank_value}"
                    >
                        {rank_value}
                    </span>

                    <span
                        class="epl-round-mobile-avatar"
                        style="{avatar_style}"
                        aria-hidden="true"
                    ></span>

                    <div class="epl-round-mobile-player">
                        <div class="epl-round-mobile-name-line">
                            <span class="epl-round-mobile-name">
                                {escaped_name}
                            </span>
                            {champion_crown}
                            {player_badge}
                        </div>

                        <span class="epl-round-mobile-meta">
                            {num_scored} trận · TB/trận {average_points:.1f}
                        </span>
                    </div>

                    <div
                        class="epl-round-mobile-score"
                        aria-label="{round_points} điểm vòng"
                    >
                        <strong>{round_points}</strong>
                        <span>điểm</span>
                    </div>
                </div>

                <div class="epl-round-mobile-stats">
                    <span class="epl-round-mobile-stat is-breakdown">
                        <small>Chi tiết điểm</small>
                        <strong
                            class="epl-round-mobile-breakdown"
                            aria-label="Điểm gốc {base_points}, điểm bổ trợ {format_signed(star_bonus_points)}"
                        >
                            <b>Gốc {base_points}</b>
                            <b class="{star_bonus_class}">
                                Sao {format_signed(star_bonus_points)}
                            </b>
                        </strong>
                    </span>
                    <span class="epl-round-mobile-stat">
                        <small>Bổ trợ đã dùng</small>
                        <strong class="epl-round-mobile-boosters">
                            <b>⭐ {hope_stars_used}</b>
                            <b>✨ {super_stars_used}</b>
                        </strong>
                    </span>
                    <span class="epl-round-mobile-stat">
                        <small>Hiệu quả dự đoán</small>
                        <strong
                            class="epl-round-mobile-accuracy"
                            aria-label="Đúng tỉ số {exact_score_count}, đúng kết quả {correct_outcome_count}, tỷ lệ đúng {result_prediction_rate * 100:.1f}%"
                        >
                            <b>Tỉ số {exact_score_count}</b>
                            <b>Kết quả {correct_outcome_count}</b>
                            <b>{result_prediction_rate * 100:.1f}%</b>
                        </strong>
                    </span>
                </div>
            </article>
            """
        )

    first_row = leaderboard.iloc[0]
    round_match_count = safe_int(
        first_row,
        "round_match_count"
    )
    completed_match_count = safe_int(
        first_row,
        "completed_match_count"
    )
    is_round_complete = to_bool(
        first_row.get("is_round_complete")
    )

    if is_round_complete:
        status_label = "Đã chốt"
        status_class = "is-complete"
    elif completed_match_count > 0:
        status_label = "Đang diễn ra"
        status_class = "is-live"
    else:
        status_label = "Chưa có kết quả"
        status_class = "is-upcoming"

    table_html = f"""
    <style>
    .epl-round-leaderboard-card {{
        overflow: hidden;
        border: 1px solid rgba(7,17,31,0.10);
        border-radius: 18px;
        background: #FFFFFF;
        box-shadow: 0 12px 30px rgba(7,17,31,0.07);
    }}

    .epl-round-leaderboard-toolbar {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
        padding: 13px 16px;
        color: #EAF2F8;
        border-bottom: 3px solid #F5C542;
        background:
            linear-gradient(
                105deg,
                #07111F 0%,
                #0A2136 62%,
                #12324B 100%
            );
    }}

    .epl-round-leaderboard-toolbar-left,
    .epl-round-leaderboard-toolbar-right {{
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 7px;
        min-width: 0;
    }}

    .epl-round-chip {{
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 4px 10px;
        border: 1px solid rgba(245,197,66,0.42);
        border-radius: 999px;
        color: #F8DA78;
        background: rgba(245,197,66,0.10);
        font-size: 12px;
        font-weight: 900;
        letter-spacing: 0.025em;
        white-space: nowrap;
    }}

    .epl-round-progress {{
        color: rgba(234,242,248,0.76);
        font-size: 12px;
        font-weight: 750;
        white-space: nowrap;
    }}

    .epl-round-status {{
        display: inline-flex;
        align-items: center;
        min-height: 25px;
        padding: 3px 8px;
        border: 1px solid transparent;
        border-radius: 999px;
        font-size: 10px;
        font-weight: 900;
        letter-spacing: 0.035em;
        white-space: nowrap;
    }}

    .epl-round-status.is-complete {{
        color: #CFF9DA;
        border-color: rgba(86,205,126,0.28);
        background: rgba(43,151,80,0.16);
    }}

    .epl-round-status.is-live {{
        color: #FFE49A;
        border-color: rgba(245,197,66,0.30);
        background: rgba(245,197,66,0.13);
    }}

    .epl-round-status.is-upcoming {{
        color: #D6E4EF;
        border-color: rgba(214,228,239,0.20);
        background: rgba(214,228,239,0.08);
    }}

    .epl-round-scroll-hint {{
        color: rgba(234,242,248,0.68);
        font-size: 10px;
        font-weight: 750;
        white-space: nowrap;
    }}

    .epl-round-leaderboard-scroll {{
        width: 100%;
        overflow-x: auto;
        overflow-y: hidden;
        overscroll-behavior-inline: contain;
        scrollbar-color: #A9BAC8 #EEF3F7;
        scrollbar-width: thin;
    }}

    .epl-round-leaderboard-scroll::-webkit-scrollbar {{
        height: 8px;
    }}

    .epl-round-leaderboard-scroll::-webkit-scrollbar-track {{
        background: #EEF3F7;
    }}

    .epl-round-leaderboard-scroll::-webkit-scrollbar-thumb {{
        border: 2px solid #EEF3F7;
        border-radius: 999px;
        background: #A9BAC8;
    }}

    .epl-round-leaderboard-table {{
        width: 100%;
        min-width: 1080px;
        border-spacing: 0;
        border-collapse: separate;
        table-layout: fixed;
        color: #162536;
        background: #FFFFFF;
        font-size: 13px;
    }}

    .epl-round-leaderboard-table th,
    .epl-round-leaderboard-table td {{
        height: 54px;
        padding: 9px 11px;
        border-left: 0 !important;
        border-right: 0 !important;
        border-bottom: 1px solid #E5ECF2;
        text-align: center;
        vertical-align: middle;
        white-space: nowrap;
    }}

    .epl-round-leaderboard-table thead th {{
        position: sticky;
        top: 0;
        z-index: 5;
        height: 52px;
        color: #EAF2F8;
        background: #091827;
        font-size: 11px;
        font-weight: 850;
        line-height: 1.25;
    }}

    .epl-round-leaderboard-table tbody td {{
        background: #FFFFFF;
        font-weight: 720;
        transition: background-color 140ms ease;
    }}

    .epl-round-leaderboard-table tbody tr:nth-child(even) td {{
        background: #F7FAFC;
    }}

    .epl-round-leaderboard-table tbody tr:hover td {{
        background: #F1F7FB;
    }}

    .epl-round-leaderboard-table tbody tr:last-child td {{
        border-bottom: 0;
    }}

    .epl-round-leaderboard-table tbody tr.is-current-user td {{
        color: #07111F;
        background: #E5F4FB;
        font-weight: 820;
    }}

    .epl-round-leaderboard-table tbody tr.is-round-champion td {{
        background: #FFF9E8;
    }}

    .epl-round-leaderboard-table
    tbody tr.is-round-champion.is-current-user td {{
        background:
            linear-gradient(
                90deg,
                #E5F4FB,
                #FFF9E8
            );
    }}

    .epl-round-leaderboard-table .col-rank {{
        width: 64px;
        min-width: 64px;
        max-width: 64px;
    }}

    .epl-round-leaderboard-table .col-player {{
        width: 226px;
        min-width: 226px;
        max-width: 226px;
        text-align: left;
    }}

    .epl-round-leaderboard-table .col-score {{ width: 86px; }}
    .epl-round-leaderboard-table .col-breakdown {{ width: 150px; }}
    .epl-round-leaderboard-table .col-boosters {{ width: 126px; }}
    .epl-round-leaderboard-table .col-matches {{ width: 66px; }}
    .epl-round-leaderboard-table .col-average {{ width: 82px; }}
    .epl-round-leaderboard-table .col-exact {{ width: 84px; }}
    .epl-round-leaderboard-table .col-outcome {{ width: 98px; }}
    .epl-round-leaderboard-table .col-rate {{ width: 86px; }}

    .epl-round-leaderboard-table .sticky-rank {{
        position: sticky;
        left: 0;
        z-index: 3;
    }}

    .epl-round-leaderboard-table .sticky-player {{
        position: sticky;
        left: 64px;
        z-index: 3;
    }}

    .epl-round-leaderboard-table thead .sticky-rank,
    .epl-round-leaderboard-table thead .sticky-player {{
        z-index: 8;
        background: #07111F;
    }}

    .epl-round-leaderboard-card .rank-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 30px;
        height: 30px;
        border: 1px solid #D9E3EA;
        border-radius: 50%;
        color: #405467;
        background: #F4F7FA;
        font-size: 12px;
        font-weight: 950;
    }}

    .epl-round-leaderboard-card .is-rank-1 .rank-badge {{
        color: #704B00;
        border-color: #E9B91F;
        background: linear-gradient(145deg,#FFE485,#F5C542);
    }}

    .epl-round-leaderboard-card .is-rank-2 .rank-badge {{
        color: #344557;
        border-color: #B7C5D1;
        background: linear-gradient(145deg,#F1F5F9,#CBD5E1);
    }}

    .epl-round-leaderboard-card .is-rank-3 .rank-badge {{
        color: #562609;
        border-color: #B9652F;
        background: linear-gradient(145deg,#E8A06C,#C8753D);
    }}

    .epl-round-leaderboard-card .player-cell {{
        display: flex;
        align-items: center;
        min-width: 0;
    }}

    .epl-round-leaderboard-card .player-avatar {{
        flex: 0 0 auto;
        display: inline-block;
        width: 32px;
        height: 32px;
        margin-right: 9px;
        border: 2px solid #FFFFFF;
        border-radius: 50%;
        background-color: #DDE7EF;
        box-shadow: 0 2px 7px rgba(7,17,31,0.16);
    }}

    .epl-round-leaderboard-card .player-name {{
        min-width: 0;
        overflow: hidden;
        color: #152638;
        font-weight: 850;
        text-overflow: ellipsis;
    }}

    .round-champion-crown {{
        flex: 0 0 auto;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        margin-left: 6px;
        font-size: 17px;
        line-height: 1;
        filter: drop-shadow(0 1px 2px rgba(142,94,0,0.22));
    }}

    .epl-round-you-badge {{
        flex: 0 0 auto;
        display: inline-flex;
        align-items: center;
        margin-left: 7px;
        padding: 2px 6px;
        color: #0A5274;
        border: 1px solid rgba(14,116,144,0.25);
        border-radius: 999px;
        background: rgba(14,116,144,0.08);
        font-size: 9px;
        font-weight: 950;
        text-transform: uppercase;
    }}

    .round-score-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 42px;
        height: 30px;
        padding: 0 9px;
        color: #07111F;
        border: 1px solid #E8BD31;
        border-radius: 9px;
        background: #F8D863;
        font-size: 14px;
        font-weight: 950;
    }}

    .epl-round-leaderboard-card .score-breakdown {{
        display: grid;
        grid-template-columns: repeat(2,minmax(0,1fr));
        align-items: center;
        gap: 7px;
        width: 100%;
    }}

    .epl-round-leaderboard-card .breakdown-item {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
        min-width: 0;
    }}

    .epl-round-leaderboard-card .breakdown-label {{
        color: #7A8C9C;
        font-size: 9px;
        font-weight: 800;
        text-transform: uppercase;
    }}

    .epl-round-leaderboard-card .bonus-value {{
        font-weight: 900;
    }}

    .epl-round-leaderboard-card .bonus-value.is-positive {{
        color: #A65B08;
    }}

    .epl-round-leaderboard-card .bonus-value.is-negative {{
        color: #C73535;
    }}

    .epl-round-leaderboard-card .bonus-value.is-zero {{
        color: #738496;
    }}

    .epl-round-leaderboard-card .boosters-cell {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 5px;
    }}

    .star-used {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 48px;
        height: 27px;
        padding: 0 6px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 950;
    }}

    .star-used.hope-star {{
        color: #805500;
        border: 1px solid rgba(222,174,24,0.35);
        background: rgba(245,197,66,0.15);
    }}

    .star-used.super-star {{
        color: #50418F;
        border: 1px solid rgba(107,88,190,0.24);
        background: rgba(124,105,210,0.10);
    }}

    .epl-round-leaderboard-card .average-value {{
        color: #0E7490;
        font-weight: 900 !important;
    }}

    .epl-round-leaderboard-card .percentage-value {{
        color: #445A6D;
        font-variant-numeric: tabular-nums;
    }}

    .epl-round-leaderboard-footer {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 10px 16px;
        color: #66798B;
        border-top: 1px solid #E5ECF2;
        background: #F8FAFC;
        font-size: 11px;
        font-weight: 700;
    }}

    .epl-round-leaderboard-footer strong {{
        color: #1C3348;
        font-weight: 900;
    }}

    .epl-round-leaderboard-mobile {{
        display: none;
    }}

    @media (max-width: 768px) {{
        .epl-round-leaderboard-card {{
            border-radius: 16px;
            box-shadow: 0 8px 24px rgba(7,17,31,0.07);
        }}

        .epl-round-leaderboard-toolbar {{
            align-items: center;
            gap: 8px;
            padding: 10px 12px;
            border-bottom-width: 2px;
        }}

        .epl-round-leaderboard-toolbar-left {{
            gap: 5px;
        }}

        .epl-round-leaderboard-toolbar-right {{
            justify-content: flex-end;
        }}

        .epl-round-chip {{
            min-height: 24px;
            padding: 3px 8px;
            font-size: 10px;
        }}

        .epl-round-progress {{
            font-size: 10px;
        }}

        .epl-round-status {{
            min-height: 23px;
            padding: 3px 7px;
            font-size: 9px;
        }}

        .epl-round-scroll-hint {{
            display: none;
        }}

        .epl-round-leaderboard-scroll {{
            display: none;
        }}

        .epl-round-leaderboard-mobile {{
            display: block;
            background: #F5F8FB;
        }}

        .epl-round-mobile-row {{
            padding: 11px 12px 10px;
            border-bottom: 1px solid #E3EAF0;
            background: #FFFFFF;
        }}

        .epl-round-mobile-row:nth-child(even) {{
            background: #F8FAFC;
        }}

        .epl-round-mobile-row:last-child {{
            border-bottom: 0;
        }}

        .epl-round-mobile-row.is-current-user {{
            background:
                linear-gradient(
                    90deg,
                    #E6F5FB 0%,
                    #F3FAFD 100%
                );
        }}

        .epl-round-mobile-row.is-round-champion {{
            background:
                linear-gradient(
                    90deg,
                    #FFF8E1 0%,
                    #FFFDF5 100%
                );
        }}

        .epl-round-mobile-row.is-current-user.is-round-champion {{
            background:
                linear-gradient(
                    90deg,
                    #E7F5FA 0%,
                    #FFF8E2 100%
                );
        }}

        .epl-round-mobile-main {{
            display: grid;
            grid-template-columns: 30px 36px minmax(0, 1fr) auto;
            align-items: center;
            gap: 8px;
            min-width: 0;
        }}

        .epl-round-mobile-rank {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border: 1px solid #D7E1E8;
            border-radius: 50%;
            color: #425669;
            background: #F2F6F9;
            font-size: 11px;
            font-weight: 950;
        }}

        .epl-round-mobile-row.is-rank-1
        .epl-round-mobile-rank {{
            color: #704B00;
            border-color: #E9B91F;
            background: linear-gradient(145deg,#FFE485,#F5C542);
        }}

        .epl-round-mobile-row.is-rank-2
        .epl-round-mobile-rank {{
            color: #344557;
            border-color: #B7C5D1;
            background: linear-gradient(145deg,#F1F5F9,#CBD5E1);
        }}

        .epl-round-mobile-row.is-rank-3
        .epl-round-mobile-rank {{
            color: #562609;
            border-color: #B9652F;
            background: linear-gradient(145deg,#E8A06C,#C8753D);
        }}

        .epl-round-mobile-avatar {{
            display: inline-block;
            width: 34px;
            height: 34px;
            border: 2px solid #FFFFFF;
            border-radius: 50%;
            background-color: #DDE7EF;
            box-shadow: 0 2px 7px rgba(7,17,31,0.14);
        }}

        .epl-round-mobile-player {{
            min-width: 0;
        }}

        .epl-round-mobile-name-line {{
            display: flex;
            align-items: center;
            min-width: 0;
        }}

        .epl-round-mobile-name {{
            min-width: 0;
            overflow: hidden;
            color: #142638;
            font-size: 12px;
            font-weight: 900;
            line-height: 1.25;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}

        .epl-round-mobile-name-line
        .round-champion-crown {{
            margin-left: 4px;
            font-size: 15px;
        }}

        .epl-round-mobile-name-line
        .epl-round-you-badge {{
            margin-left: 5px;
            padding: 1px 5px;
            font-size: 7px;
        }}

        .epl-round-mobile-meta {{
            display: block;
            margin-top: 2px;
            color: #788A9A;
            font-size: 9.5px;
            font-weight: 720;
            line-height: 1.2;
        }}

        .epl-round-mobile-score {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-width: 49px;
            min-height: 41px;
            padding: 4px 7px;
            border: 1px solid #E8BD31;
            border-radius: 10px;
            color: #07111F;
            background: #F8D863;
        }}

        .epl-round-mobile-score strong {{
            font-size: 16px;
            font-weight: 950;
            line-height: 1;
        }}

        .epl-round-mobile-score span {{
            margin-top: 2px;
            font-size: 8px;
            font-weight: 850;
            line-height: 1;
            text-transform: uppercase;
        }}

        .epl-round-mobile-stats {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin-top: 8px;
            padding-top: 7px;
            border-top: 1px solid rgba(136,157,174,0.18);
        }}

        .epl-round-mobile-stats > span {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 3px;
            min-width: 0;
            min-height: 32px;
            padding: 1px 5px;
            border-right: 1px solid rgba(136,157,174,0.17);
        }}

        .epl-round-mobile-stats > span:nth-child(3n) {{
            border-right: 0;
        }}

        .epl-round-mobile-stats small {{
            width: 100%;
            overflow: hidden;
            color: #758797;
            font-size: 8.5px;
            font-weight: 760;
            line-height: 1.1;
            text-align: center;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}

        .epl-round-mobile-stats strong {{
            color: #17324A;
            font-size: 11px;
            font-weight: 950;
            line-height: 1.1;
        }}

        .epl-round-mobile-breakdown,
        .epl-round-mobile-boosters,
        .epl-round-mobile-accuracy {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 5px;
            min-width: 0;
            white-space: nowrap;
        }}

        .epl-round-mobile-breakdown b,
        .epl-round-mobile-boosters b,
        .epl-round-mobile-accuracy b {{
            font-size: 9px;
            font-weight: 900;
        }}

        .epl-round-mobile-breakdown .is-positive {{
            color: #16804A;
        }}

        .epl-round-mobile-breakdown .is-negative {{
            color: #C2413A;
        }}

        .epl-round-mobile-breakdown .is-zero {{
            color: #64748B;
        }}

        .epl-round-leaderboard-footer {{
            justify-content: center;
            padding: 8px 12px;
            font-size: 10px;
            text-align: center;
        }}

        .epl-round-leaderboard-footer > span:last-child {{
            display: none;
        }}
    }}
    </style>

    <div class="epl-round-leaderboard-card">
        <div class="epl-round-leaderboard-toolbar">
            <div class="epl-round-leaderboard-toolbar-left">
                <span class="epl-round-chip">
                    Mùa {html.escape(str(season_label))}
                </span>
                <span class="epl-round-chip">
                    {html.escape(str(round_name))}
                </span>
                <span class="epl-round-progress">
                    {completed_match_count}/{round_match_count}
                    trận kết thúc
                </span>
            </div>
            <div class="epl-round-leaderboard-toolbar-right">
                <span class="epl-round-status {status_class}">
                    {status_label}
                </span>
                <span class="epl-round-scroll-hint">
                    ↔ Cuộn ngang trên màn hình nhỏ
                </span>
            </div>
        </div>

        <div class="epl-round-leaderboard-scroll">
            <table class="epl-round-leaderboard-table">
                <thead>
                    <tr>
                        <th class="col-rank sticky-rank" title="Hạng trong vòng">#</th>
                        <th class="col-player sticky-player">Người chơi</th>
                        <th class="col-score" title="Tổng điểm dự đoán trong vòng, chưa gồm thưởng vô địch vòng">Điểm vòng</th>
                        <th class="col-breakdown" title="Điểm gốc và điểm bổ trợ trong vòng">Chi tiết điểm</th>
                        <th class="col-boosters" title="Số bổ trợ đã dùng trong vòng">Bổ trợ</th>
                        <th class="col-matches" title="Số trận đã chấm trong vòng">Trận</th>
                        <th class="col-average" title="Điểm trung bình mỗi trận đã chấm">Điểm TB</th>
                        <th class="col-exact">Đúng tỉ số</th>
                        <th class="col-outcome" title="Gồm cả dự đoán đúng tỉ số">Đúng kết quả</th>
                        <th class="col-rate" title="Tỷ lệ đúng kết quả trong vòng">Tỷ lệ đúng</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(table_rows)}
                </tbody>
            </table>
        </div>

        <div
            class="epl-round-leaderboard-mobile"
            aria-label="Bảng xếp hạng theo vòng trên điện thoại"
        >
            {''.join(mobile_rows)}
        </div>

        <div class="epl-round-leaderboard-footer">
            <span>
                Hiển thị
                <strong>{page_start + 1}–{page_end}</strong>
                trong
                <strong>{total_players}</strong>
                người chơi
            </span>
            <span>
                Điểm vòng không gồm
                +{ROUND_CHAMPION_BONUS_POINTS}
                điểm thưởng vô địch vòng
            </span>
        </div>
    </div>
    """

    st.html(table_html)

    st.markdown(
        """
        <style>
        div[class*="st-key-round_leaderboard_pagination_"] {
            width: 100% !important;
            max-width: 240px !important;
            margin: 12px auto 0 !important;
        }

        div[class*="st-key-round_leaderboard_pagination_"]
        .stButton > button {
            width: 40px !important;
            min-width: 40px !important;
            height: 36px !important;
            min-height: 36px !important;
            padding: 0 !important;
            color: #0D2940 !important;
            border: 1px solid rgba(13,41,64,0.18) !important;
            border-radius: 10px !important;
            background: rgba(255,255,255,0.96) !important;
            box-shadow: none !important;
            font-size: 22px !important;
            font-weight: 850 !important;
            line-height: 1 !important;
            transform: none !important;
        }

        div[class*="st-key-round_leaderboard_pagination_"]
        .stButton > button:hover:not(:disabled) {
            color: #07111F !important;
            border-color: #E0AE15 !important;
            background: #F8D863 !important;
            transform: none !important;
        }

        div[class*="st-key-round_leaderboard_pagination_"]
        .stButton > button:disabled {
            color: #AEBAC4 !important;
            border-color: #E2E8EE !important;
            background: #F4F7F9 !important;
            opacity: 1 !important;
        }

        @media (max-width: 768px) {
            div[class*="st-key-round_leaderboard_pagination_"] {
                max-width: 220px !important;
                margin-top: 10px !important;
            }

            div[class*="st-key-round_leaderboard_pagination_"]
            div[data-testid="stHorizontalBlock"] {
                display: grid !important;
                grid-template-columns: 38px minmax(90px, 1fr) 38px !important;
                gap: 9px !important;
                align-items: center !important;
            }

            div[class*="st-key-round_leaderboard_pagination_"]
            div[data-testid="stColumn"] {
                width: 100% !important;
                min-width: 0 !important;
                max-width: none !important;
                flex: none !important;
            }

            div[class*="st-key-round_leaderboard_pagination_"]
            .stButton > button {
                width: 38px !important;
                min-width: 38px !important;
                height: 34px !important;
                min-height: 34px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    with st.container(
        key=(
            "round_leaderboard_pagination_"
            + pagination_token
        )
    ):
        (
            previous_column,
            page_column,
            next_column
        ) = st.columns(
            [1, 1.8, 1]
        )

        with previous_column:
            previous_clicked = st.button(
                "‹",
                key=(
                    "round_leaderboard_page_previous_"
                    + pagination_token
                ),
                help="Trang trước",
                disabled=current_page <= 1
            )

        with page_column:
            st.markdown(
                f"""
                <div style="
                    min-height:36px;
                    display:flex;
                    align-items:center;
                    justify-content:center;
                    gap:4px;
                    color:#6A7D8F;
                    font-size:12px;
                    font-weight:800;
                    white-space:nowrap;
                ">
                    Trang
                    <span style="
                        color:#07111F;
                        font-size:14px;
                        font-weight:950;
                    ">{current_page}</span>
                    / {total_pages}
                </div>
                """,
                unsafe_allow_html=True
            )

        with next_column:
            next_clicked = st.button(
                "›",
                key=(
                    "round_leaderboard_page_next_"
                    + pagination_token
                ),
                help="Trang sau",
                disabled=current_page >= total_pages
            )

    if previous_clicked:
        st.session_state[page_state_key] = (
            current_page - 1
        )
        st.rerun()

    if next_clicked:
        st.session_state[page_state_key] = (
            current_page + 1
        )
        st.rerun()


def page_leaderboard():
    render_page_title(
        "Bảng xếp hạng",
        "Xem ai đang dẫn đầu cuộc đua dự đoán."
    )

    # Chỉ tinh chỉnh tiêu đề của trang BXH trên mobile.
    # Không có rule desktop và khối CSS chỉ được render khi đang ở trang này.
    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            .wc-page-title {
                margin: 3px 0 13px 0 !important;
            }

            .wc-page-title h2 {
                margin: 0 0 5px 0 !important;
                font-size: 23px !important;
                line-height: 1.12 !important;
                letter-spacing: -0.035em !important;
            }

            .wc-page-title p {
                margin: 0 !important;
                font-size: 12.5px !important;
                line-height: 1.4 !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    season_slug = get_selected_season_slug()
    season_label = SEASON_LABEL_BY_SLUG.get(
        season_slug,
        season_slug
    )

    score_all_predictions(season_slug)

    active_leaderboard_view = (
        render_prediction_leaderboard_view_switcher()
    )

    current_user = st.session_state["user"]
    current_user_id = to_optional_int(
        current_user.get("user_id")
    )
    current_display_name = str(
        current_user.get("display_name", "")
    ).strip()

    if active_leaderboard_view == "round":
        matches = load_matches(season_slug)
        selected_round = (
            render_prediction_round_filter(
                matches=matches,
                season_slug=season_slug
            )
        )

        if selected_round is None:
            st.info(
                "Chưa có dữ liệu vòng đấu "
                "cho mùa giải này."
            )
            return

        round_leaderboard = (
            build_round_leaderboard_df(
                season_slug=season_slug,
                round_name=selected_round
            )
        )

        if round_leaderboard.empty:
            st.info(
                "Chưa có dữ liệu để tính "
                "bảng xếp hạng vòng."
            )
            return

        render_round_leaderboard_table(
            leaderboard=round_leaderboard,
            season_slug=season_slug,
            season_label=season_label,
            round_name=selected_round,
            current_user_id=current_user_id,
            current_display_name=(
                current_display_name
            )
        )
        return

    leaderboard = build_leaderboard_df(season_slug)

    if leaderboard.empty:
        st.info("Chưa có dữ liệu người chơi.")
        return

    if "avatar_key" not in leaderboard.columns:
        leaderboard["avatar_key"] = DEFAULT_AVATAR_KEY

    bonus_by_user = get_all_daily_checkin_bonus_counts_cached()
    user_ids = leaderboard["user_id"].astype(int)

    hope_totals = user_ids.map(
        lambda user_id: (
            HOPE_STARS_PER_USER
            + int(
                bonus_by_user.get(
                    int(user_id),
                    {}
                ).get("hope_bonus", 0)
            )
        )
    ).astype(int)

    super_totals = user_ids.map(
        lambda user_id: (
            SUPER_STARS_PER_USER
            + int(
                bonus_by_user.get(
                    int(user_id),
                    {}
                ).get("super_bonus", 0)
            )
        )
    ).astype(int)

    hope_used = pd.to_numeric(
        leaderboard["hope_stars_used"],
        errors="coerce"
    ).fillna(0).astype(int)

    super_used = pd.to_numeric(
        leaderboard["super_stars_used"],
        errors="coerce"
    ).fillna(0).astype(int)

    leaderboard["hope_star_display"] = (
        (hope_totals - hope_used).clip(lower=0).astype(str)
        + "/"
        + hope_totals.astype(str)
    )

    leaderboard["super_star_display"] = (
        (super_totals - super_used).clip(lower=0).astype(str)
        + "/"
        + super_totals.astype(str)
    )

    total_players = len(leaderboard)
    total_pages = max(
        1,
        (
            total_players
            + LEADERBOARD_PAGE_SIZE
            - 1
        )
        // LEADERBOARD_PAGE_SIZE
    )

    page_state_key = (
        f"leaderboard_page_{season_slug}"
    )

    current_page = to_optional_int(
        st.session_state.get(page_state_key)
    )

    if current_page is None:
        current_page = 1

    current_page = min(
        max(current_page, 1),
        total_pages
    )
    st.session_state[page_state_key] = current_page

    page_start = (
        current_page - 1
    ) * LEADERBOARD_PAGE_SIZE
    page_end = min(
        page_start + LEADERBOARD_PAGE_SIZE,
        total_players
    )

    page_df = (
        leaderboard
        .iloc[page_start:page_end]
        .copy()
        .reset_index(drop=True)
    )

    available_avatar_keys = load_avatar_catalog()
    sprite_src, sprite_columns, sprite_rows = (
        build_avatar_sprite_payload()
    )

    def safe_int(row, column_name):
        value = pd.to_numeric(
            pd.Series([row.get(column_name)]),
            errors="coerce"
        ).iloc[0]

        if pd.isna(value):
            return 0

        return int(round(float(value)))

    def safe_float(row, column_name):
        value = pd.to_numeric(
            pd.Series([row.get(column_name)]),
            errors="coerce"
        ).iloc[0]

        if pd.isna(value):
            return 0.0

        return float(value)

    def format_signed(value):
        value = int(value)

        if value > 0:
            return f"+{value}"

        return str(value)

    def build_avatar_style(avatar_key):
        normalized_avatar_key = normalize_avatar_key(
            avatar_key,
            avatar_keys=list(available_avatar_keys)
        )

        if (
            sprite_src
            and sprite_columns > 0
            and sprite_rows > 0
        ):
            sprite_position = get_avatar_sprite_position(
                normalized_avatar_key,
                avatar_keys=available_avatar_keys
            )

            if sprite_position is not None:
                x_position, y_position = sprite_position

                return (
                    "background-image:url('"
                    f"{html.escape(sprite_src, quote=True)}"
                    "');"
                    "background-size:"
                    f"{sprite_columns * 100}% "
                    f"{sprite_rows * 100}%;"
                    "background-position:"
                    f"{x_position:.6f}% "
                    f"{y_position:.6f}%;"
                    "background-repeat:no-repeat;"
                )

        avatar_src = get_avatar_src(
            normalized_avatar_key,
            avatar_keys=list(available_avatar_keys)
        )

        if not avatar_src:
            return ""

        return (
            "background-image:url('"
            f"{html.escape(avatar_src, quote=True)}"
            "');"
            "background-size:cover;"
            "background-position:center;"
            "background-repeat:no-repeat;"
        )

    table_rows = []
    mobile_rows = []

    for _, row in page_df.iterrows():
        rank_value = safe_int(row, "rank")
        row_user_id = to_optional_int(
            row.get("user_id")
        )
        display_name = str(
            row.get("display_name", "")
        ).strip()

        is_current_user = (
            (
                current_user_id is not None
                and row_user_id == current_user_id
            )
            or (
                current_user_id is None
                and display_name == current_display_name
            )
        )

        row_classes = [
            "epl-leaderboard-row"
        ]

        if is_current_user:
            row_classes.append("is-current-user")

        if rank_value in [1, 2, 3]:
            row_classes.append(
                f"is-rank-{rank_value}"
            )

        player_badge = (
            '<span class="epl-you-badge">Bạn</span>'
            if is_current_user
            else ""
        )

        avatar_style = build_avatar_style(
            row.get(
                "avatar_key",
                DEFAULT_AVATAR_KEY
            )
        )

        total_points = safe_int(
            row,
            "total_points"
        )
        base_points = safe_int(
            row,
            "base_points"
        )
        star_bonus_points = safe_int(
            row,
            "star_bonus_points"
        )
        round_bonus_points = safe_int(
            row,
            "round_champion_bonus_points"
        )
        round_champion_count = safe_int(
            row,
            "round_champion_count"
        )
        num_scored = safe_int(
            row,
            "num_scored"
        )
        average_points = safe_float(
            row,
            "average_points_per_scored_match"
        )
        exact_score_count = safe_int(
            row,
            "exact_score_count"
        )
        correct_outcome_count = safe_int(
            row,
            "correct_outcome_count"
        )
        result_prediction_rate = safe_float(
            row,
            "result_prediction_rate"
        )

        star_bonus_class = (
            "is-negative"
            if star_bonus_points < 0
            else (
                "is-positive"
                if star_bonus_points > 0
                else "is-zero"
            )
        )

        escaped_name = html.escape(
            display_name
        )
        escaped_hope_display = html.escape(
            str(
                row.get(
                    "hope_star_display",
                    "0/0"
                )
            )
        )
        escaped_super_display = html.escape(
            str(
                row.get(
                    "super_star_display",
                    "0/0"
                )
            )
        )

        table_rows.append(
            f"""
            <tr class="{' '.join(row_classes)}">
                <td class="col-rank sticky-rank">
                    <span class="rank-badge">{rank_value}</span>
                </td>
                <td class="col-player sticky-player">
                    <div class="player-cell">
                        <span
                            class="player-avatar"
                            style="{avatar_style}"
                            aria-hidden="true"
                        ></span>
                        <span class="player-name">{escaped_name}</span>
                        {player_badge}
                    </div>
                </td>
                <td class="col-score">
                    <span class="total-score-badge">{total_points}</span>
                </td>
                <td class="col-breakdown">
                    <div
                        class="score-breakdown"
                        title="Điểm gốc: {base_points} • Thưởng sao: {format_signed(star_bonus_points)} • Thưởng vòng: {format_signed(round_bonus_points)}"
                    >
                        <span class="breakdown-item">
                            <span class="breakdown-label">Gốc</span>
                            <strong>{base_points}</strong>
                        </span>
                        <span class="breakdown-item">
                            <span class="breakdown-label">Sao</span>
                            <strong class="bonus-value {star_bonus_class}">
                                {format_signed(star_bonus_points)}
                            </strong>
                        </span>
                        <span class="breakdown-item">
                            <span class="breakdown-label">Vòng</span>
                            <strong class="round-bonus-value">
                                {format_signed(round_bonus_points)}
                            </strong>
                        </span>
                    </div>
                </td>
                <td class="col-round-titles">
                    <span class="round-title-count">
                        {round_champion_count}
                    </span>
                </td>
                <td class="col-boosters">
                    <div class="boosters-cell">
                        <span
                            class="star-balance hope-star"
                            title="Ngôi sao hy vọng còn lại"
                        >
                            ⭐ {escaped_hope_display}
                        </span>
                        <span
                            class="star-balance super-star"
                            title="Siêu sao còn lại"
                        >
                            ✨ {escaped_super_display}
                        </span>
                    </div>
                </td>
                <td class="col-matches">{num_scored}</td>
                <td class="col-average average-value">
                    {average_points:.1f}
                </td>
                <td class="col-exact">{exact_score_count}</td>
                <td class="col-outcome">{correct_outcome_count}</td>
                <td class="col-rate percentage-value">
                    {result_prediction_rate * 100:.1f}%
                </td>
            </tr>
            """
        )

        champion_meta = (
            f'<span class="epl-mobile-title-meta">'
            f'👑 {round_champion_count} VĐ vòng'
            f'</span>'
            if round_champion_count > 0
            else ""
        )

        mobile_rows.append(
            f"""
            <article class="epl-mobile-row {' '.join(row_classes)}">
                <div class="epl-mobile-main">
                    <span
                        class="epl-mobile-rank"
                        aria-label="Hạng {rank_value}"
                    >
                        {rank_value}
                    </span>

                    <span
                        class="epl-mobile-avatar"
                        style="{avatar_style}"
                        aria-hidden="true"
                    ></span>

                    <div class="epl-mobile-player">
                        <div class="epl-mobile-name-line">
                            <span class="epl-mobile-name">
                                {escaped_name}
                            </span>
                            {player_badge}
                        </div>

                        <div class="epl-mobile-meta">
                            <span>
                                {num_scored} trận · TB/trận {average_points:.1f}
                            </span>
                            {champion_meta}
                        </div>
                    </div>

                    <div
                        class="epl-mobile-score"
                        aria-label="{total_points} điểm"
                    >
                        <strong>{total_points}</strong>
                        <span>điểm</span>
                    </div>
                </div>

                <div class="epl-mobile-stats">
                    <span class="epl-mobile-stat is-breakdown">
                        <small>Chi tiết điểm</small>
                        <strong
                            class="epl-mobile-breakdown"
                            aria-label="Điểm gốc {base_points}, thưởng sao {format_signed(star_bonus_points)}, thưởng vòng {format_signed(round_bonus_points)}"
                        >
                            <b>Gốc {base_points}</b>
                            <b class="{star_bonus_class}">
                                Sao {format_signed(star_bonus_points)}
                            </b>
                            <b class="is-round-bonus">
                                Vòng {format_signed(round_bonus_points)}
                            </b>
                        </strong>
                    </span>
                    <span class="epl-mobile-stat">
                        <small>Bổ trợ còn lại</small>
                        <strong class="epl-mobile-boosters">
                            <b>⭐ {escaped_hope_display}</b>
                            <b>✨ {escaped_super_display}</b>
                        </strong>
                    </span>
                    <span class="epl-mobile-stat">
                        <small>Hiệu quả dự đoán</small>
                        <strong
                            class="epl-mobile-accuracy"
                            aria-label="Đúng tỉ số {exact_score_count}, đúng kết quả {correct_outcome_count}, tỷ lệ đúng {result_prediction_rate * 100:.1f}%"
                        >
                            <b>Tỉ số {exact_score_count}</b>
                            <b>Kết quả {correct_outcome_count}</b>
                            <b>{result_prediction_rate * 100:.1f}%</b>
                        </strong>
                    </span>
                </div>
            </article>
            """
        )

    table_html = f"""
    <style>
    .epl-leaderboard-card {{
        overflow: hidden;
        background:
            linear-gradient(
                135deg,
                rgba(255,255,255,0.99),
                rgba(248,250,252,0.97)
            );
        border: 1px solid rgba(7,17,31,0.10);
        border-radius: 18px;
        box-shadow:
            0 12px 30px rgba(7,17,31,0.07);
    }}

    .epl-leaderboard-toolbar {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 14px 16px;
        color: #EAF2F8;
        background:
            linear-gradient(
                105deg,
                #07111F 0%,
                #0A2136 62%,
                #12324B 100%
            );
        border-bottom:
            3px solid #F5C542;
    }}

    .epl-leaderboard-toolbar-left {{
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
        min-width: 0;
    }}

    .epl-leaderboard-season {{
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 4px 10px;
        border: 1px solid rgba(245,197,66,0.42);
        border-radius: 999px;
        color: #F8DA78;
        background: rgba(245,197,66,0.10);
        font-size: 12px;
        font-weight: 900;
        letter-spacing: 0.035em;
        white-space: nowrap;
    }}

    .epl-leaderboard-count {{
        color: rgba(234,242,248,0.76);
        font-size: 12px;
        font-weight: 700;
        white-space: nowrap;
    }}

    .epl-leaderboard-scroll-hint {{
        color: rgba(234,242,248,0.72);
        font-size: 11px;
        font-weight: 700;
        white-space: nowrap;
    }}

    .epl-leaderboard-scroll {{
        position: relative;
        width: 100%;
        overflow-x: auto;
        overflow-y: hidden;
        overscroll-behavior-inline: contain;
        scrollbar-color: #A9BAC8 #EEF3F7;
        scrollbar-width: thin;
    }}

    .epl-leaderboard-scroll::-webkit-scrollbar {{
        height: 8px;
    }}

    .epl-leaderboard-scroll::-webkit-scrollbar-track {{
        background: #EEF3F7;
    }}

    .epl-leaderboard-scroll::-webkit-scrollbar-thumb {{
        background: #A9BAC8;
        border: 2px solid #EEF3F7;
        border-radius: 999px;
    }}

    .epl-leaderboard-table {{
        width: 100%;
        min-width: 1160px;
        border-spacing: 0;
        border-collapse: separate;
        table-layout: fixed;
        color: #162536;
        background: #FFFFFF;
        font-size: 13px;
    }}

    .epl-leaderboard-table th,
    .epl-leaderboard-table td {{
        height: 54px;
        padding: 9px 11px;
        border-left: 0 !important;
        border-right: 0 !important;
        border-bottom: 1px solid #E5ECF2;
        text-align: center;
        vertical-align: middle;
        white-space: nowrap;
    }}

    .epl-leaderboard-table thead th {{
        position: sticky;
        top: 0;
        z-index: 5;
        height: 52px;
        color: #EAF2F8;
        background: #091827;
        font-size: 11px;
        font-weight: 850;
        line-height: 1.25;
        letter-spacing: 0.015em;
    }}

    .epl-leaderboard-table tbody tr:last-child td {{
        border-bottom: 0;
    }}

    .epl-leaderboard-table tbody td {{
        background: #FFFFFF;
        font-weight: 720;
        transition:
            background-color 140ms ease,
            color 140ms ease;
    }}

    .epl-leaderboard-table tbody tr:nth-child(even) td {{
        background: #F7FAFC;
    }}

    .epl-leaderboard-table tbody tr:hover td {{
        background: #F1F7FB;
    }}

    .epl-leaderboard-table tbody tr.is-current-user td {{
        background: #E5F4FB;
        color: #07111F;
        font-weight: 820;
    }}

    .epl-leaderboard-table tbody tr.is-current-user:hover td {{
        background: #DCEFF8;
    }}

    .epl-leaderboard-table .col-rank {{
        width: 64px;
        min-width: 64px;
        max-width: 64px;
    }}

    .epl-leaderboard-table .col-player {{
        width: 220px;
        min-width: 220px;
        max-width: 220px;
        text-align: left;
    }}

    .epl-leaderboard-table .col-score {{
        width: 76px;
    }}

    .epl-leaderboard-table .col-breakdown {{
        width: 190px;
    }}

    .epl-leaderboard-table .col-round-titles {{
        width: 78px;
    }}

    .epl-leaderboard-table .col-boosters {{
        width: 132px;
    }}

    .epl-leaderboard-table .col-matches {{
        width: 64px;
    }}

    .epl-leaderboard-table .col-average {{
        width: 82px;
    }}

    .epl-leaderboard-table .col-exact {{
        width: 82px;
    }}

    .epl-leaderboard-table .col-outcome {{
        width: 96px;
    }}

    .epl-leaderboard-table .col-rate {{
        width: 82px;
    }}

    .epl-leaderboard-table .sticky-rank {{
        position: sticky;
        left: 0;
        z-index: 3;
    }}

    .epl-leaderboard-table .sticky-player {{
        position: sticky;
        left: 64px;
        z-index: 3;
    }}

    .epl-leaderboard-table thead .sticky-rank,
    .epl-leaderboard-table thead .sticky-player {{
        z-index: 8;
        background: #07111F;
    }}

    .rank-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 30px;
        height: 30px;
        border: 1px solid #D9E3EA;
        border-radius: 50%;
        color: #405467;
        background: #F4F7FA;
        font-size: 12px;
        font-weight: 950;
    }}

    .is-rank-1 .rank-badge {{
        color: #704B00;
        border-color: #E9B91F;
        background:
            linear-gradient(
                145deg,
                #FFE485,
                #F5C542
            );
    }}

    .is-rank-2 .rank-badge {{
        color: #344557;
        border-color: #B7C5D1;
        background:
            linear-gradient(
                145deg,
                #F1F5F9,
                #CBD5E1
            );
    }}

    .is-rank-3 .rank-badge {{
        color: #562609;
        border-color: #B9652F;
        background:
            linear-gradient(
                145deg,
                #E8A06C,
                #C8753D
            );
    }}

    .player-cell {{
        display: flex;
        align-items: center;
        min-width: 0;
    }}

    .player-avatar {{
        flex: 0 0 auto;
        display: inline-block;
        width: 32px;
        height: 32px;
        margin-right: 9px;
        border: 2px solid #FFFFFF;
        border-radius: 50%;
        background-color: #DDE7EF;
        box-shadow:
            0 2px 7px rgba(7,17,31,0.16);
    }}

    .player-name {{
        min-width: 0;
        overflow: hidden;
        color: #152638;
        font-weight: 850;
        text-overflow: ellipsis;
    }}

    .epl-you-badge {{
        flex: 0 0 auto;
        display: inline-flex;
        align-items: center;
        margin-left: 7px;
        padding: 2px 6px;
        color: #0A5274;
        border: 1px solid rgba(14,116,144,0.25);
        border-radius: 999px;
        background: rgba(14,116,144,0.08);
        font-size: 9px;
        font-weight: 950;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }}

    .total-score-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 42px;
        height: 30px;
        padding: 0 9px;
        color: #07111F;
        border: 1px solid #E8BD31;
        border-radius: 9px;
        background: #F8D863;
        font-size: 14px;
        font-weight: 950;
    }}

    .score-breakdown {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        align-items: center;
        gap: 5px;
        width: 100%;
    }}

    .breakdown-item {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
        min-width: 0;
    }}

    .breakdown-label {{
        color: #7A8C9C;
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 0.02em;
        text-transform: uppercase;
    }}

    .bonus-value,
    .round-bonus-value,
    .round-title-count {{
        font-weight: 900;
    }}

    .bonus-value.is-positive {{
        color: #A65B08;
    }}

    .bonus-value.is-negative {{
        color: #C73535;
    }}

    .bonus-value.is-zero {{
        color: #738496;
    }}

    .round-bonus-value,
    .round-title-count {{
        color: #1763B6;
    }}

    .boosters-cell {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 5px;
    }}

    .star-balance {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 54px;
        height: 27px;
        padding: 0 6px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 950;
    }}

    .hope-star {{
        color: #805500;
        border: 1px solid rgba(222,174,24,0.35);
        background: rgba(245,197,66,0.15);
    }}

    .super-star {{
        color: #50418F;
        border: 1px solid rgba(107,88,190,0.24);
        background: rgba(124,105,210,0.10);
    }}

    .average-value {{
        color: #0E7490;
        font-weight: 900 !important;
    }}

    .percentage-value {{
        color: #445A6D;
        font-variant-numeric: tabular-nums;
    }}

    .epl-leaderboard-footer {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 10px 16px;
        color: #66798B;
        background: #F8FAFC;
        border-top: 1px solid #E5ECF2;
        font-size: 11px;
        font-weight: 700;
    }}

    .epl-leaderboard-footer strong {{
        color: #1C3348;
        font-weight: 900;
    }}

    .epl-leaderboard-mobile {{
        display: none;
    }}

    @media (max-width: 768px) {{
        .epl-leaderboard-card {{
            border-radius: 16px;
            box-shadow: 0 8px 24px rgba(7,17,31,0.07);
        }}

        .epl-leaderboard-toolbar {{
            align-items: center;
            padding: 10px 12px;
            border-bottom-width: 2px;
        }}

        .epl-leaderboard-toolbar-left {{
            gap: 7px;
        }}

        .epl-leaderboard-season {{
            min-height: 24px;
            padding: 3px 8px;
            font-size: 10px;
        }}

        .epl-leaderboard-count {{
            font-size: 10px;
        }}

        .epl-leaderboard-scroll-hint {{
            display: none;
        }}

        .epl-leaderboard-scroll {{
            display: none;
        }}

        .epl-leaderboard-mobile {{
            display: block;
            background: #F5F8FB;
        }}

        .epl-mobile-row {{
            padding: 11px 12px 10px;
            border-bottom: 1px solid #E3EAF0;
            background: #FFFFFF;
        }}

        .epl-mobile-row:nth-child(even) {{
            background: #F8FAFC;
        }}

        .epl-mobile-row:last-child {{
            border-bottom: 0;
        }}

        .epl-mobile-row.is-current-user {{
            background:
                linear-gradient(
                    90deg,
                    #E5F4FB 0%,
                    #F3FAFD 100%
                );
        }}

        .epl-mobile-main {{
            display: grid;
            grid-template-columns: 30px 36px minmax(0, 1fr) auto;
            align-items: center;
            gap: 8px;
            min-width: 0;
        }}

        .epl-mobile-rank {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border: 1px solid #D7E1E8;
            border-radius: 50%;
            color: #425669;
            background: #F2F6F9;
            font-size: 11px;
            font-weight: 950;
        }}

        .epl-mobile-row.is-rank-1 .epl-mobile-rank {{
            color: #704B00;
            border-color: #E9B91F;
            background: linear-gradient(145deg,#FFE485,#F5C542);
        }}

        .epl-mobile-row.is-rank-2 .epl-mobile-rank {{
            color: #344557;
            border-color: #B7C5D1;
            background: linear-gradient(145deg,#F1F5F9,#CBD5E1);
        }}

        .epl-mobile-row.is-rank-3 .epl-mobile-rank {{
            color: #562609;
            border-color: #B9652F;
            background: linear-gradient(145deg,#E8A06C,#C8753D);
        }}

        .epl-mobile-avatar {{
            display: inline-block;
            width: 34px;
            height: 34px;
            border: 2px solid #FFFFFF;
            border-radius: 50%;
            background-color: #DDE7EF;
            box-shadow: 0 2px 7px rgba(7,17,31,0.14);
        }}

        .epl-mobile-player {{
            min-width: 0;
        }}

        .epl-mobile-name-line {{
            display: flex;
            align-items: center;
            min-width: 0;
        }}

        .epl-mobile-name {{
            min-width: 0;
            overflow: hidden;
            color: #142638;
            font-size: 12px;
            font-weight: 900;
            line-height: 1.25;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}

        .epl-mobile-name-line .epl-you-badge {{
            margin-left: 5px;
            padding: 1px 5px;
            font-size: 7px;
        }}

        .epl-mobile-meta {{
            display: flex;
            align-items: center;
            gap: 6px;
            min-width: 0;
            margin-top: 2px;
            color: #788A9A;
            font-size: 9.5px;
            font-weight: 720;
            line-height: 1.2;
            white-space: nowrap;
        }}

        .epl-mobile-title-meta {{
            overflow: hidden;
            color: #8B6410;
            text-overflow: ellipsis;
        }}

        .epl-mobile-score {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-width: 49px;
            min-height: 41px;
            padding: 4px 7px;
            border: 1px solid #E8BD31;
            border-radius: 10px;
            color: #07111F;
            background: #F8D863;
        }}

        .epl-mobile-score strong {{
            font-size: 16px;
            font-weight: 950;
            line-height: 1;
        }}

        .epl-mobile-score span {{
            margin-top: 2px;
            font-size: 8px;
            font-weight: 850;
            line-height: 1;
            text-transform: uppercase;
        }}

        .epl-mobile-stats {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin-top: 8px;
            padding-top: 7px;
            border-top: 1px solid rgba(136,157,174,0.18);
        }}

        .epl-mobile-stats > span {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 3px;
            min-width: 0;
            min-height: 32px;
            padding: 1px 5px;
            border-right: 1px solid rgba(136,157,174,0.17);
        }}

        .epl-mobile-stats > span:nth-child(3n) {{
            border-right: 0;
        }}

        .epl-mobile-stats small {{
            width: 100%;
            overflow: hidden;
            color: #758797;
            font-size: 8.5px;
            font-weight: 760;
            line-height: 1.1;
            text-align: center;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}

        .epl-mobile-stats strong {{
            color: #17324A;
            font-size: 11px;
            font-weight: 950;
            line-height: 1.1;
        }}

        .epl-mobile-breakdown,
        .epl-mobile-boosters,
        .epl-mobile-accuracy {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
            min-width: 0;
            white-space: nowrap;
        }}

        .epl-mobile-breakdown b,
        .epl-mobile-boosters b,
        .epl-mobile-accuracy b {{
            font-size: 8.5px;
            font-weight: 900;
        }}

        .epl-mobile-breakdown .is-positive,
        .epl-mobile-breakdown .is-round-bonus {{
            color: #16804A;
        }}

        .epl-mobile-breakdown .is-negative {{
            color: #C2413A;
        }}

        .epl-mobile-breakdown .is-zero {{
            color: #64748B;
        }}

        .epl-leaderboard-footer {{
            justify-content: center;
            padding: 8px 12px;
            font-size: 10px;
            text-align: center;
        }}

        .epl-leaderboard-footer > span:last-child {{
            display: none;
        }}
    }}
    </style>

    <div class="epl-leaderboard-card">
        <div class="epl-leaderboard-toolbar">
            <div class="epl-leaderboard-toolbar-left">
                <span class="epl-leaderboard-season">
                    Mùa {html.escape(str(season_label))}
                </span>
                <span class="epl-leaderboard-count">
                    {total_players} người chơi
                </span>
            </div>
            <span class="epl-leaderboard-scroll-hint">
                ↔ Cuộn ngang trên màn hình nhỏ
            </span>
        </div>

        <div class="epl-leaderboard-scroll">
            <table class="epl-leaderboard-table">
                <thead>
                    <tr>
                        <th
                            class="col-rank sticky-rank"
                            title="Hạng"
                        >#</th>
                        <th
                            class="col-player sticky-player"
                        >Người chơi</th>
                        <th class="col-score">Điểm</th>
                        <th
                            class="col-breakdown"
                            title="Điểm gốc, thưởng sao và thưởng vô địch vòng"
                        >Chi tiết điểm</th>
                        <th
                            class="col-round-titles"
                            title="Số lần vô địch vòng"
                        >VĐ vòng</th>
                        <th
                            class="col-boosters"
                            title="Số Ngôi sao hy vọng và Siêu sao còn lại"
                        >Bổ trợ</th>
                        <th
                            class="col-matches"
                            title="Số trận đã chấm"
                        >Trận</th>
                        <th
                            class="col-average"
                            title="Điểm dự đoán trung bình mỗi trận đã chấm, không gồm thưởng vòng"
                        >Điểm TB</th>
                        <th
                            class="col-exact"
                        >Đúng tỉ số</th>
                        <th
                            class="col-outcome"
                            title="Số dự đoán đúng kết quả, gồm cả dự đoán đúng tỉ số"
                        >Đúng kết quả</th>
                        <th
                            class="col-rate"
                            title="Tỷ lệ dự đoán đúng kết quả trên tổng số trận đã chấm"
                        >Tỷ lệ đúng</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(table_rows)}
                </tbody>
            </table>
        </div>

        <div
            class="epl-leaderboard-mobile"
            aria-label="Bảng xếp hạng tổng trên điện thoại"
        >
            {''.join(mobile_rows)}
        </div>

        <div class="epl-leaderboard-footer">
            <span>
                Hiển thị
                <strong>{page_start + 1}–{page_end}</strong>
                trong
                <strong>{total_players}</strong>
                người chơi
            </span>
            <span>
                Điểm TB/trận không bao gồm thưởng vô địch vòng
            </span>
        </div>
    </div>
    """

    # Đây là một cây HTML lồng nhiều cấp và có các dòng thụt lề.
    # st.markdown() có thể kết thúc HTML block tại dòng trống rồi hiểu
    # phần còn lại là Markdown code block, khiến mã <div>/<table> bị
    # in thẳng ra màn hình. st.html() render toàn bộ cây HTML trực tiếp.
    st.html(table_html)

    # Không dùng selector trần `button` trong stylable_container.
    # Ở một số phiên bản streamlit-extras, selector đó có thể bị áp
    # sang các nút hệ thống trên header và nút đóng/mở sidebar.
    # Mọi rule dưới đây chỉ được phép tác động tới container phân trang.
    st.markdown(
        """
        <style>
        div[class*="st-key-leaderboard_pagination_"] {
            width: 100% !important;
            max-width: 240px !important;
            margin: 12px auto 0 !important;
        }

        div[class*="st-key-leaderboard_pagination_"]
        .stButton > button {
            width: 40px !important;
            min-width: 40px !important;
            height: 36px !important;
            min-height: 36px !important;
            padding: 0 !important;
            color: #0D2940 !important;
            border: 1px solid rgba(13,41,64,0.18) !important;
            border-radius: 10px !important;
            background: rgba(255,255,255,0.96) !important;
            box-shadow: none !important;
            font-size: 22px !important;
            font-weight: 850 !important;
            line-height: 1 !important;
            transform: none !important;
        }

        div[class*="st-key-leaderboard_pagination_"]
        .stButton > button:hover:not(:disabled) {
            color: #07111F !important;
            border-color: #E0AE15 !important;
            background: #F8D863 !important;
            transform: none !important;
        }

        div[class*="st-key-leaderboard_pagination_"]
        .stButton > button:disabled {
            color: #AEBAC4 !important;
            border-color: #E2E8EE !important;
            background: #F4F7F9 !important;
            opacity: 1 !important;
        }

        @media (max-width: 768px) {
            div[class*="st-key-leaderboard_pagination_"] {
                max-width: 220px !important;
                margin-top: 10px !important;
            }

            div[class*="st-key-leaderboard_pagination_"]
            div[data-testid="stHorizontalBlock"] {
                display: grid !important;
                grid-template-columns: 38px minmax(90px, 1fr) 38px !important;
                gap: 9px !important;
                align-items: center !important;
            }

            div[class*="st-key-leaderboard_pagination_"]
            div[data-testid="stColumn"] {
                width: 100% !important;
                min-width: 0 !important;
                max-width: none !important;
                flex: none !important;
            }

            div[class*="st-key-leaderboard_pagination_"]
            .stButton > button {
                width: 38px !important;
                min-width: 38px !important;
                height: 34px !important;
                min-height: 34px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    with st.container(
        key=(
            "leaderboard_pagination_"
            + season_slug.replace("-", "_")
        )
    ):
        (
            previous_column,
            page_column,
            next_column
        ) = st.columns(
            [1, 1.8, 1]
        )

        with previous_column:
            previous_clicked = st.button(
                "‹",
                key=(
                    "leaderboard_previous_"
                    + season_slug
                ),
                help="Trang trước",
                disabled=current_page <= 1
            )

        with page_column:
            st.markdown(
                f"""
                <div style="
                    min-height:36px;
                    display:flex;
                    align-items:center;
                    justify-content:center;
                    gap:4px;
                    color:#6A7D8F;
                    font-size:12px;
                    font-weight:800;
                    white-space:nowrap;
                ">
                    Trang
                    <span style="
                        color:#07111F;
                        font-size:14px;
                        font-weight:950;
                    ">{current_page}</span>
                    / {total_pages}
                </div>
                """,
                unsafe_allow_html=True
            )

        with next_column:
            next_clicked = st.button(
                "›",
                key=(
                    "leaderboard_next_"
                    + season_slug
                ),
                help="Trang sau",
                disabled=current_page >= total_pages
            )

    if previous_clicked:
        st.session_state[page_state_key] = (
            current_page - 1
        )
        st.rerun()

    if next_clicked:
        st.session_state[page_state_key] = (
            current_page + 1
        )
        st.rerun()

def page_dashboard():
    import plotly.express as px

    render_page_title(
        "Bảng phân tích tổng quan",
        "Phân tích tổng quan hiệu suất dự đoán, điểm số và độ chính xác của tất cả người chơi."
    )

    score_all_predictions(get_selected_season_slug())

    leaderboard = build_leaderboard_df(get_selected_season_slug())
    predictions = load_predictions(get_selected_season_slug())

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
    total_score_values = pd.to_numeric(
        leaderboard["total_points"],
        errors="coerce"
    ).fillna(0)

    score_min = int(total_score_values.min())
    score_max = int(total_score_values.max())
    score_axis_min = min(0.0, score_min * 1.16)
    score_axis_max = max(1.0, score_max * 1.16)
    score_color_min = min(0, score_min)
    score_color_max = max(1, score_max)

    # Plotly không cho phép kích thước điểm âm. Dịch toàn bộ miền điểm
    # sang số dương nhưng vẫn giữ nguyên thứ tự lớn/nhỏ giữa người chơi.
    leaderboard["score_bubble_size"] = (
        total_score_values
        - score_min
        + 1
    ).astype(float)

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
            "prediction_points",
            "base_points",
            "star_bonus_points",
            "round_champion_bonus_points",
            "round_champion_count",
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
            "Điểm dự đoán = %{customdata[1]}<br>"
            "Điểm gốc = %{customdata[2]}<br>"
            "Điểm bổ trợ = %{customdata[3]}<br>"
            "Thưởng vòng = %{customdata[4]} "
            "(%{customdata[5]} lần VĐ vòng)<br>"
            "⭐ Ngôi sao hy vọng đã dùng = %{customdata[6]}<br>"
            "✨ Siêu sao đã dùng = %{customdata[7]}"
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
        range=[score_axis_min, score_axis_max]
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
        size="score_bubble_size",
        hover_name="display_name",
        custom_data=[
            "total_points",
            "prediction_points",
            "base_points",
            "star_bonus_points",
            "round_champion_bonus_points",
            "round_champion_count",
            "hope_stars_used",
            "super_stars_used"
        ],
        title="Độ chính xác kết quả vs độ chính xác tỉ số",
        labels={
            "result_prediction_rate": "% Đúng kết quả",
            "exact_score_rate": "% Đúng hoàn toàn tỉ số",
            "total_points": "Điểm",
            "score_bubble_size": "Quy mô điểm"
        },
        color="total_points",
        color_continuous_scale=custom_score_scale,
        range_color=(score_color_min, score_color_max)
    )

    fig_accuracy.update_xaxes(tickformat=".1%")
    fig_accuracy.update_yaxes(tickformat=".1%")

    fig_accuracy.update_traces(
        hovertemplate=(
            "<b>%{hovertext}</b><br>"
            "% Đúng kết quả = %{x:.1%}<br>"
            "% Đúng hoàn toàn tỉ số = %{y:.1%}<br>"
            "Tổng điểm = %{customdata[0]}<br>"
            "Điểm dự đoán = %{customdata[1]}<br>"
            "Điểm gốc = %{customdata[2]}<br>"
            "Điểm bổ trợ = %{customdata[3]}<br>"
            "Thưởng vòng = %{customdata[4]} "
            "(%{customdata[5]} lần VĐ vòng)<br>"
            "⭐ Ngôi sao hy vọng đã dùng = %{customdata[6]}<br>"
            "✨ Siêu sao đã dùng = %{customdata[7]}"
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

    matches = load_matches(get_selected_season_slug())
    users = load_users()
    predictions = load_predictions(get_selected_season_slug())

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

        matches = (
            matches
            .sort_values("kickoff_time_utc_dt")
            .copy()
        )

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
        score_all_predictions.clear()
        score_all_predictions(
            get_selected_season_slug()
        )
        build_leaderboard_df.clear()
        st.success(
            "Đã chấm lại toàn bộ dự đoán theo luật mới."
        )

# ============================================================
# EPL NEWS TICKER
# ============================================================

@st.cache_data(
    ttl=60,
    show_spinner=False,
    max_entries=2
)
def load_latest_epl_news_ticker():
    """
    Đọc bản ticker hiện tại từ Supabase.

    Tính năng này là phụ:
    - Database lỗi thì ticker tự ẩn.
    - Không làm gián đoạn các trang khác.
    - Cache 60 giây để tránh query liên tục.
    """

    row = fetch_one(
        """
        SELECT
            generated_at,
            items,
            ticker_text,
            model_name,
            updated_at
        FROM epl_news_ticker
        WHERE id = 1
          AND updated_at >= (
              NOW()
              - make_interval(
                    hours => :max_age_hours
                )
          )
        LIMIT 1
        """,
        {
            "max_age_hours": int(
                NEWS_TICKER_MAX_AGE_HOURS
            )
        }
    )

    if row is None:
        return None

    row = dict(row)

    raw_items = row.get("items")

    # Một số driver có thể trả JSONB dưới dạng chuỗi.
    if isinstance(raw_items, str):
        try:
            raw_items = json.loads(
                raw_items
            )
        except json.JSONDecodeError:
            LOGGER.warning(
                "EPL news ticker items contain invalid JSON."
            )
            return None

    if not isinstance(raw_items, list):
        return None

    ticker_items = []

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue

        item_text = re.sub(
            r"\s+",
            " ",
            str(
                raw_item.get(
                    "text",
                    ""
                )
            )
        ).strip()

        if item_text:
            ticker_items.append(
                item_text
            )

    if not ticker_items:
        return None

    row["items"] = ticker_items

    return row


def _render_epl_news_ticker_content():
    """
    Render phần nội dung ticker.

    Tách thành hàm riêng để có thể dùng với st.fragment.
    """

    if not NEWS_TICKER_ENABLED:
        return

    try:
        ticker_data = (
            load_latest_epl_news_ticker()
        )

    except Exception:
        LOGGER.exception(
            "Failed to load EPL news ticker."
        )
        return

    if not ticker_data:
        return

    ticker_items = ticker_data.get(
        "items",
        []
    )

    if not ticker_items:
        return

    safe_items = [
        html.escape(
            str(item),
            quote=False
        )
        for item in ticker_items
    ]

    item_markup = "".join(
        (
            '<span class="epl-news-item">'
            f'{item}'
            '</span>'

            '<span '
            'class="epl-news-separator" '
            'aria-hidden="true">'
            '◆'
            '</span>'
        )
        for item in safe_items
    )

    total_characters = sum(
        len(item)
        for item in ticker_items
    )

    # Tự điều chỉnh tốc độ theo tổng độ dài bản tin.
    animation_duration = max(
        100,
        min(
            220,
            round(
                total_characters / 7
            )
        )
    )

    generated_at = ticker_data.get(
        "generated_at"
    )

    generated_label = ""

    if generated_at:
        try:
            if isinstance(
                generated_at,
                str
            ):
                generated_at = (
                    datetime.fromisoformat(
                        generated_at.replace(
                            "Z",
                            "+00:00"
                        )
                    )
                )

            if isinstance(
                generated_at,
                datetime
            ):
                if (
                    generated_at.tzinfo
                    is None
                ):
                    generated_at = (
                        generated_at.replace(
                            tzinfo=timezone.utc
                        )
                    )

                generated_vietnam = (
                    generated_at.astimezone(
                        timezone(
                            timedelta(hours=7)
                        )
                    )
                )

                generated_label = (
                    generated_vietnam.strftime(
                        "%H:%M %d/%m"
                    )
                )

        except Exception:
            generated_label = ""

    label_title = "Tin EPL mới nhất"

    if generated_label:
        label_title += (
            f" · Cập nhật {generated_label}"
        )

    safe_label_title = html.escape(
        label_title,
        quote=True
    )

    ticker_css = f"""
    <style>
    div[class*="st-key-epl_news_ticker_shell"] {{
        width: 100% !important;
        max-width: 100% !important;

        margin:
            0 0 12px 0 !important;

        padding:
            0 !important;
    }}

    div[class*="st-key-epl_news_ticker_shell"]
    > div[data-testid="stVerticalBlock"] {{
        gap: 0 !important;
    }}

    div[class*="st-key-epl_news_ticker_shell"]
    div[data-testid="stElementContainer"] {{
        margin:
            0 !important;
    }}

    .epl-news-shell {{
        --ticker-duration:
            {animation_duration}s;

        display:
            grid;

        grid-template-columns:
            auto minmax(0, 1fr);

        width:
            100%;

        min-width:
            0;

        height:
            40px;

        min-height:
            40px;

        box-sizing:
            border-box;

        overflow:
            hidden;

        background:
            linear-gradient(
                90deg,
                #210027 0%,
                #37003C 46%,
                #27002E 100%
            );

        border:
            1px solid
            rgba(55, 0, 60, 0.24);

        border-radius:
            11px;

        box-shadow:
            0 8px 22px
            rgba(55, 0, 60, 0.13),
            inset 0 1px 0
            rgba(255, 255, 255, 0.10);

        user-select:
            none;

        pointer-events:
            none;
    }}

    .epl-news-label {{
        position:
            relative;

        z-index:
            2;

        display:
            inline-flex;

        align-items:
            center;

        justify-content:
            center;

        gap:
            8px;

        min-width:
            103px;

        height:
            40px;

        box-sizing:
            border-box;

        padding:
            0 16px 0 13px;

        background:
            linear-gradient(
                135deg,
                #FF2882 0%,
                #D90D69 100%
            );

        color:
            #FFFFFF;

        font-size:
            10px;

        font-weight:
            950;

        line-height:
            1;

        letter-spacing:
            0.075em;

        white-space:
            nowrap;

        text-transform:
            uppercase;

        clip-path:
            polygon(
                0 0,
                calc(100% - 12px) 0,
                100% 50%,
                calc(100% - 12px) 100%,
                0 100%
            );
    }}

    .epl-news-label-dot {{
        width:
            6px;

        height:
            6px;

        flex:
            0 0 auto;

        background:
            #00FF85;

        transform:
            rotate(45deg);

        box-shadow:
            0 0 8px
            rgba(0, 255, 133, 0.62);
    }}

    .epl-news-viewport {{
        width:
            100%;

        min-width:
            0;

        height:
            40px;

        overflow:
            hidden;

        box-sizing:
            border-box;
    }}

    .epl-news-track {{
        display:
            flex;

        align-items:
            center;

        width:
            max-content;

        height:
            40px;

        will-change:
            transform;

        animation:
            eplNewsTickerAnimation
            var(--ticker-duration)
            linear
            infinite;
    }}

    .epl-news-group {{
        display:
            inline-flex;

        align-items:
            center;

        flex:
            0 0 auto;

        height:
            40px;

        box-sizing:
            border-box;

        padding-right:
            28px;
    }}

    .epl-news-item {{
        display:
            inline-block;

        color:
            #FFFFFF;

        font-size:
            13px;

        font-weight:
            650;

        line-height:
            1.2;

        letter-spacing:
            0.002em;

        white-space:
            nowrap;
    }}

    .epl-news-separator {{
        display:
            inline-flex;

        align-items:
            center;

        justify-content:
            center;

        flex:
            0 0 auto;

        margin:
            0 20px;

        color:
            #00FF85;

        font-size:
            7px;

        line-height:
            1;

        filter:
            drop-shadow(
                0 0 4px
                rgba(0, 255, 133, 0.48)
            );
    }}

    @keyframes eplNewsTickerAnimation {{
        from {{
            transform:
                translate3d(
                    0,
                    0,
                    0
                );
        }}

        to {{
            transform:
                translate3d(
                    -50%,
                    0,
                    0
                );
        }}
    }}

    @media (max-width: 768px) {{
        div[class*="st-key-epl_news_ticker_shell"] {{
            margin-bottom:
                10px !important;
        }}

        .epl-news-shell {{
            height:
                35px;

            min-height:
                35px;

            border-radius:
                9px;
        }}

        .epl-news-label {{
            min-width:
                73px;

            height:
                35px;

            gap:
                6px;

            padding:
                0 9px 0 8px;

            font-size:
                7.8px;

            letter-spacing:
                0.045em;
        }}

        .epl-news-label-dot {{
            width:
                5px;

            height:
                5px;
        }}

        .epl-news-viewport,
        .epl-news-track,
        .epl-news-group {{
            height:
                35px;
        }}

        .epl-news-item {{
            font-size:
                11.5px;

            font-weight:
                650;
        }}

        .epl-news-separator {{
            margin:
                0 15px;

            font-size:
                6px;
        }}

        .epl-news-group {{
            padding-right:
                22px;
        }}
    }}

    @media (
        prefers-reduced-motion: reduce
    ) {{
        .epl-news-track {{
            animation:
                none !important;

            transform:
                none !important;
        }}

        .epl-news-group:nth-child(2) {{
            display:
                none !important;
        }}
    }}
    </style>
    """

    ticker_html = f"""
    <div
        class="epl-news-shell"
        role="region"
        aria-label="{safe_label_title}"
        title="{safe_label_title}"
    >
        <div
            class="epl-news-label"
            aria-hidden="true"
        >
            <span
                class="epl-news-label-dot"
            ></span>

            <span>
                TIN EPL
            </span>
        </div>

        <div
            class="epl-news-viewport"
        >
            <div
                class="epl-news-track"
                aria-hidden="true"
            >
                <div
                    class="epl-news-group"
                >
                    {item_markup}
                </div>

                <div
                    class="epl-news-group"
                >
                    {item_markup}
                </div>
            </div>
        </div>
    </div>
    """

    with st.container(
        key="epl_news_ticker_shell"
    ):
        st.markdown(
            ticker_css + ticker_html,
            unsafe_allow_html=True
        )


@st.fragment(
    run_every=NEWS_TICKER_REFRESH_INTERVAL
)
def render_epl_news_ticker():
    """
    Tự kiểm tra bản tin mới mà không rerun toàn bộ app.
    """

    _render_epl_news_ticker_content()

def render_footer():
    if FOOTER_PROJECT_URL:
        footer_link = (
            f'<a href="{FOOTER_PROJECT_URL}" '
            f'target="_blank">'
            f'Project repo / portfolio'
            f'</a>'
        )
    else:
        footer_link = "EPL Prediction Arena"

    st.markdown(
        f"""
        <div class="wc-footer">
            © 2026 Prediction Arena. {footer_link}
        </div>
        """,
        unsafe_allow_html=True
    )


def render_page_safely(
    page_name: str,
    page_renderer
):
    """
    Không để lỗi kết nối/tài nguyên tạm thời biến thành màn hình crash đỏ.

    Lỗi đầy đủ vẫn được ghi ở server log để có thể chẩn đoán. Giao diện bình
    thường không thay đổi; khối này chỉ xuất hiện khi page renderer thật sự lỗi.
    """
    try:
        page_renderer()

    except Exception:
        LOGGER.exception(
            "Failed to render page %s",
            page_name
        )

        st.error(
            "Dữ liệu tạm thời chưa tải được. "
            "Bạn có thể thử lại ngay mà không cần đăng nhập lại."
        )
        st.caption(
            "Nếu Supabase vừa khởi động lại hoặc mạng chập chờn, "
            "lần thử tiếp theo thường sẽ hoạt động bình thường."
        )

        if st.button(
            "Thử tải lại",
            key=(
                "retry_page_"
                + re.sub(
                    r"[^a-z0-9]+",
                    "_",
                    page_name.casefold()
                ).strip("_")
            ),
            use_container_width=True
        ):
            reset_database_pool_after_disconnect()

            try:
                clear_data_cache()
            except Exception:
                pass

            try:
                score_all_predictions.clear()
            except Exception:
                pass

            st.rerun()


# ============================================================
# 11. MAIN APP
# ============================================================

def main():
    with st.container(
        key="global_ui_bootstrap"
    ):
        enforce_embed_url()

        inject_epl_theme()
        inject_hide_streamlit_embed_footer_css()
        inject_sidebar_menu_radio_css()
        inject_display_name_ui_css()

        # Đặt cuối cùng để ưu tiên CSS bố cục tổng.
        inject_main_page_lift_css()

    try:
        initialize_app_once()
    except Exception as e:
        st.error(
            "App không khởi động được ở bước "
            "kết nối/khởi tạo database."
        )
        st.caption(
            "Hãy kiểm tra DATABASE_URL, trạng thái "
            "Supabase và log trong Streamlit Cloud."
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
    
    daily_checkin_popup_opened = maybe_render_daily_checkin_popup(user["user_id"])
    
    if not daily_checkin_popup_opened:
        maybe_render_final_poster_popup(user["user_id"])

    display_name_edit_clicked = False

    with st.sidebar:
        render_sidebar_brand()

        display_name_edit_clicked = (
            render_sidebar_display_name(user)
        )
        render_sidebar_star_balance(user["user_id"])

        if st.button(
            "Đăng xuất",
            key="sidebar_logout_button",
            use_container_width=True
        ):
            logout_user()

        st.markdown("---")

        pages = [
            "Lịch thi đấu & dự đoán",
            "Dự đoán của tôi",
            "Bảng xếp hạng",
            "Thống kê giải đấu",
            "Phân tích tổng quan"
        ]

        if user["role"] == "admin":
            pages.append("Admin")
        
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

    if display_name_edit_clicked:
        try:
            change_state = get_display_name_change_state(
                int(user["user_id"])
            )

            if change_state["can_change"]:
                render_display_name_change_dialog(user)
            else:
                next_change_text = format_vietnam_datetime(
                    change_state.get("next_available_at")
                )

                set_display_name_feedback(
                    title="Chưa đến thời gian đổi tên",
                    detail=(
                        "Bạn có thể đổi lại từ "
                        f"{next_change_text}."
                    ),
                    tone="info"
                )

        except Exception:
            LOGGER.exception(
                "Failed to check display name cooldown "
                "for user_id=%s",
                int(user["user_id"])
            )
            set_display_name_feedback(
                title="Chưa thể kiểm tra quyền đổi tên",
                detail="Vui lòng thử lại sau.",
                tone="danger"
            )

    render_display_name_feedback_popup()
    
    # Hiển thị ticker tin tức Premier League
    # trên mọi trang sau khi người dùng đăng nhập.
    render_epl_news_ticker()
    
    # Chỉ nạp CSS/JavaScript chuyên biệt của trang đang mở.
    # Trước đây mọi trang, kể cả đăng nhập, đều phải nhận toàn bộ CSS card
    # và ba DOM observer của trang dự đoán dù không sử dụng.
    if selected_page == "Lịch thi đấu & dự đoán":
        with st.container(
            key="matches_page_ui_bootstrap"
        ):
            inject_match_card_border_animation_css()
            inject_epl_premium_match_card_css()
            inject_epl_match_card_background_css()
            inject_epl_big_match_card_css()

            inject_mobile_prediction_score_row_css()
            inject_prediction_score_stepper_css()
            inject_mobile_prediction_action_buttons_css()
            inject_prediction_score_readonly_script()
            inject_mobile_team_name_display_script()

            inject_mobile_match_title_css()
            inject_desktop_match_vs_style()

            inject_mobile_goal_scorer_button_css()
            inject_mobile_goal_scorer_panel_css()
            inject_ai_summary_button_css()

    elif selected_page == "Admin":
        # Admin vẫn giữ cơ chế rút gọn tên CLB trên mobile như bản cũ.
        inject_mobile_team_name_display_script()

    # Nút điểm danh vẫn được render bên ngoài wrapper nội dung,
    # vì vậy giữ nguyên vị trí fixed hiện tại.
    if selected_page == "Lịch thi đấu & dự đoán":
        render_daily_checkin_shortcut_button(
            int(user["user_id"])
        )

    # Chỉ wrapper này được đẩy lên trên.
    # Avatar và nút điểm danh không nằm trong wrapper.
    with st.container(
        key="main_page_content_shell"
    ):
        page_renderers = {
            "Lịch thi đấu & dự đoán": page_matches,
            "Dự đoán của tôi": page_my_predictions,
            "Bảng xếp hạng": page_leaderboard,
            "Thống kê giải đấu": page_competition_stats,
            "Phân tích tổng quan": page_dashboard,
            "Admin": page_admin
        }

        page_renderer = page_renderers.get(
            selected_page
        )

        if page_renderer is not None:
            render_page_safely(
                page_name=selected_page,
                page_renderer=page_renderer
            )

        render_footer()

if __name__ == "__main__":
    main()
