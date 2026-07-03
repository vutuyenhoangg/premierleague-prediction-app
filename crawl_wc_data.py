# ============================================================
# WORLD CUP 2026 DATA PIPELINE
# Source: OpenFootball
# Output:
#   1. CSV local
#   2. SQLite local backup
#   3. Safe sync to Supabase for deployed app
#
# Ready for:
#   - Local run with .streamlit/secrets.toml
#   - GitHub Actions run with DATABASE_URL secret
# ============================================================

import os
import re
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

import toml
import requests
import pandas as pd
from sqlalchemy import create_engine, text


# ============================================================
# 1. CONFIG
# ============================================================

SOURCE_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

BASE_DIR = Path(__file__).resolve().parent

OUTPUT_DIR = BASE_DIR / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RAW_JSON_PATH = OUTPUT_DIR / "worldcup_2026_raw.json"
MATCHES_CSV_PATH = OUTPUT_DIR / "worldcup_2026_matches_for_app.csv"
TEAMS_CSV_PATH = OUTPUT_DIR / "worldcup_2026_teams_for_app.csv"
MATCH_GOALS_CSV_PATH = OUTPUT_DIR / "worldcup_2026_match_goals_for_app.csv"

DB_PATH = BASE_DIR / "worldcup_prediction.db"

SECRETS_PATH = BASE_DIR / ".streamlit" / "secrets.toml"

SYNC_TO_SUPABASE = os.getenv("SYNC_TO_SUPABASE", "true").strip().lower() in [
    "true",
    "1",
    "yes",
    "y"
]

REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))

MATCH_GOALS_COLUMNS = [
    "goal_key",
    "match_id",
    "team_id",
    "team_name",
    "team_side",
    "player_name",
    "minute",
    "is_penalty",
    "is_own_goal"
]


# ============================================================
# 2. SUPABASE CONNECTION AND SCHEMA
# ============================================================

def get_supabase_engine():
    """
    Ưu tiên đọc DATABASE_URL từ biến môi trường.
    Dùng cho GitHub Actions.

    Nếu không có biến môi trường, fallback về .streamlit/secrets.toml.
    Dùng cho chạy local.
    """
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        if not SECRETS_PATH.exists():
            raise FileNotFoundError(
                "Không tìm thấy DATABASE_URL trong biến môi trường "
                f"và cũng không tìm thấy secrets file: {SECRETS_PATH}"
            )

        secrets = toml.load(SECRETS_PATH)

        if "DATABASE_URL" not in secrets:
            raise KeyError("Không tìm thấy DATABASE_URL trong secrets.toml")

        database_url = secrets["DATABASE_URL"]

    engine = create_engine(
        database_url,
        pool_pre_ping=True
    )

    return engine


