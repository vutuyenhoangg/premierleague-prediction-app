# ============================================================
# EPL PREDICTION ARENA
# Safe refactor: duplicate overwritten helper definitions removed; runtime behavior intentionally preserved.
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
from datetime import datetime, timezone, timedelta, date
import pandas as pd
import streamlit as st
import plotly.express as px
from streamlit_extras.stylable_container import stylable_container
import secrets
from streamlit_cookies_controller import CookieController
import re
from google import genai
from google.genai import types
import textwrap

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
HOPE_STARS_PER_USER = 5
SUPER_STARS_PER_USER = 1
CHECKIN_CYCLE_DAYS = 7
CHECKIN_HOPE_REWARD_DAY = 5
CHECKIN_SUPER_REWARD_DAY = 7
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME = st.secrets.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")
ENABLE_FINAL_POSTER = False
ENABLE_AI_FEATURES = True
AI_SUGGESTION_MAX_DAYS = 3

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

APP_LOGO_URL = "data/static/epl-prediction-arena.png"

HERO_BACKGROUND_URL = "data/static/epl-banner.png"

HERO_TROPHY_IMAGE_URL = "data/static/logo-epl.png"

SIDEBAR_DECORATION_URL = "data/static/epl-sidebar.png"

FINAL_POSTER_IMAGE_URL = ""

FINAL_BACKGROUND_IMAGE_URL = ""

EPL_MATCH_BACKGROUND_IMAGE_URL = "data/static/epl-match-background.png"

FINAL_POSTER_END_DATE = date(2026, 7, 20)

FOOTER_PROJECT_URL = ""

@st.cache_data(show_spinner=False)
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

    for cached_function in [
        load_matches,
        load_predictions,
        build_leaderboard_df
    ]:
        try:
            cached_function.clear()
        except Exception:
            pass


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
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="collapsed"
)

def enforce_embed_url():
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


enforce_embed_url()

cookie_controller = CookieController()

@st.cache_data(show_spinner=False)
def load_avatar_keys() -> list[str]:
    """
    Load danh sách avatar có sẵn trong folder data/static/avatars.
    Khai báo thứ tự avatar.
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
    avatar_key = normalize_avatar_key(avatar_key)

    if not avatar_key:
        return ""

    return resolve_asset_src(f"{AVATAR_FOLDER}/{avatar_key}")
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
            padding-top: 0rem;
            padding-bottom: 2.4rem;
            max-width: 1440px;
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
         * Fix nút Đăng xuất trong sidebar:
         * nền trắng nhưng chữ không bị trắng theo sidebar.
         */
        section[data-testid="stSidebar"]
        .stButton > button {{
            background: rgba(255, 255, 255, 0.96) !important;
            color: #07111F !important;
            border: 1px solid rgba(245, 197, 66, 0.35) !important;
        }}

        section[data-testid="stSidebar"]
        .stButton > button * {{
            color: #07111F !important;
        }}

        section[data-testid="stSidebar"]
        .stButton > button:hover {{
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

        /* =====================================================
           NÚT MENU SIDEBAR
           ===================================================== */

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

        /*
         * Khi sidebar mở, nút nằm trên nền xanh đậm
         * nên chữ Menu chuyển sang trắng.
         */
        section[data-testid="stSidebar"]
        button[data-testid="stBaseButton-headerNoPadding"]:first-of-type::after,
        section[data-testid="stSidebar"]
        button[kind="headerNoPadding"]:first-of-type::after {{
            color: #F8FAFC !important;
        }}

        section[data-testid="stSidebar"]
        button[data-testid="stBaseButton-headerNoPadding"]:first-of-type svg,
        section[data-testid="stSidebar"]
        button[kind="headerNoPadding"]:first-of-type svg {{
            color: #F8FAFC !important;
            stroke: #F8FAFC !important;
        }}

        section[data-testid="stSidebar"]
        button[data-testid="stBaseButton-headerNoPadding"]:first-of-type:hover,
        section[data-testid="stSidebar"]
        button[kind="headerNoPadding"]:first-of-type:hover {{
            background: rgba(255, 255, 255, 0.08) !important;
        }}

        button[data-testid="stBaseButton-headerNoPadding"]:first-of-type:hover,
        button[kind="headerNoPadding"]:first-of-type:hover {{
            background: rgba(15, 23, 42, 0.05) !important;
        }}

        button[data-testid="stBaseButton-headerNoPadding"]:first-of-type svg,
        button[kind="headerNoPadding"]:first-of-type svg {{
            width: 20px !important;
            height: 20px !important;
            color: #64748B !important;
            stroke: #64748B !important;
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

def inject_main_page_lift_css():
    """
    Đẩy riêng nội dung trang chính lên cao hơn.

    - Desktop và mobile có mức dịch chuyển riêng.
    - Không tác động tới sidebar.
    - Không tác động tới avatar.
    - Không tác động tới nút điểm danh.
    - Không thay đổi kích thước hoặc bố cục bên trong nội dung.
    """
    st.markdown(
        """
        <style>
        /*
         * Desktop
         */
        @media (min-width: 769px) {
            div[class*="st-key-main_page_content_shell"] {
                position: relative !important;
                margin-top: -118px !important;
            }
        }

        /*
         * Điện thoại và tablet dọc.
         *
         * Khoảng trống hiện tại trên mobile khoảng hơn 150px.
         * Kéo nội dung lên 92px để hero tiến gần khu vực avatar,
         * nhưng vẫn giữ một khoảng an toàn phía dưới header.
         */
        @media (max-width: 768px) {
            div[class*="st-key-main_page_content_shell"] {
                position: relative !important;
                margin-top: -92px !important;
            }
        }

        /*
         * Màn hình rất nhỏ cần dịch nhẹ hơn một chút,
         * tránh hero tiến quá sát thanh Menu.
         */
        @media (max-width: 390px) {
            div[class*="st-key-main_page_content_shell"] {
                margin-top: -84px !important;
            }
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

inject_epl_theme()
inject_match_card_border_animation_css()
inject_epl_premium_match_card_css()
inject_epl_match_card_background_css()
inject_mobile_prediction_score_row_css()
inject_hide_streamlit_embed_footer_css()
inject_main_page_lift_css()

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
                    subtree: true,
                    attributes: true,
                    attributeFilter: [
                        "class",
                        "style",
                        "aria-label",
                        "aria-selected",
                        "data-selected"
                    ]
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

inject_mobile_match_title_css()
inject_desktop_match_vs_style()

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
    Nút tròn nhỏ dưới avatar để mở lại popup điểm danh.
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

            cursor: pointer !important;
            overflow: visible !important;

            transition:
                transform 0.18s ease,
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
            transform: translateY(-1px) scale(1.045) !important;
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
            transform: translateY(0) scale(0.98) !important;
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
    
    if shortcut_clicked:
        render_daily_checkin_dialog(user_id)

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
        unknown_matches = 0
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

        unknown_matches = int(
            matches_for_count["has_unknown_team"].sum()
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
                **Dự đoán tỉ số**

                - Đúng hoàn toàn tỉ số: **+3 điểm**
                - Đúng kết quả thắng/hòa/thua: **+1 điểm**
                - Sai kết quả: **0 điểm**

                **Bổ trợ**

                - {STAR_CONFIG[STAR_TYPE_HOPE]["short_label"]}: **x2** điểm trận đó
                - {STAR_CONFIG[STAR_TYPE_SUPER]["short_label"]}: **x3** điểm trận đó
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
                ⭐ Ngôi sao hy vọng: <b style="color:#F5C542;">{usage["hope_left"]}/{usage.get("hope_total", HOPE_STARS_PER_USER)}</b>
            </div>
            <div style="font-size:13px;color:#CBD5E1;margin-top:4px;">
                ✨ Siêu sao: <b style="color:#F5C542;">{usage["super_left"]}/{usage.get("super_total", SUPER_STARS_PER_USER)}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

@st.fragment
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
    user = st.session_state.get("user", user)
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
                            update_user_avatar(
                                user_id=int(user["user_id"]),
                                avatar_key=avatar_key
                            )
                    
                            updated_user = dict(st.session_state.get("user", user))
                            updated_user["avatar_key"] = avatar_key
                            st.session_state["user"] = updated_user
                    
                            rerun_current_fragment()
                    
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
                border: none !important;
                outline: none !important;
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


def get_user_star_usage(user_id: int, exclude_match_id: int | None = None) -> dict:
    """
    Dùng cho UI.

    Logic mới:
    - locked_used: chỉ tính sao ở các trận đã khóa dự đoán.
    - reserved_used: sao đang giữ tạm ở các trận chưa diễn ra.
    - left: số sao còn lại theo kho chính thức, chỉ trừ locked_used.
    - free_left: số sao còn trống để gắn ngay, đã trừ cả reserved_used.
    """
    predictions = load_predictions(get_selected_season_slug())
    matches = load_matches(get_selected_season_slug())

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





def get_match_card_css(status_info, row=None):
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

            safe_component_id = f"wc_countdown_badge_{int(row.get('match_id'))}"
            safe_initial_text = html.escape(initial_countdown_text)
            safe_expired_label = html.escape(badge_label)
            safe_badge_bg = html.escape(str(status_info["badge_bg"]))
            safe_badge_text = html.escape(str(status_info["badge_text"]))

            countdown_html = f"""
            <!doctype html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    html,
                    body {{
                        margin: 0;
                        padding: 0;
                        background: transparent;
                        overflow: hidden;
                    }}

                    .wc-countdown-badge {{
                        display: inline-block;
                        padding: 7px 13px;
                        border-radius: 999px;
                        background: {safe_badge_bg};
                        color: {safe_badge_text};
                        font-weight: 850;
                        font-size: 13px;
                        line-height: 1.25;
                        margin-bottom: 8px;
                        border: 1px solid rgba(15,23,42,0.06);
                        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                        white-space: nowrap;
                        box-sizing: border-box;
                    }}
                </style>
            </head>
            <body>
                <div
                    id="{safe_component_id}"
                    class="wc-countdown-badge"
                    data-kickoff-ms="{kickoff_epoch_ms}"
                    data-expired-label="{safe_expired_label}"
                >{safe_initial_text}</div>

                <script>
                (function() {{
                    const badge = document.getElementById("{safe_component_id}");

                    if (!badge) {{
                        return;
                    }}

                    const kickoffMs = Number(badge.dataset.kickoffMs);
                    const expiredLabel = badge.dataset.expiredLabel || "";

                    function formatCountdown(totalSeconds) {{
                        totalSeconds = Math.max(0, Math.floor(totalSeconds));

                        const days = Math.floor(totalSeconds / 86400);
                        const hours = Math.floor((totalSeconds % 86400) / 3600);
                        const minutes = Math.floor((totalSeconds % 3600) / 60);
                        const seconds = totalSeconds % 60;

                        if (days >= 1) {{
                            return days + "d " + hours + "h " + minutes + "m";
                        }}

                        return hours + "h " + minutes + "m " + seconds + "s";
                    }}

                    function updateCountdown() {{
                        const remainingMs = kickoffMs - Date.now();

                        if (remainingMs <= 0) {{
                            badge.textContent = expiredLabel;
                            window.clearInterval(timer);
                            return;
                        }}

                        badge.textContent = formatCountdown(remainingMs / 1000);
                    }}

                    updateCountdown();

                    const timer = window.setInterval(
                        updateCountdown,
                        1000
                    );
                }})();
                </script>
            </body>
            </html>
            """

            components.html(
                countdown_html,
                height=38,
                scrolling=False
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

    team_columns = read_sql(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'teams'
        """
    )

    actual_team_columns = set(
        team_columns["column_name"].tolist()
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

    match_columns = read_sql(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'matches'
        """
    )

    actual_match_columns = set(
        match_columns["column_name"].tolist()
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
        get_daily_checkin_state_cached.clear()
    except Exception:
        pass

    try:
        build_leaderboard_df.clear()
    except Exception:
        pass

@st.cache_data(ttl=60, show_spinner=False)
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


@st.cache_data(ttl=60, show_spinner=False)
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

@st.cache_data(
    ttl=30,
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
def load_predictions(season_slug: str | None = None) -> pd.DataFrame:
    season_slug = season_slug or DEFAULT_SEASON_SLUG

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


def clear_prediction_write_cache():
    """
    Chỉ xóa các cache bị ảnh hưởng trực tiếp khi dự đoán thay đổi.
    Không xóa cache trận đấu, user, cầu thủ ghi bàn hoặc AI.
    """
    try:
        load_predictions.clear()
    except (NameError, AttributeError):
        pass

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

    if not can_edit_prediction(match.get("kickoff_time_utc")):
        raise ValueError("Trận đấu đã khóa dự đoán.")

    if predicted_winner_team_id is not None:
        predicted_winner_team_id = int(predicted_winner_team_id)

    is_knockout = to_bool(match.get("is_knockout"))

    if not is_knockout:
        return predicted_winner_team_id

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
    predictions = load_predictions(get_selected_season_slug())

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
        clear_prediction_write_cache()

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

        if not can_edit_prediction(source_match.get("kickoff_time_utc")):
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

    clear_prediction_write_cache()
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

        if not can_edit_prediction(match.get("kickoff_time_utc")):
            raise ValueError(
                "Trận đấu đã khóa dự đoán, bạn không thể hủy dự đoán nữa."
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

    clear_prediction_write_cache()

    return {
        "status": "deleted",
        "prediction_id": prediction_id
    }

def score_all_predictions(season_slug: str | None = None):
    """
    Chấm điểm lại toàn bộ dự đoán đã có kết quả.

    Tối ưu:
    - Vẫn giữ nguyên logic tính điểm hiện tại.
    - Vẫn kiểm tra toàn bộ prediction đã có kết quả.
    - Chỉ UPDATE database khi điểm mới khác điểm đang lưu.
    - Nếu không có gì thay đổi thì KHÔNG clear cache, giúp Bảng xếp hạng load nhanh hơn nhiều.
    """
    season_slug = season_slug or get_selected_season_slug()
    matches = load_matches(season_slug)
    predictions = load_predictions(season_slug)

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
    score_all_predictions(get_selected_season_slug())


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
def get_mobile_team_display_name(team_name) -> str:
    """
    Tạo tên ngắn gọn, rõ nghĩa dành riêng cho card mobile.

    Desktop vẫn sử dụng tên đầy đủ từ database.
    """
    if team_name is None or pd.isna(team_name):
        return "TBD"

    full_name = str(team_name).strip()

    if not full_name:
        return "TBD"

    mobile_name_overrides = {
        "afc bournemouth": "Bournemouth",
        "brighton & hove albion": "Brighton",
        "brighton & hove albion fc": "Brighton",
        "coventry city": "Coventry",
        "hull city": "Hull City",
        "ipswich town": "Ipswich Town",
        "manchester city": "Man City",
        "manchester city fc": "Man City",
        "manchester united": "Man United",
        "manchester united fc": "Man United",
        "newcastle united": "Newcastle",
        "newcastle united fc": "Newcastle",
        "nottingham forest": "Nottingham Forest",
        "nottingham forest fc": "Nottingham Forest",
        "tottenham hotspur": "Tottenham",
        "tottenham hotspur fc": "Tottenham",
        "west ham united": "West Ham",
        "west ham united fc": "West Ham",
        "wolverhampton wanderers": "Wolves",
        "wolverhampton wanderers fc": "Wolves",
    }

    normalized_name = full_name.casefold()

    if normalized_name in mobile_name_overrides:
        return mobile_name_overrides[
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
    row=None
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

    if safe_round:
        ribbon_html = (
            '<div class="epl-premier-league-ribbon">'

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
            '<div class="epl-premier-league-ribbon">'

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
        set_prediction_feedback_message(
            match_id=match_id,
            message=(
                "Không thể xóa dự đoán vào lúc này. "
                "Dữ liệu cũ của bạn vẫn được giữ nguyên."
            ),
            tone="danger"
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

    is_knockout = to_bool(row.get("is_knockout"))
    is_finished = to_bool(row.get("is_finished"))

    editable = can_edit_prediction(row.get("kickoff_time_utc"))

    if user_prediction_map is None:
        existing = get_user_prediction(user_id, match_id)
    else:
        existing = user_prediction_map.get(match_id)

    status_info = get_match_status_info(row)
    card_css = get_match_card_css(
        status_info,
        row=row
    )

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
                  AND m.season_slug = :season_slug
                ORDER BY m.kickoff_time_utc
                """,
                {
                    "user_id": int(user_id),
                    "target_match_id": int(match_id),
                    "star_type": star_type,
                    "season_slug": get_selected_season_slug()
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
        render_status_badge(status_info, row=row)
    
        top_left, top_right = st.columns([3, 1])

        with top_left:
            render_match_title(
                home_name,
                away_name,
                match_id,
                row=row
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
            
            st.caption(
                " • ".join(schedule_parts)
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
                    save_col, spacer_col, delete_col = st.columns([1.45, 6.8, 0.85])

                    with save_col:
                        st.form_submit_button(
                            "Cập nhật dự đoán",
                            on_click=handle_prediction_form_submit,
                            kwargs=submit_callback_kwargs
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
                            st.form_submit_button(
                                "Xóa dự đoán",
                                help="Xóa dự đoán đã lưu cho trận này.",
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

    user_predictions = load_predictions(get_selected_season_slug())
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

    score_all_predictions(get_selected_season_slug())

    user_id = st.session_state["user"]["user_id"]

    matches = load_matches(get_selected_season_slug())
    predictions = load_predictions(get_selected_season_slug())

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

    leaderboard = build_leaderboard_df(get_selected_season_slug())

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
def build_leaderboard_df(season_slug: str | None = None):
    users = load_users()
    season_slug = season_slug or get_selected_season_slug()
    predictions = load_predictions(season_slug)
    matches = load_matches(season_slug)

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

    summary["result_prediction_checkable"] = summary["num_scored"]
    
    summary["result_prediction_correct"] = summary["correct_outcome_count"]
    
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

def build_epl_standings_df(matches: pd.DataFrame) -> pd.DataFrame:
    columns = ["Logo", "Đội bóng", "Trận", "Thắng", "Hòa", "Thua", "Bàn thắng", "Bàn thua", "Hiệu số", "Điểm"]

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
                "Điểm": 0
            }
        elif not table[team_key]["Logo"] and logo_path and not pd.isna(logo_path):
            table[team_key]["Logo"] = str(logo_path).strip()

        return table[team_key]

    for _, row in matches.iterrows():
        if pd.notna(row.get("home_team_name")):
            ensure_team(row.get("home_team_id"), row.get("home_team_name"), row.get("home_team_logo_path"))

        if pd.notna(row.get("away_team_name")):
            ensure_team(row.get("away_team_id"), row.get("away_team_name"), row.get("away_team_logo_path"))

    for _, row in matches.iterrows():
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
        elif away_goals > home_goals:
            away_team["Thắng"] += 1
            home_team["Thua"] += 1
            away_team["Điểm"] += 3
        else:
            home_team["Hòa"] += 1
            away_team["Hòa"] += 1
            home_team["Điểm"] += 1
            away_team["Điểm"] += 1

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


def render_epl_standings_table(standings_df: pd.DataFrame):
    if standings_df.empty:
        return

    stat_columns = ["Trận", "Thắng", "Hòa", "Thua", "Bàn thắng", "Bàn thua", "Hiệu số", "Điểm"]
    rows_html = []

    for index, row in standings_df.reset_index(drop=True).iterrows():
        rank = index + 1
        team_name = html.escape(str(row.get("Đội bóng", "")).strip())
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

            cells_html.append(f'<td class="{value_class}">{html.escape(display_value)}</td>')

        rows_html.append(
            f"""
            <tr>
                <td class="rank-cell">{rank}</td>
                <td class="team-cell">
                    <div class="team-wrap">
                        {logo_html}
                        <span>{team_name}</span>
                    </div>
                </td>
                {''.join(cells_html)}
            </tr>
            """
        )

    standings_html = f"""
    <style>
    .epl-standings-box {{
        margin-top: 18px;
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
        min-width: 900px;
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
    .epl-standings-table th:nth-child(2) {{
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
            border-radius: 14px;
        }}
        .epl-standings-table {{
            min-width: 820px;
            font-size: 13px;
        }}
        .epl-standings-table th,
        .epl-standings-table td {{
            padding: 11px 10px;
        }}
    }}
    </style>

    <div class="epl-standings-box">
        <div class="epl-standings-scroll">
            <table class="epl-standings-table">
                <thead>
                    <tr>
                        <th>Hạng</th>
                        <th>Đội bóng</th>
                        <th>Trận</th>
                        <th>Thắng</th>
                        <th>Hòa</th>
                        <th>Thua</th>
                        <th>Bàn thắng</th>
                        <th>Bàn thua</th>
                        <th>Hiệu số</th>
                        <th>Điểm</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows_html)}
                </tbody>
            </table>
        </div>
    </div>
    """

    components.html(
        standings_html,
        height=820,
        scrolling=True
    )


def page_competition_stats():
    render_page_title(
        "Thông số giải đấu",
        f"Bảng xếp hạng EPL {get_selected_season_label()}"
    )

    matches = load_matches(get_selected_season_slug())
    standings = build_epl_standings_df(matches)

    if standings.empty:
        st.info("Chưa có đủ dữ liệu trận đấu để tính bảng xếp hạng.")
        return

    render_epl_standings_table(standings)

def page_leaderboard():
    render_page_title(
        "Bảng xếp hạng",
        "Xem ai đang dẫn đầu cuộc đua dự đoán."
    )

    score_all_predictions(get_selected_season_slug())

    leaderboard = build_leaderboard_df(get_selected_season_slug())

    if leaderboard.empty:
        st.info("Chưa có dữ liệu người chơi.")
        return

    current_display_name = str(st.session_state["user"]["display_name"]).strip()

    if "avatar_key" not in leaderboard.columns:
        leaderboard["avatar_key"] = DEFAULT_AVATAR_KEY

    def format_hope_star_display_for_leaderboard(row):
        quota = get_user_star_quota(int(row["user_id"]))
        hope_total = int(quota["hope_total"])
        hope_used = int(row["hope_stars_used"])
    
        return f"{max(0, hope_total - hope_used)}/{hope_total}"
    
    
    def format_super_star_display_for_leaderboard(row):
        quota = get_user_star_quota(int(row["user_id"]))
        super_total = int(quota["super_total"])
        super_used = int(row["super_stars_used"])
    
        return f"{max(0, super_total - super_used)}/{super_total}"
    
    
    leaderboard["hope_star_display"] = leaderboard.apply(
        format_hope_star_display_for_leaderboard,
        axis=1
    )
    
    leaderboard["super_star_display"] = leaderboard.apply(
        format_super_star_display_for_leaderboard,
        axis=1
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

    score_all_predictions(get_selected_season_slug())

    leaderboard = build_leaderboard_df(get_selected_season_slug())
    predictions = load_predictions(get_selected_season_slug())
    matches = load_matches(get_selected_season_slug())

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
        score_all_predictions(get_selected_season_slug())
        st.success("Đã chấm điểm lại toàn bộ dự đoán.")


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
    
    daily_checkin_popup_opened = maybe_render_daily_checkin_popup(user["user_id"])
    
    if not daily_checkin_popup_opened:
        maybe_render_final_poster_popup(user["user_id"])

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
            "Thông số giải đấu",
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
        if selected_page == "Lịch thi đấu & dự đoán":
            page_matches()

        elif selected_page == "Dự đoán của tôi":
            page_my_predictions()

        elif selected_page == "Bảng xếp hạng":
            page_leaderboard()

        elif selected_page == "Thông số giải đấu":
            page_competition_stats()

        elif selected_page == "Phân tích tổng quan":
            page_dashboard()

        elif selected_page == "Admin":
            page_admin()

        render_footer()

if __name__ == "__main__":
    main()