def ensure_supabase_schema(engine):
    """
    Tạo bảng nếu chưa tồn tại.
    Không xóa dữ liệu users, predictions, prediction_history.
    """
    schema_sql_list = [
        """
        CREATE TABLE IF NOT EXISTS teams (
            team_id INTEGER PRIMARY KEY,
            team_name TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS matches (
            match_id INTEGER PRIMARY KEY,
            source_match_id TEXT,

            round_name TEXT,
            stage_type TEXT,
            is_knockout BOOLEAN,

            date_source TEXT,
            time_source TEXT,

            kickoff_time_utc TEXT,
            kickoff_datetime_vietnam TEXT,
            kickoff_date_vietnam TEXT,
            kickoff_date_display_vietnam TEXT,
            kickoff_time_vietnam TEXT,
            kickoff_weekday_vietnam TEXT,
            kickoff_display_vietnam TEXT,

            home_team_id INTEGER,
            home_team_name TEXT,
            away_team_id INTEGER,
            away_team_name TEXT,

            venue TEXT,
            city TEXT,

            score_ft_home INTEGER,
            score_ft_away INTEGER,
            score_et_home INTEGER,
            score_et_away INTEGER,
            score_pen_home INTEGER,
            score_pen_away INTEGER,

            home_score_for_prediction INTEGER,
            away_score_for_prediction INTEGER,

            is_finished BOOLEAN DEFAULT FALSE,

            winner_team_id INTEGER,
            winner_team_name TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS match_goals (
            goal_key TEXT PRIMARY KEY,
            match_id INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,

            team_id INTEGER,
            team_name TEXT,
            team_side TEXT,

            player_name TEXT NOT NULL,
            minute TEXT,

            is_penalty BOOLEAN DEFAULT FALSE,
            is_own_goal BOOLEAN DEFAULT FALSE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_match_goals_match_id
        ON match_goals (match_id)
        """,
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
        """,
        """
        CREATE TABLE IF NOT EXISTS predictions (
            prediction_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            match_id INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,

            predicted_home_score INTEGER NOT NULL,
            predicted_away_score INTEGER NOT NULL,
            predicted_winner_team_id INTEGER,

            points INTEGER,

            submitted_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            UNIQUE(user_id, match_id)
        )
        """,
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
    ]

    with engine.begin() as conn:
        for schema_sql in schema_sql_list:
            conn.execute(text(schema_sql))


# ============================================================
# 3. DOWNLOAD RAW JSON
# ============================================================

def download_json(url: str) -> dict:
    """
    Download JSON từ OpenFootball.
    """
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


# ============================================================
# 4. HELPER FUNCTIONS
# ============================================================

def get_first_existing_value(data: dict, keys: list, default=None):
    """
    Lấy giá trị đầu tiên tồn tại trong dict theo danh sách key.
    """
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def get_first_not_none(data: dict, keys: list, default=None):
    """
    Lấy giá trị đầu tiên khác None.
    Khác với dùng 'or' vì tỉ số 0 là giá trị hợp lệ.
    """
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def normalize_team_name(value):
    """
    Chuẩn hóa tên đội.
    OpenFootball thường để team1/team2 là string.
    Nhưng hàm này vẫn xử lý trường hợp value là dict.
    """
    if value is None:
        return None

    if isinstance(value, dict):
        return (
            value.get("name")
            or value.get("title")
            or value.get("code")
            or value.get("key")
            or str(value)
        )

    return str(value).strip()


def get_score_pair(score_obj, possible_keys):
    """
    Lấy cặp tỉ số từ object score.

    OpenFootball thường có dạng:
    score = {
        "ft": [2, 0],
        "et": [1, 1],
        "p": [4, 3]
    }
    """
    if not isinstance(score_obj, dict):
        return None, None

    value = None

    for key in possible_keys:
        if key in score_obj:
            value = score_obj.get(key)
            break

    if value is None:
        return None, None

    if isinstance(value, list) and len(value) >= 2:
        return value[0], value[1]

    if isinstance(value, tuple) and len(value) >= 2:
        return value[0], value[1]

    if isinstance(value, dict):
        home_score = get_first_not_none(
            value,
            ["home", "team1", "score1", "h"],
            default=None
        )
        away_score = get_first_not_none(
            value,
            ["away", "team2", "score2", "a"],
            default=None
        )
        return home_score, away_score

    return None, None


def parse_match_datetime_to_utc(date_value, time_value):
    """
    Parse date + time có format kiểu:
    date = '2026-06-11'
    time = '13:00 UTC-6'

    Trả về Timestamp UTC.
    """
    if pd.isna(date_value) or pd.isna(time_value):
        return pd.NaT

    date_str = str(date_value).strip()
    time_str = str(time_value).replace("\n", " ").strip()

    time_str = (
        time_str
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
    )

    pattern = r"(\d{1,2}):(\d{2})(?::\d{2})?\s*(?:UTC|GMT)\s*([+-]\d{1,2})(?::?(\d{2}))?"
    match = re.search(pattern, time_str, flags=re.IGNORECASE)

    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        offset_hours = int(match.group(3))
        offset_minutes = int(match.group(4)) if match.group(4) else 0

        if offset_hours < 0:
            offset_minutes = -abs(offset_minutes)

    else:
        pattern_utc_zero = r"(\d{1,2}):(\d{2})(?::\d{2})?\s*(?:UTC|GMT)\b"
        match_zero = re.search(pattern_utc_zero, time_str, flags=re.IGNORECASE)

        if match_zero:
            hour = int(match_zero.group(1))
            minute = int(match_zero.group(2))
            offset_hours = 0
            offset_minutes = 0
        else:
            raise ValueError(
                f"Không parse được time='{time_value}'. "
                f"Format kỳ vọng ví dụ: '13:00 UTC-6'"
            )

    local_date = datetime.strptime(date_str, "%Y-%m-%d")

    local_dt = local_date.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
        tzinfo=timezone(timedelta(hours=offset_hours, minutes=offset_minutes))
    )

    utc_dt = local_dt.astimezone(timezone.utc)

    return pd.Timestamp(utc_dt)


def infer_stage_type(round_name, match_id=None):
    """
    Phân loại group/knockout.
    """
    if round_name is None or pd.isna(round_name):
        if match_id is not None and match_id <= 72:
            return "group"
        return "unknown"

    r = str(round_name).lower().strip()

    knockout_keywords = [
        "round of 32",
        "round of 16",
        "quarter",
        "semi",
        "final",
        "third",
        "place",
        "knockout",
        "playoff",
        "play-off"
    ]

    group_keywords = [
        "group",
        "matchday"
    ]

    if any(keyword in r for keyword in knockout_keywords):
        return "knockout"

    if any(keyword in r for keyword in group_keywords):
        return "group"

    if match_id is not None:
        return "group" if match_id <= 72 else "knockout"

    return "unknown"


def calculate_prediction_scores(row):
    """
    Tạo tỉ số dùng cho app prediction.

    Rule của app:
    - Nếu có hiệp phụ, lấy tỉ số sau hiệp phụ.
    - Nếu không có hiệp phụ, lấy tỉ số full-time.
    - Không cộng penalty vào tỉ số.
    """
    ft_home = row.get("score_ft_home")
    ft_away = row.get("score_ft_away")
    et_home = row.get("score_et_home")
    et_away = row.get("score_et_away")

    if pd.notna(et_home) and pd.notna(et_away):
        return et_home, et_away

    return ft_home, ft_away


def infer_winner_team_name(row):
    """
    Xác định đội thắng/đi tiếp.

    - Vòng bảng hòa thì winner = None.
    - Knockout hòa sau hiệp phụ thì dùng penalty để xác định đội đi tiếp.
    """
    home_team = row.get("home_team_name")
    away_team = row.get("away_team_name")

    home_score = row.get("home_score_for_prediction")
    away_score = row.get("away_score_for_prediction")

    pen_home = row.get("score_pen_home")
    pen_away = row.get("score_pen_away")

    is_knockout = bool(row.get("is_knockout"))

    if pd.isna(home_score) or pd.isna(away_score):
        return None

    if home_score > away_score:
        return home_team

    if away_score > home_score:
        return away_team

    if is_knockout:
        if pd.notna(pen_home) and pd.notna(pen_away):
            if pen_home > pen_away:
                return home_team
            if pen_away > pen_home:
                return away_team

    return None


def is_finished_match(row):
    """
    Một trận được xem là đã có kết quả nếu có tỉ số full-time.
    """
    return (
        pd.notna(row.get("score_ft_home"))
        and pd.notna(row.get("score_ft_away"))
    )


def map_weekday_to_vietnamese(weekday_en):
    """
    Đổi tên thứ tiếng Anh sang tiếng Việt.
    """
    mapping = {
        "Monday": "Thứ 2",
        "Tuesday": "Thứ 3",
        "Wednesday": "Thứ 4",
        "Thursday": "Thứ 5",
        "Friday": "Thứ 6",
        "Saturday": "Thứ 7",
        "Sunday": "Chủ nhật"
    }

    return mapping.get(weekday_en, weekday_en)


def get_outcome(home_score, away_score):
    if home_score > away_score:
        return "HOME_WIN"

    if home_score < away_score:
        return "AWAY_WIN"

    return "DRAW"


def to_optional_int(value):
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    return int(value)


def to_bool(value) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass

    if isinstance(value, (int, float)):
        return value == 1

    value_str = str(value).strip().lower()

    return value_str in ["true", "1", "yes", "y"]


def clean_value_for_db(value):
    """
    Convert pandas/numpy values sang Python scalar để psycopg2 xử lý ổn.
    """
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return value

    return value


def normalize_goal_minute(goal: dict) -> str | None:
    """
    Chuẩn hóa phút ghi bàn để sau này hiển thị UI dạng:
    32'
    45+2'
    """
    minute = goal.get("minute")
    offset = goal.get("offset")

    if minute is None:
        return None

    minute_text = str(minute).strip().replace("’", "'")

    if not minute_text:
        return None

    minute_text = minute_text.rstrip("'")

    if offset is not None:
        offset_text = str(offset).strip().rstrip("'")

        if offset_text:
            return f"{minute_text}+{offset_text}'"

    return f"{minute_text}'"


def normalize_goal_item(goal):
    """
    Chuẩn hóa 1 bàn thắng từ OpenFootball.

    Output giữ đủ thông tin để UI hiển thị kiểu:
    Tên cầu thủ 32'
    Tên cầu thủ 55' (OG)
    Tên cầu thủ 70' (pen)
    """
    if goal is None:
        return None

    if isinstance(goal, dict):
        player_name = (
            goal.get("name")
            or goal.get("player")
            or goal.get("scorer")
            or goal.get("player_name")
        )

        if not player_name:
            return None

        return {
            "player_name": str(player_name).strip(),
            "minute": normalize_goal_minute(goal),
            "is_penalty": bool(
                goal.get("penalty", False)
                or goal.get("pen", False)
            ),
            "is_own_goal": bool(
                goal.get("owngoal", False)
                or goal.get("own_goal", False)
                or goal.get("ownGoal", False)
                or goal.get("og", False)
            )
        }

    goal_text = str(goal).strip()

    if not goal_text:
        return None

    return {
        "player_name": goal_text,
        "minute": None,
        "is_penalty": False,
        "is_own_goal": False
    }


# ============================================================
# 5. EXTRACT AND NORMALIZE MATCHES
# ============================================================

def extract_matches_from_openfootball(data: dict) -> list:
    """
    OpenFootball 2026 thường có key 'matches'.
    """
    if isinstance(data, dict) and isinstance(data.get("matches"), list):
        return data["matches"]

    raise ValueError(
        "Không tìm thấy key 'matches' trong JSON. "
        "Hãy mở raw JSON để kiểm tra lại schema."
    )


def normalize_matches(matches_raw: list) -> pd.DataFrame:
    rows = []

    for idx, match in enumerate(matches_raw, start=1):
        score_obj = match.get("score", {}) or {}

        ft_home, ft_away = get_score_pair(
            score_obj,
            ["ft", "fulltime", "full_time"]
        )

        et_home, et_away = get_score_pair(
            score_obj,
            ["et", "extratime", "extra_time"]
        )

        pen_home, pen_away = get_score_pair(
            score_obj,
            ["p", "pen", "penalty", "penalties"]
        )

        round_name = get_first_existing_value(
            match,
            ["round", "round_name", "stage", "stage_name"],
            default=None
        )

        date_value = match.get("date")
        time_value = match.get("time")

        home_team_name = normalize_team_name(
            get_first_existing_value(match, ["team1", "home_team", "home"])
        )

        away_team_name = normalize_team_name(
            get_first_existing_value(match, ["team2", "away_team", "away"])
        )

        venue = get_first_existing_value(
            match,
            ["stadium", "venue", "venue_name", "ground"],
            default=None
        )
        
        city = get_first_existing_value(
            match,
            ["city", "venue_city"],
            default=None
        )

        rows.append({
            "match_id": idx,
            "source_match_id": str(match.get("id") or match.get("num") or idx),

            "round_name": round_name,
            "date_source": date_value,
            "time_source": time_value,

            "home_team_name": home_team_name,
            "away_team_name": away_team_name,

            "venue": venue,
            "city": city,

            "score_ft_home": ft_home,
            "score_ft_away": ft_away,
            "score_et_home": et_home,
            "score_et_away": et_away,
            "score_pen_home": pen_home,
            "score_pen_away": pen_away,

            "raw_match_json": json.dumps(match, ensure_ascii=False)
        })

    return pd.DataFrame(rows)


def normalize_match_datetimes(matches_df: pd.DataFrame) -> pd.DataFrame:
    result = matches_df.copy()

    result["kickoff_time_utc"] = result.apply(
        lambda row: parse_match_datetime_to_utc(
            row["date_source"],
            row["time_source"]
        ),
        axis=1
    )

    result["kickoff_datetime_vietnam"] = result["kickoff_time_utc"].dt.tz_convert(
        "Asia/Ho_Chi_Minh"
    )

    result["kickoff_date_vietnam"] = result["kickoff_datetime_vietnam"].dt.date

    result["kickoff_time_vietnam"] = result["kickoff_datetime_vietnam"].dt.strftime("%H:%M")

    result["kickoff_weekday_vietnam_en"] = result["kickoff_datetime_vietnam"].dt.day_name()

    result["kickoff_weekday_vietnam"] = result["kickoff_weekday_vietnam_en"].apply(
        map_weekday_to_vietnamese
    )

    result["kickoff_date_display_vietnam"] = result["kickoff_datetime_vietnam"].dt.strftime(
        "%d/%m/%Y"
    )

    result["kickoff_display_vietnam"] = result["kickoff_datetime_vietnam"].dt.strftime(
        "%H:%M, %d/%m/%Y"
    )

    return result


def enrich_matches(matches_df: pd.DataFrame) -> pd.DataFrame:
    result = matches_df.copy()

    score_cols = [
        "score_ft_home",
        "score_ft_away",
        "score_et_home",
        "score_et_away",
        "score_pen_home",
        "score_pen_away"
    ]

    for col in score_cols:
        result[col] = pd.to_numeric(result[col], errors="coerce").astype("Int64")

    result["stage_type"] = result.apply(
        lambda row: infer_stage_type(row["round_name"], row["match_id"]),
        axis=1
    )

    result["is_knockout"] = result["stage_type"].eq("knockout")

    result[["home_score_for_prediction", "away_score_for_prediction"]] = result.apply(
        lambda row: pd.Series(calculate_prediction_scores(row)),
        axis=1
    )

    result["home_score_for_prediction"] = pd.to_numeric(
        result["home_score_for_prediction"],
        errors="coerce"
    ).astype("Int64")

    result["away_score_for_prediction"] = pd.to_numeric(
        result["away_score_for_prediction"],
        errors="coerce"
    ).astype("Int64")

    result["is_finished"] = result.apply(is_finished_match, axis=1)

    result["winner_team_name"] = result.apply(infer_winner_team_name, axis=1)

    return result


# ============================================================
# 6. TEAM MAPPING
# ============================================================

def get_team_names_from_matches(matches_df: pd.DataFrame) -> list[str]:
    team_names = pd.concat(
        [
            matches_df["home_team_name"],
            matches_df["away_team_name"]
        ],
        ignore_index=True
    )

    team_names = (
        team_names
        .dropna()
        .astype(str)
        .str.strip()
    )

    team_names = team_names[team_names.ne("")]

    return sorted(team_names.unique())


def get_existing_team_mapping_from_supabase(engine) -> dict:
    """
    Lấy team_id hiện có từ Supabase để không đánh lại ID mỗi lần crawl.
    """
    with engine.connect() as conn:
        existing_teams = pd.read_sql_query(
            text(
                """
                SELECT team_id, team_name
                FROM teams
                ORDER BY team_id
                """
            ),
            conn
        )

    if existing_teams.empty:
        return {}

    existing_teams["team_name"] = existing_teams["team_name"].astype(str).str.strip()
    existing_teams = existing_teams.drop_duplicates(subset=["team_name"], keep="first")

    return dict(zip(existing_teams["team_name"], existing_teams["team_id"]))


def build_stable_team_table(team_names: list[str], engine=None) -> tuple[pd.DataFrame, dict]:
    """
    Nếu sync Supabase:
    - Giữ nguyên team_id đã tồn tại theo team_name.
    - Team mới thì lấy max(team_id) + 1.

    Nếu không sync:
    - Dùng ID local theo alphabet.
    """
    if engine is not None:
        existing_mapping = get_existing_team_mapping_from_supabase(engine)
    else:
        existing_mapping = {}

    team_name_to_id = {}
    used_ids = set()

    for team_name, team_id in existing_mapping.items():
        team_id = int(team_id)
        team_name_to_id[team_name] = team_id
        used_ids.add(team_id)

    next_team_id = max(used_ids) + 1 if used_ids else 1

    for team_name in team_names:
        if team_name in team_name_to_id:
            continue

        team_name_to_id[team_name] = next_team_id
        next_team_id += 1

    teams_df = pd.DataFrame(
        [
            {
                "team_id": team_id,
                "team_name": team_name
            }
            for team_name, team_id in team_name_to_id.items()
            if team_name in team_names
        ]
    )

    teams_df = teams_df.sort_values("team_id").reset_index(drop=True)

    return teams_df, team_name_to_id


# ============================================================
# 7. MATCH GOALS
# ============================================================

def extract_match_goals_from_openfootball(
    matches_raw: list,
    team_name_to_id: dict
) -> pd.DataFrame:
    """
    Tách goals1/goals2 từ OpenFootball thành bảng match_goals.

    goals1 = cầu thủ ghi bàn của đội home/team1
    goals2 = cầu thủ ghi bàn của đội away/team2
    """
    goal_rows = []

    for match_id, match in enumerate(matches_raw, start=1):
        home_team_name = normalize_team_name(
            get_first_existing_value(match, ["team1", "home_team", "home"])
        )

        away_team_name = normalize_team_name(
            get_first_existing_value(match, ["team2", "away_team", "away"])
        )

        goal_sources = [
            {
                "team_side": "home",
                "goals_key": "goals1",
                "team_name": home_team_name
            },
            {
                "team_side": "away",
                "goals_key": "goals2",
                "team_name": away_team_name
            }
        ]

        for source in goal_sources:
            goals = match.get(source["goals_key"], [])

            if goals is None:
                goals = []

            if isinstance(goals, dict):
                goals = [goals]

            if not isinstance(goals, list):
                continue

            for goal_order, goal in enumerate(goals, start=1):
                normalized_goal = normalize_goal_item(goal)

                if normalized_goal is None:
                    continue

                team_name = source["team_name"]
                team_id = team_name_to_id.get(team_name)

                goal_rows.append({
                    "goal_key": f"{match_id}_{source['team_side']}_{goal_order}",
                    "match_id": match_id,
                    "team_id": team_id,
                    "team_name": team_name,
                    "team_side": source["team_side"],
                    "player_name": normalized_goal["player_name"],
                    "minute": normalized_goal["minute"],
                    "is_penalty": normalized_goal["is_penalty"],
                    "is_own_goal": normalized_goal["is_own_goal"]
                })

    return pd.DataFrame(goal_rows, columns=MATCH_GOALS_COLUMNS)


# ============================================================
# 8. FINAL TABLES
# ============================================================

def build_matches_for_app(matches_df: pd.DataFrame) -> pd.DataFrame:
    return matches_df[
        [
            "match_id",
            "source_match_id",

            "round_name",
            "stage_type",
            "is_knockout",

            "date_source",
            "time_source",

            "kickoff_time_utc",
            "kickoff_datetime_vietnam",
            "kickoff_date_vietnam",
            "kickoff_date_display_vietnam",
            "kickoff_time_vietnam",
            "kickoff_weekday_vietnam",
            "kickoff_display_vietnam",

            "home_team_id",
            "home_team_name",
            "away_team_id",
            "away_team_name",

            "venue",
            "city",

            "score_ft_home",
            "score_ft_away",
            "score_et_home",
            "score_et_away",
            "score_pen_home",
            "score_pen_away",

            "home_score_for_prediction",
            "away_score_for_prediction",

            "is_finished",
            "winner_team_id",
            "winner_team_name"
        ]
    ].copy()


def print_data_quality_checks(matches_for_app: pd.DataFrame, teams_df: pd.DataFrame):
    print("\n========== DATA QUALITY CHECK ==========")
    print("Số trận:", len(matches_for_app))
    print("Số đội/team hiện tại:", len(teams_df))

    print("\nStage type:")
    print(matches_for_app["stage_type"].value_counts(dropna=False))

    print("\nFinished status từ nguồn crawl:")
    print(matches_for_app["is_finished"].value_counts(dropna=False))

    print("\nMissing kickoff_time_utc:", matches_for_app["kickoff_time_utc"].isna().sum())
    print("Missing home_team_name:", matches_for_app["home_team_name"].isna().sum())
    print("Missing away_team_name:", matches_for_app["away_team_name"].isna().sum())

    print("\nScore dtypes:")
    print(
        matches_for_app[
            [
                "score_ft_home",
                "score_ft_away",
                "score_et_home",
                "score_et_away",
                "score_pen_home",
                "score_pen_away",
                "home_score_for_prediction",
                "away_score_for_prediction"
            ]
        ].dtypes
    )


# ============================================================
# 9. LOCAL SAVE
# ============================================================

def prepare_for_sqlite(df: pd.DataFrame) -> pd.DataFrame:
    """
    SQLite không lưu timezone-aware Timestamp đẹp như PostgreSQL,
    nên convert datetime/date sang string.
    Int64 nullable cũng được convert để SQLite nhận NULL ổn hơn.
    """
    sql_df = df.copy()

    date_time_cols = [
        "kickoff_time_utc",
        "kickoff_datetime_vietnam",
        "kickoff_date_vietnam"
    ]

    for col in date_time_cols:
        if col in sql_df.columns:
            sql_df[col] = sql_df[col].astype("string")
            sql_df[col] = sql_df[col].where(pd.notna(sql_df[col]), None)

    for col in sql_df.columns:
        if str(sql_df[col].dtype) == "Int64":
            sql_df[col] = sql_df[col].astype(object)
            sql_df[col] = sql_df[col].where(pd.notna(sql_df[col]), None)

    sql_df = sql_df.where(pd.notna(sql_df), None)

    return sql_df


def save_outputs_to_csv(
    matches_for_app: pd.DataFrame,
    teams_df: pd.DataFrame,
    match_goals_df: pd.DataFrame
):
    matches_for_app.to_csv(
        MATCHES_CSV_PATH,
        index=False,
        encoding="utf-8-sig"
    )

    teams_df.to_csv(
        TEAMS_CSV_PATH,
        index=False,
        encoding="utf-8-sig"
    )

    match_goals_df.to_csv(
        MATCH_GOALS_CSV_PATH,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"\nĐã lưu matches CSV: {MATCHES_CSV_PATH}")
    print(f"Đã lưu teams CSV: {TEAMS_CSV_PATH}")
    print(f"Đã lưu match goals CSV: {MATCH_GOALS_CSV_PATH}")


def save_outputs_to_sqlite(
    matches_for_app: pd.DataFrame,
    teams_df: pd.DataFrame,
    match_goals_df: pd.DataFrame
):
    matches_sql = prepare_for_sqlite(matches_for_app)
    teams_sql = prepare_for_sqlite(teams_df)
    match_goals_sql = prepare_for_sqlite(match_goals_df)

    with sqlite3.connect(DB_PATH) as conn:
        matches_sql.to_sql("matches", conn, if_exists="replace", index=False)
        teams_sql.to_sql("teams", conn, if_exists="replace", index=False)
        match_goals_sql.to_sql("match_goals", conn, if_exists="replace", index=False)

    print(f"Đã lưu SQLite database local backup: {DB_PATH}")


# ============================================================
# 10. PREPARE DATA FOR POSTGRES
# ============================================================

def prepare_for_postgres(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    date_time_cols = [
        "kickoff_time_utc",
        "kickoff_datetime_vietnam",
        "kickoff_date_vietnam"
    ]

    for col in date_time_cols:
        if col in result.columns:
            result[col] = result[col].astype("string")
            result[col] = result[col].where(pd.notna(result[col]), None)

    if "source_match_id" in result.columns:
        result["source_match_id"] = result["source_match_id"].astype("string")
        result["source_match_id"] = result["source_match_id"].where(
            pd.notna(result["source_match_id"]),
            None
        )

    for col in result.columns:
        if str(result[col].dtype) == "Int64":
            result[col] = result[col].astype(object)
            result[col] = result[col].where(pd.notna(result[col]), None)

    result = result.where(pd.notna(result), None)

    return result


def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    records = df.to_dict(orient="records")

    clean_records = []

    for record in records:
        clean_record = {
            key: clean_value_for_db(value)
            for key, value in record.items()
        }
        clean_records.append(clean_record)

    return clean_records


# ============================================================
# 11. SAFE SYNC TO SUPABASE
# ============================================================

def sync_teams_to_supabase(engine, teams_df: pd.DataFrame):
    teams_pg = prepare_for_postgres(teams_df)
    team_records = dataframe_to_records(teams_pg)

    if not team_records:
        print("Không có team nào để sync.")
        return

    upsert_team_sql = text(
        """
        INSERT INTO teams (
            team_id,
            team_name
        )
        VALUES (
            :team_id,
            :team_name
        )
        ON CONFLICT (team_id)
        DO UPDATE SET
            team_name = EXCLUDED.team_name
        """
    )

    with engine.begin() as conn:
        conn.execute(upsert_team_sql, team_records)

    print(f"Đã sync teams lên Supabase: {len(team_records)} dòng")


def sync_matches_to_supabase(engine, matches_for_app: pd.DataFrame):
    """
    Safe sync:
    - Luôn update thông tin lịch, đội, venue.
    - Chỉ update score/result nếu nguồn crawl có kết quả thật.
    - Nếu nguồn crawl chưa có score, không ghi đè kết quả đã có trên Supabase.
    """
    matches_pg = prepare_for_postgres(matches_for_app)
    match_records = dataframe_to_records(matches_pg)

    if not match_records:
        print("Không có match nào để sync.")
        return

    upsert_match_sql = text(
        """
        INSERT INTO matches (
            match_id,
            source_match_id,

            round_name,
            stage_type,
            is_knockout,

            date_source,
            time_source,

            kickoff_time_utc,
            kickoff_datetime_vietnam,
            kickoff_date_vietnam,
            kickoff_date_display_vietnam,
            kickoff_time_vietnam,
            kickoff_weekday_vietnam,
            kickoff_display_vietnam,

            home_team_id,
            home_team_name,
            away_team_id,
            away_team_name,

            venue,
            city,

            score_ft_home,
            score_ft_away,
            score_et_home,
            score_et_away,
            score_pen_home,
            score_pen_away,

            home_score_for_prediction,
            away_score_for_prediction,

            is_finished,
            winner_team_id,
            winner_team_name
        )
        VALUES (
            :match_id,
            :source_match_id,

            :round_name,
            :stage_type,
            :is_knockout,

            :date_source,
            :time_source,

            :kickoff_time_utc,
            :kickoff_datetime_vietnam,
            :kickoff_date_vietnam,
            :kickoff_date_display_vietnam,
            :kickoff_time_vietnam,
            :kickoff_weekday_vietnam,
            :kickoff_display_vietnam,

            :home_team_id,
            :home_team_name,
            :away_team_id,
            :away_team_name,

            :venue,
            :city,

            :score_ft_home,
            :score_ft_away,
            :score_et_home,
            :score_et_away,
            :score_pen_home,
            :score_pen_away,

            :home_score_for_prediction,
            :away_score_for_prediction,

            :is_finished,
            :winner_team_id,
            :winner_team_name
        )
        ON CONFLICT (match_id)
        DO UPDATE SET
            source_match_id = EXCLUDED.source_match_id,

            round_name = EXCLUDED.round_name,
            stage_type = EXCLUDED.stage_type,
            is_knockout = EXCLUDED.is_knockout,

            date_source = EXCLUDED.date_source,
            time_source = EXCLUDED.time_source,

            kickoff_time_utc = EXCLUDED.kickoff_time_utc,
            kickoff_datetime_vietnam = EXCLUDED.kickoff_datetime_vietnam,
            kickoff_date_vietnam = EXCLUDED.kickoff_date_vietnam,
            kickoff_date_display_vietnam = EXCLUDED.kickoff_date_display_vietnam,
            kickoff_time_vietnam = EXCLUDED.kickoff_time_vietnam,
            kickoff_weekday_vietnam = EXCLUDED.kickoff_weekday_vietnam,
            kickoff_display_vietnam = EXCLUDED.kickoff_display_vietnam,

            home_team_id = EXCLUDED.home_team_id,
            home_team_name = EXCLUDED.home_team_name,
            away_team_id = EXCLUDED.away_team_id,
            away_team_name = EXCLUDED.away_team_name,

            venue = EXCLUDED.venue,
            city = EXCLUDED.city,

            score_ft_home =
                CASE
                    WHEN EXCLUDED.is_finished IS TRUE THEN EXCLUDED.score_ft_home
                    ELSE matches.score_ft_home
                END,

            score_ft_away =
                CASE
                    WHEN EXCLUDED.is_finished IS TRUE THEN EXCLUDED.score_ft_away
                    ELSE matches.score_ft_away
                END,

            score_et_home =
                CASE
                    WHEN EXCLUDED.is_finished IS TRUE THEN EXCLUDED.score_et_home
                    ELSE matches.score_et_home
                END,

            score_et_away =
                CASE
                    WHEN EXCLUDED.is_finished IS TRUE THEN EXCLUDED.score_et_away
                    ELSE matches.score_et_away
                END,

            score_pen_home =
                CASE
                    WHEN EXCLUDED.is_finished IS TRUE THEN EXCLUDED.score_pen_home
                    ELSE matches.score_pen_home
                END,

            score_pen_away =
                CASE
                    WHEN EXCLUDED.is_finished IS TRUE THEN EXCLUDED.score_pen_away
                    ELSE matches.score_pen_away
                END,

            home_score_for_prediction =
                CASE
                    WHEN EXCLUDED.is_finished IS TRUE THEN EXCLUDED.home_score_for_prediction
                    ELSE matches.home_score_for_prediction
                END,

            away_score_for_prediction =
                CASE
                    WHEN EXCLUDED.is_finished IS TRUE THEN EXCLUDED.away_score_for_prediction
                    ELSE matches.away_score_for_prediction
                END,

            is_finished =
                CASE
                    WHEN EXCLUDED.is_finished IS TRUE THEN TRUE
                    ELSE matches.is_finished
                END,

            winner_team_id =
                CASE
                    WHEN EXCLUDED.is_finished IS TRUE THEN EXCLUDED.winner_team_id
                    ELSE matches.winner_team_id
                END,

            winner_team_name =
                CASE
                    WHEN EXCLUDED.is_finished IS TRUE THEN EXCLUDED.winner_team_name
                    ELSE matches.winner_team_name
                END
        """
    )

    with engine.begin() as conn:
        conn.execute(upsert_match_sql, match_records)

    print(f"Đã sync matches lên Supabase: {len(match_records)} dòng")


def sync_match_goals_to_supabase(engine, match_goals_df: pd.DataFrame):
    """
    Sync dữ liệu cầu thủ ghi bàn lên Supabase.

    Bảng này chỉ phục vụ hiển thị UI.
    Không ảnh hưởng logic dự đoán, tính điểm, BXH.
    """
    if match_goals_df.empty:
        print("Không có dữ liệu cầu thủ ghi bàn để sync. Giữ nguyên bảng match_goals.")
        return

    goals_pg = prepare_for_postgres(match_goals_df)
    goal_records = dataframe_to_records(goals_pg)

    delete_sql = text(
        """
        DELETE FROM match_goals
        """
    )

    insert_sql = text(
        """
        INSERT INTO match_goals (
            goal_key,
            match_id,
            team_id,
            team_name,
            team_side,
            player_name,
            minute,
            is_penalty,
            is_own_goal
        )
        VALUES (
            :goal_key,
            :match_id,
            :team_id,
            :team_name,
            :team_side,
            :player_name,
            :minute,
            :is_penalty,
            :is_own_goal
        )
        """
    )

    with engine.begin() as conn:
        conn.execute(delete_sql)
        conn.execute(insert_sql, goal_records)

    print(f"Đã sync match_goals lên Supabase: {len(goal_records)} dòng")


# ============================================================
# 12. RESCORE PREDICTIONS AFTER SYNC
# ============================================================

def calculate_prediction_points_from_row(row) -> int | None:
    pred_home = to_optional_int(row.get("predicted_home_score"))
    pred_away = to_optional_int(row.get("predicted_away_score"))

    actual_home = to_optional_int(row.get("home_score_for_prediction"))
    actual_away = to_optional_int(row.get("away_score_for_prediction"))

    is_finished = to_bool(row.get("is_finished"))

    if (
        not is_finished
        or pred_home is None
        or pred_away is None
        or actual_home is None
        or actual_away is None
    ):
        return None

    if pred_home == actual_home and pred_away == actual_away:
        points = 3
    elif get_outcome(pred_home, pred_away) == get_outcome(actual_home, actual_away):
        points = 1
    else:
        points = 0

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


def rescore_predictions_on_supabase(engine):
    """
    Chấm điểm lại toàn bộ predictions sau khi sync matches.

    Logic:
    - Đúng tỉ số: 3 điểm
    - Đúng kết quả thắng/hòa/thua: 1 điểm
    - Knockout đúng đội đi tiếp: +1 điểm
    """
    query = text(
        """
        SELECT
            p.prediction_id,
            p.predicted_home_score,
            p.predicted_away_score,
            p.predicted_winner_team_id,

            m.home_score_for_prediction,
            m.away_score_for_prediction,
            m.is_finished,
            m.is_knockout,
            m.winner_team_id
        FROM predictions p
        JOIN matches m
            ON p.match_id = m.match_id
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql_query(query, conn)

    if df.empty:
        print("Chưa có prediction nào để chấm điểm.")
        return

    update_records = []

    for _, row in df.iterrows():
        points = calculate_prediction_points_from_row(row)

        update_records.append(
            {
                "prediction_id": int(row["prediction_id"]),
                "points": points
            }
        )

    update_sql = text(
        """
        UPDATE predictions
        SET points = :points
        WHERE prediction_id = :prediction_id
        """
    )

    with engine.begin() as conn:
        conn.execute(update_sql, update_records)

    print(f"Đã chấm điểm lại predictions: {len(update_records)} dòng")


# ============================================================
# 13. QUICK PREVIEW
# ============================================================

def print_quick_preview(matches_for_app: pd.DataFrame, match_goals_df: pd.DataFrame):
    preview_cols = [
        "match_id",
        "round_name",
        "stage_type",
        "kickoff_date_display_vietnam",
        "kickoff_time_vietnam",
        "kickoff_weekday_vietnam",
        "home_team_name",
        "away_team_name",
        "score_ft_home",
        "score_ft_away",
        "score_et_home",
        "score_et_away",
        "score_pen_home",
        "score_pen_away",
        "home_score_for_prediction",
        "away_score_for_prediction",
        "is_finished",
        "winner_team_name"
    ]

    print("\n========== MATCHES PREVIEW ==========")
    print(matches_for_app[preview_cols].head(20))

    print("\n========== MATCH GOALS PREVIEW ==========")

    if match_goals_df.empty:
        print("Chưa có dữ liệu cầu thủ ghi bàn.")
    else:
        print("Số dòng cầu thủ ghi bàn:", len(match_goals_df))
        print(
            match_goals_df[
                [
                    "match_id",
                    "team_name",
                    "team_side",
                    "player_name",
                    "minute",
                    "is_penalty",
                    "is_own_goal"
                ]
            ].head(30)
        )


# ============================================================
# 14. MAIN PIPELINE
# ============================================================

def run_pipeline():
    if SYNC_TO_SUPABASE:
        supabase_engine = get_supabase_engine()
        ensure_supabase_schema(supabase_engine)
    else:
        supabase_engine = None

    raw_data = download_json(SOURCE_URL)

    with open(RAW_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)

    print(f"Đã tải raw JSON và lưu tại: {RAW_JSON_PATH}")

    matches_raw = extract_matches_from_openfootball(raw_data)
    print(f"Số trận raw lấy được: {len(matches_raw)}")

    matches_df = normalize_matches(matches_raw)
    matches_df = normalize_match_datetimes(matches_df)
    matches_df = enrich_matches(matches_df)

    team_names = get_team_names_from_matches(matches_df)

    teams_df, team_name_to_id = build_stable_team_table(
        team_names=team_names,
        engine=supabase_engine if SYNC_TO_SUPABASE else None
    )

    matches_df["home_team_id"] = matches_df["home_team_name"].map(team_name_to_id).astype("Int64")
    matches_df["away_team_id"] = matches_df["away_team_name"].map(team_name_to_id).astype("Int64")
    matches_df["winner_team_id"] = matches_df["winner_team_name"].map(team_name_to_id).astype("Int64")

    match_goals_df = extract_match_goals_from_openfootball(
        matches_raw=matches_raw,
        team_name_to_id=team_name_to_id
    )

    matches_for_app = build_matches_for_app(matches_df)

    print_data_quality_checks(matches_for_app, teams_df)

    save_outputs_to_csv(
        matches_for_app=matches_for_app,
        teams_df=teams_df,
        match_goals_df=match_goals_df
    )

    save_outputs_to_sqlite(
        matches_for_app=matches_for_app,
        teams_df=teams_df,
        match_goals_df=match_goals_df
    )

    if SYNC_TO_SUPABASE:
        sync_teams_to_supabase(supabase_engine, teams_df)
        sync_matches_to_supabase(supabase_engine, matches_for_app)
        sync_match_goals_to_supabase(supabase_engine, match_goals_df)
        rescore_predictions_on_supabase(supabase_engine)

        print("\n========== SUPABASE SYNC DONE ==========")
        print("Đã cập nhật dữ liệu lên app deploy.")
        print("Đã cập nhật dữ liệu cầu thủ ghi bàn.")
        print("Không xóa users / predictions / prediction_history.")
    else:
        print("SYNC_TO_SUPABASE = False, bỏ qua bước sync Supabase.")

    print_quick_preview(matches_for_app, match_goals_df)


if __name__ == "__main__":
    run_pipeline()
