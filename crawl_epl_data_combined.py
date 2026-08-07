from __future__ import annotations
from pathlib import Path
import hashlib
import json
import os
import re
import time
import unicodedata
from collections import Counter
import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from sqlalchemy import (
    MetaData,
    Table,
    bindparam,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool


COMPETITION_KEY = "epl"
SEASON_SLUG = os.getenv("EPL_SEASON_SLUG", "2026-27").strip()

TARGET_TIMEZONE = "Asia/Ho_Chi_Minh"
SOURCE_TIMEZONE = "Europe/London"

EXPECTED_TEAM_COUNT = 20
EXPECTED_MATCH_COUNT = 380
EXPECTED_MATCHDAYS = set(range(1, 39))

BASE_DIR = Path(__file__).resolve().parent

TEAM_METADATA_PATH = BASE_DIR / "data" / "epl_team_metadata.json"

REQUEST_TIMEOUT_SECONDS = 30

MATCH_COLUMNS = [
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
    "winner_team_name",
]

RESULT_STATE_COLUMNS = [
    "score_ft_home",
    "score_ft_away",
    "home_score_for_prediction",
    "away_score_for_prediction",
    "is_finished",
    "winner_team_id",
]


# ============================================================
# OPENFOOTBALL (github.com/openfootball/england) — NGUỒN CHÍNH
# ============================================================
# File text tĩnh, public domain, nằm ngay trên raw.githubusercontent.com.
# Không cần key, không có cơ chế chống bot nào (đây chỉ là 1 file text
# trên CDN của GitHub) — không bao giờ bị chặn khi chạy trên GitHub
# Actions. Bản mở rộng của file này gộp CẢ lịch thi đấu, tỉ số, VÀ ai
# ghi bàn/phút/phạt đền/phản lưới trong đúng 1 file, nên Task 1 và
# Task 2 giờ gộp làm một, chỉ cần đúng 1 HTTP request cho cả mùa.
OPENFOOTBALL_BASE_URL = os.getenv(
    "OPENFOOTBALL_BASE_URL",
    "https://raw.githubusercontent.com/openfootball/england/master",
).strip().rstrip("/")
OPENFOOTBALL_FILE_PATH = os.getenv(
    "OPENFOOTBALL_FILE_PATH",
    f"{SEASON_SLUG}/1-premierleague.txt",
).strip().lstrip("/")
OPENFOOTBALL_URL = f"{OPENFOOTBALL_BASE_URL}/{OPENFOOTBALL_FILE_PATH}"
OPENFOOTBALL_MAX_ATTEMPTS = 4


def create_http_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "EPL-Prediction-Arena-Crawler/2.0",
            "Accept": "text/plain",
        }
    )
    return session


HTTP_SESSION = create_http_session()


def fetch_openfootball_text() -> str:
    last_exc: Exception | None = None

    for attempt in range(1, OPENFOOTBALL_MAX_ATTEMPTS + 1):
        try:
            response = HTTP_SESSION.get(
                OPENFOOTBALL_URL,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.text
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == OPENFOOTBALL_MAX_ATTEMPTS:
                break
            wait_seconds = 2 ** attempt
            print(
                f"[openfootball] Lần thử {attempt}/{OPENFOOTBALL_MAX_ATTEMPTS} "
                f"thất bại ({exc}). Thử lại sau {wait_seconds}s..."
            )
            time.sleep(wait_seconds)

    raise RuntimeError(
        f"Không tải được {OPENFOOTBALL_URL} sau "
        f"{OPENFOOTBALL_MAX_ATTEMPTS} lần thử."
    ) from last_exc


# ------------------------------------------------------------
# Parser cho định dạng Football.TXT (bản mở rộng có scorer)
# ------------------------------------------------------------
MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

ROUND_LINE_RE = re.compile(r"^▪\s*(.+?)\s*$")
DATE_LINE_RE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w{3})\s+(\d{1,2})(?:\s+(\d{4}))?$"
)
MATCH_LINE_RE = re.compile(
    r"^(?:(\d{1,2}:\d{2})\s+)?"
    r"(.+?)\s+"
    r"(\d+)-(\d+)"
    r"(?:\s*\((\d+)-(\d+)\))?"
    r"\s+(.+?)\s*$"
)
GOAL_ITEM_RE = re.compile(
    r"([A-Za-zÀ-ÖØ-öø-ÿ.'\-]+(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ.'\-]+)*)\s+"
    r"((?:\d+(?:\+\d+)?'(?:\((?:p|og)\))?\s*,?\s*)+)"
)
GOAL_MINUTE_RE = re.compile(r"(\d+(?:\+\d+)?)'(\((p|og)\))?")


def parse_round_number(round_text: str) -> int | None:
    match = re.search(r"(\d+)\s*$", round_text)
    return int(match.group(1)) if match else None


def infer_year(
    month: int,
    season_start_year: int,
    last_year: int,
    last_month: int | None,
) -> int:
    if last_month is None:
        return season_start_year

    if month < last_month - 6:
        return last_year + 1

    return last_year


def normalize_player_name(raw_name: str) -> str:
    """Nguồn gốc không nhất quán: có tên viết HOA TOÀN BỘ họ
    ("MOHAMED SALAH"), có tên viết thường bình thường ("Federico
    Chiesa"). Chuẩn hoá về dạng Viết Hoa Chữ Cái Đầu cho đồng nhất.
    str.title() coi dấu cách/gạch ngang/nháy đơn là ranh giới từ nên
    xử lý đúng cả tên ghép ("Hudson-Odoi", "O'Riley", "Van De Ven")."""

    return re.sub(r"\s+", " ", raw_name).strip().title()


def parse_goal_side(text_block: str) -> list[dict[str, Any]]:
    goals: list[dict[str, Any]] = []

    for item_match in GOAL_ITEM_RE.finditer(text_block):
        player_name = normalize_player_name(item_match.group(1).strip())
        minutes_raw = item_match.group(2)

        for minute_match in GOAL_MINUTE_RE.finditer(minutes_raw):
            minute = minute_match.group(1)
            flag = minute_match.group(3)

            goals.append(
                {
                    "player_name": player_name,
                    "minute": f"{minute}'",
                    "is_penalty": flag == "p",
                    "is_own_goal": flag == "og",
                }
            )

    return goals


def parse_goal_block(
    raw: str,
    home_score: int,
    away_score: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw = raw.strip()

    if raw.startswith("("):
        raw = raw[1:]

    if raw.endswith(")"):
        raw = raw[:-1]

    parts = [p.strip() for p in raw.split(";")]

    if len(parts) >= 2:
        return parse_goal_side(parts[0]), parse_goal_side(parts[1])

    only_side_goals = parse_goal_side(parts[0]) if parts[0] else []

    # Chỉ 1 phía ghi bàn trong trận — xác định đó là home hay away dựa
    # vào tỉ số (đội có bàn thắng ắt phải là đội có score > 0).
    if away_score > 0 and home_score == 0:
        return [], only_side_goals

    return only_side_goals, []


def parse_openfootball_matches(
    text_content: str,
    season_start_year: int,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []

    current_round: int | None = None
    current_date: dt.date | None = None
    current_time: str | None = None
    last_year = season_start_year
    last_month: int | None = None

    pending: dict[str, Any] | None = None
    goal_buffer: list[str] = []
    collecting_goals = False

    def flush_pending() -> None:
        nonlocal pending, goal_buffer, collecting_goals

        if pending is None:
            return

        pending["raw_goals"] = " ".join(goal_buffer).strip()
        matches.append(pending)
        pending = None
        goal_buffer = []
        collecting_goals = False

    for raw_line in text_content.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("=") or line.startswith("#"):
            continue

        round_match = ROUND_LINE_RE.match(line)
        if round_match:
            flush_pending()
            current_round = parse_round_number(round_match.group(1))
            continue

        date_match = DATE_LINE_RE.match(line)
        if date_match:
            flush_pending()
            month_abbr, day, year_str = date_match.groups()
            month = MONTHS[month_abbr]
            year = (
                int(year_str)
                if year_str
                else infer_year(month, season_start_year, last_year, last_month)
            )
            current_date = dt.date(year, month, int(day))
            last_year = year
            last_month = month
            current_time = None
            continue

        if collecting_goals:
            goal_buffer.append(line)
            if line.rstrip().endswith(")"):
                flush_pending()
            continue

        if line.startswith("("):
            collecting_goals = True
            goal_buffer.append(line)
            if line.count("(") == line.count(")") and line.rstrip().endswith(")"):
                flush_pending()
            continue

        match_line = MATCH_LINE_RE.match(line)
        if match_line and current_date is not None:
            flush_pending()
            (
                time_str,
                home_name,
                home_score,
                away_score,
                ht_home,
                ht_away,
                away_name,
            ) = match_line.groups()

            if time_str:
                current_time = time_str

            pending = {
                "round": current_round,
                "date": current_date,
                "time": current_time or "15:00",
                "home_name": home_name.strip(),
                "away_name": away_name.strip(),
                "home_score": int(home_score),
                "away_score": int(away_score),
                "ht_home": int(ht_home) if ht_home is not None else None,
                "ht_away": int(ht_away) if ht_away is not None else None,
                "raw_goals": "",
            }
            continue

    flush_pending()

    for match in matches:
        home_goals: list[dict[str, Any]] = []
        away_goals: list[dict[str, Any]] = []

        if match["raw_goals"]:
            home_goals, away_goals = parse_goal_block(
                match["raw_goals"],
                match["home_score"],
                match["away_score"],
            )

        match["home_goals"] = home_goals
        match["away_goals"] = away_goals

    return matches


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None

    result = unicodedata.normalize("NFKC", str(value)).strip()
    return result or None


def canonical_key_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def stable_postgres_integer(namespace: str, value: str) -> int:
    digest = hashlib.sha256(f"{namespace}|{value}".encode("utf-8")).digest()
    number = int.from_bytes(digest[:4], byteorder="big", signed=False) & 0x7FFFFFFF
    return number or 1


def weekday_vietnamese(weekday_en: str) -> str:
    return {
        "Monday": "Thứ 2",
        "Tuesday": "Thứ 3",
        "Wednesday": "Thứ 4",
        "Thursday": "Thứ 5",
        "Friday": "Thứ 6",
        "Saturday": "Thứ 7",
        "Sunday": "Chủ nhật",
    }.get(weekday_en, weekday_en)


def load_team_metadata() -> dict[str, dict[str, Any]]:
    if not TEAM_METADATA_PATH.exists():
        raise FileNotFoundError(
            f"Không tìm thấy metadata đội bóng: {TEAM_METADATA_PATH}"
        )

    with TEAM_METADATA_PATH.open("r", encoding="utf-8") as file:
        metadata = json.load(file)

    if not isinstance(metadata, dict):
        raise TypeError("epl_team_metadata.json phải là JSON object.")

    normalized_metadata = {}

    for team_name, values in metadata.items():
        clean_team_name = normalize_text(team_name)

        if not clean_team_name:
            continue

        if not isinstance(values, dict):
            raise TypeError(f"Metadata của {clean_team_name} không phải object.")

        normalized_metadata[clean_team_name] = {
            "short_name": normalize_text(values.get("short_name")),
            "logo_path": normalize_text(values.get("logo_path")),
            "stadium_name": normalize_text(values.get("stadium_name")),
            "stadium_city": normalize_text(values.get("stadium_city")),
        }

    return normalized_metadata


TEAM_NAME_ALIASES = {
    "arsenal": "arsenal",
    "aston villa": "aston villa",
    "bournemouth": "bournemouth",
    "afc bournemouth": "bournemouth",
    "brentford": "brentford",
    "brighton": "brighton",
    "brighton and hove albion": "brighton",
    "brighton hove albion": "brighton",
    "burnley": "burnley",
    "chelsea": "chelsea",
    "crystal palace": "crystal palace",
    "everton": "everton",
    "fulham": "fulham",
    "leeds": "leeds united",
    "leeds united": "leeds united",
    "liverpool": "liverpool",
    "man city": "manchester city",
    "manchester city": "manchester city",
    "man united": "manchester united",
    "man utd": "manchester united",
    "manchester united": "manchester united",
    "manchester utd": "manchester united",
    "newcastle": "newcastle united",
    "newcastle united": "newcastle united",
    "nottingham forest": "nottingham forest",
    "nottm forest": "nottingham forest",
    "sunderland": "sunderland",
    "tottenham": "tottenham hotspur",
    "tottenham hotspur": "tottenham hotspur",
    "spurs": "tottenham hotspur",
    "west ham": "west ham united",
    "west ham united": "west ham united",
    "wolves": "wolverhampton wanderers",
    "wolverhampton": "wolverhampton wanderers",
    "wolverhampton wanderers": "wolverhampton wanderers",
}


def clean_team_text(value: Any) -> str:
    if value is None:
        return ""

    cleaned = str(value).strip().lower()
    cleaned = unicodedata.normalize("NFKD", cleaned)
    cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
    cleaned = cleaned.replace("&", "and")
    cleaned = re.sub(r"\b(fc|afc|football club)\b", "", cleaned)
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return TEAM_NAME_ALIASES.get(cleaned, cleaned)


def build_team_name_lookup(team_names: list[str] | set[str]) -> dict[str, str]:
    return {clean_team_text(name): name for name in team_names}


def resolve_team_name_from_metadata(
    source_name: str | None,
    metadata_lookup: dict[str, str],
) -> str:
    clean_name = normalize_text(source_name)

    if not clean_name:
        raise ValueError("Fixture thiếu tên đội.")

    key = clean_team_text(clean_name)
    resolved_name = metadata_lookup.get(key)

    if not resolved_name:
        raise KeyError(
            f"Đội chưa map được metadata: {clean_name} "
            f"(key chuẩn hoá: {key!r}). Thêm alias vào "
            f"TEAM_NAME_ALIASES hoặc sửa epl_team_metadata.json."
        )

    return resolved_name


def build_teams(
    raw_matches: list[dict[str, Any]],
    team_metadata: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    metadata_lookup = build_team_name_lookup(set(team_metadata))
    team_names: set[str] = set()

    for match in raw_matches:
        team_names.add(
            resolve_team_name_from_metadata(match["home_name"], metadata_lookup)
        )
        team_names.add(
            resolve_team_name_from_metadata(match["away_name"], metadata_lookup)
        )

    missing_metadata = sorted(
        name for name in team_names if name not in team_metadata
    )

    if missing_metadata:
        raise RuntimeError(
            "Các đội chưa có metadata:\n- " + "\n- ".join(missing_metadata)
        )

    records: list[dict[str, Any]] = []

    for team_name in sorted(team_names, key=str.casefold):
        metadata = team_metadata[team_name]
        records.append(
            {
                "team_id": stable_postgres_integer(
                    "epl-team-v1", canonical_key_text(team_name)
                ),
                "team_name": team_name,
                "short_name": metadata.get("short_name"),
                "logo_path": metadata.get("logo_path"),
                "stadium_name": metadata.get("stadium_name"),
                "stadium_city": metadata.get("stadium_city"),
            }
        )

    ids = [record["team_id"] for record in records]

    if len(ids) != len(set(ids)):
        raise RuntimeError("Phát hiện hash collision ở team_id.")

    name_to_id = {record["team_name"]: record["team_id"] for record in records}

    return records, name_to_id


def normalize_matches(
    raw_matches: list[dict[str, Any]],
    team_name_to_id: dict[str, int],
) -> tuple[list[dict[str, Any]], list[int]]:
    records: list[dict[str, Any]] = []
    matchdays: list[int] = []
    team_name_lookup = build_team_name_lookup(set(team_name_to_id))

    sorted_matches = sorted(
        raw_matches,
        key=lambda m: (
            m["date"].isoformat(),
            m["time"] or "",
            m["home_name"],
        ),
    )

    for source_order, match in enumerate(sorted_matches, start=1):
        home_name = resolve_team_name_from_metadata(
            match["home_name"], team_name_lookup
        )
        away_name = resolve_team_name_from_metadata(
            match["away_name"], team_name_lookup
        )

        if home_name == away_name:
            raise ValueError(
                f"Đội nhà và đội khách trùng nhau tại: {match}"
            )

        matchday = match["round"] or ((source_order - 1) // 10) + 1
        round_name = f"Vòng {matchday}"

        naive_kickoff = dt.datetime.combine(
            match["date"],
            dt.datetime.strptime(match["time"], "%H:%M").time(),
        )
        kickoff_source = naive_kickoff.replace(tzinfo=ZoneInfo(SOURCE_TIMEZONE))
        kickoff_utc = kickoff_source.astimezone(dt.timezone.utc)
        kickoff_vietnam = kickoff_utc.astimezone(ZoneInfo(TARGET_TIMEZONE))

        score_home = match["home_score"]
        score_away = match["away_score"]

        # File chỉ chứa trận đã có kết quả (kể cả 0-0) — nếu tương lai
        # nguồn thêm trận chưa đá (không có tỉ số), coi None là chưa đá.
        is_finished = score_home is not None and score_away is not None

        winner_name = None
        if is_finished:
            if score_home > score_away:
                winner_name = home_name
            elif score_away > score_home:
                winner_name = away_name

        winner_id = (
            team_name_to_id[winner_name] if winner_name is not None else None
        )

        source_match_id = "|".join(
            [
                match["date"].isoformat(),
                clean_team_text(home_name),
                clean_team_text(away_name),
            ]
        )
        match_id = stable_postgres_integer(
            "epl-match-v1",
            "|".join([COMPETITION_KEY, SEASON_SLUG, source_match_id]),
        )

        matchdays.append(matchday)

        records.append(
            {
                "match_id": match_id,
                "source_match_id": source_match_id,
                "round_name": round_name,
                "stage_type": "league",
                "is_knockout": False,
                "date_source": kickoff_source.strftime("%Y-%m-%d"),
                "time_source": kickoff_source.strftime("%H:%M"),
                "kickoff_time_utc": kickoff_utc.isoformat(),
                "kickoff_datetime_vietnam": kickoff_vietnam.isoformat(),
                "kickoff_date_vietnam": kickoff_vietnam.strftime("%Y-%m-%d"),
                "kickoff_date_display_vietnam": kickoff_vietnam.strftime(
                    "%d/%m/%Y"
                ),
                "kickoff_time_vietnam": kickoff_vietnam.strftime("%H:%M"),
                "kickoff_weekday_vietnam": weekday_vietnamese(
                    kickoff_vietnam.strftime("%A")
                ),
                "kickoff_display_vietnam": kickoff_vietnam.strftime(
                    "%H:%M, %d/%m/%Y"
                ),
                "home_team_id": team_name_to_id[home_name],
                "home_team_name": home_name,
                "away_team_id": team_name_to_id[away_name],
                "away_team_name": away_name,
                "venue": None,
                "city": None,
                "score_ft_home": score_home,
                "score_ft_away": score_away,
                "score_et_home": None,
                "score_et_away": None,
                "score_pen_home": None,
                "score_pen_away": None,
                "home_score_for_prediction": score_home if is_finished else None,
                "away_score_for_prediction": score_away if is_finished else None,
                "is_finished": is_finished,
                "winner_team_id": winner_id,
                "winner_team_name": winner_name,
                "_home_goals": match["home_goals"],
                "_away_goals": match["away_goals"],
            }
        )

    records.sort(key=lambda row: (row["kickoff_time_utc"], row["match_id"]))

    return records, matchdays


def validate_dataset(
    teams: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    matchdays: list[int],
) -> None:
    errors: list[str] = []

    if len(teams) != EXPECTED_TEAM_COUNT:
        errors.append(f"Số đội={len(teams)}, kỳ vọng={EXPECTED_TEAM_COUNT}.")

    if len(matches) != EXPECTED_MATCH_COUNT:
        errors.append(f"Số trận={len(matches)}, kỳ vọng={EXPECTED_MATCH_COUNT}.")

    match_ids = [row["match_id"] for row in matches]
    source_ids = [row["source_match_id"] for row in matches]

    if len(match_ids) != len(set(match_ids)):
        errors.append("Có match_id bị trùng.")

    if len(source_ids) != len(set(source_ids)):
        errors.append("Có source_match_id bị trùng.")

    observed_matchdays = set(matchdays)

    if observed_matchdays != EXPECTED_MATCHDAYS:
        errors.append(
            f"Vòng đấu không đủ 1-38. Đang có: {sorted(observed_matchdays)}"
        )

    matchday_counts = Counter(matchdays)
    invalid_round_counts = {
        round_no: count
        for round_no, count in matchday_counts.items()
        if count != 10
    }

    if invalid_round_counts:
        errors.append(f"Một số vòng không đúng 10 trận: {invalid_round_counts}")

    home_counts = Counter(row["home_team_name"] for row in matches)
    away_counts = Counter(row["away_team_name"] for row in matches)
    invalid_team_schedules = {}

    for team in teams:
        name = team["team_name"]
        home_count = home_counts[name]
        away_count = away_counts[name]

        if home_count != 19 or away_count != 19:
            invalid_team_schedules[name] = {"home": home_count, "away": away_count}

    if invalid_team_schedules:
        errors.append(
            "Lịch sân nhà/sân khách không hợp lệ: "
            + json.dumps(invalid_team_schedules, ensure_ascii=False)
        )

    for row in matches:
        if (row["score_ft_home"] is None) != (row["score_ft_away"] is None):
            errors.append(f"Tỉ số thiếu một phía tại match_id={row['match_id']}")

        expected_goals = (row["score_ft_home"] or 0) + (row["score_ft_away"] or 0)
        parsed_goals = len(row["_home_goals"]) + len(row["_away_goals"])

        if row["is_finished"] and expected_goals != parsed_goals:
            errors.append(
                f"Lệch số bàn tại match_id={row['match_id']} "
                f"({row['home_team_name']} {row['score_ft_home']}-"
                f"{row['score_ft_away']} {row['away_team_name']}): "
                f"kỳ vọng {expected_goals}, parse được {parsed_goals}"
            )

    if errors:
        raise RuntimeError("DATA VALIDATION FAILED:\n- " + "\n- ".join(errors))

    finished_count = sum(1 for row in matches if row["is_finished"])

    print("Validation thành công")
    print("Số đội:", len(teams))
    print("Số trận:", len(matches))
    print("Số vòng:", len(observed_matchdays))
    print("Đã có kết quả:", finished_count)
    print("Chưa có kết quả:", len(matches) - finished_count)


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()

    if not database_url:
        raise RuntimeError("Thiếu environment variable DATABASE_URL.")

    parsed = make_url(database_url)

    if parsed.drivername != "postgresql+psycopg2":
        raise RuntimeError("DATABASE_URL phải dùng postgresql+psycopg2.")

    if parsed.port != 5432:
        raise RuntimeError("DATABASE_URL phải dùng Session Pooler port 5432.")

    return database_url


def ensure_database_schema(engine) -> None:
    required_tables = {"teams", "matches", "predictions"}
    inspector = inspect(engine)
    public_tables = set(inspector.get_table_names(schema="public"))
    missing_tables = sorted(required_tables - public_tables)

    if missing_tables:
        raise RuntimeError("Database còn thiếu bảng: " + ", ".join(missing_tables))

    expected_columns = {
        "teams": {
            "team_id",
            "team_name",
            "short_name",
            "logo_path",
            "stadium_name",
            "stadium_city",
        },
        "matches": set(MATCH_COLUMNS),
        "predictions": {
            "prediction_id",
            "match_id",
            "predicted_home_score",
            "predicted_away_score",
            "star_type",
            "base_points",
            "star_bonus_points",
            "points",
        },
    }

    for table_name, required_columns in expected_columns.items():
        actual_columns = {
            column["name"]
            for column in inspector.get_columns(table_name, schema="public")
        }
        missing_columns = sorted(required_columns - actual_columns)

        if missing_columns:
            raise RuntimeError(
                f"Bảng {table_name} thiếu cột: " + ", ".join(missing_columns)
            )


def result_state(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(column) for column in RESULT_STATE_COLUMNS)


def get_existing_result_states(
    connection,
    matches_table: Table,
    match_ids: list[int],
) -> dict[int, tuple[Any, ...]]:
    statement = select(
        matches_table.c.match_id,
        *[matches_table.c[column] for column in RESULT_STATE_COLUMNS],
    ).where(matches_table.c.match_id.in_(match_ids))

    existing = {}

    for row in connection.execute(statement).mappings():
        existing[int(row["match_id"])] = tuple(
            row[column] for column in RESULT_STATE_COLUMNS
        )

    return existing


def get_outcome(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "HOME_WIN"
    if home_score < away_score:
        return "AWAY_WIN"
    return "DRAW"


def calculate_base_points(
    predicted_home: int,
    predicted_away: int,
    actual_home: int,
    actual_away: int,
) -> int:
    if predicted_home == actual_home and predicted_away == actual_away:
        return 3

    if get_outcome(predicted_home, predicted_away) == get_outcome(
        actual_home, actual_away
    ):
        return 1

    return 0


def star_multiplier(star_type: Any) -> int:
    normalized = str(star_type or "none").strip().lower()
    return {"none": 1, "hope": 2, "super": 3}.get(normalized, 1)


def rescore_predictions(connection, changed_match_ids: list[int]) -> int:
    if not changed_match_ids:
        return 0

    statement = text(
        """
        SELECT
            p.prediction_id,
            p.predicted_home_score,
            p.predicted_away_score,
            p.star_type,
            m.home_score_for_prediction,
            m.away_score_for_prediction,
            m.is_finished
        FROM predictions AS p
        JOIN matches AS m ON m.match_id = p.match_id
        WHERE p.match_id IN :match_ids
        """
    ).bindparams(bindparam("match_ids", expanding=True))

    updates = []

    for row in connection.execute(
        statement, {"match_ids": changed_match_ids}
    ).mappings():
        if not bool(row["is_finished"]):
            continue

        actual_home = row["home_score_for_prediction"]
        actual_away = row["away_score_for_prediction"]

        if actual_home is None or actual_away is None:
            continue

        base_points = calculate_base_points(
            int(row["predicted_home_score"]),
            int(row["predicted_away_score"]),
            int(actual_home),
            int(actual_away),
        )
        multiplier = star_multiplier(row["star_type"])
        final_points = base_points * multiplier
        bonus_points = final_points - base_points

        updates.append(
            {
                "prediction_id": int(row["prediction_id"]),
                "base_points": base_points,
                "star_bonus_points": bonus_points,
                "points": final_points,
            }
        )

    if not updates:
        return 0

    connection.execute(
        text(
            """
            UPDATE predictions
            SET base_points = :base_points,
                star_bonus_points = :star_bonus_points,
                points = :points
            WHERE prediction_id = :prediction_id
            """
        ),
        updates,
    )

    return len(updates)


def sync_database(
    teams: list[dict[str, Any]],
    matches: list[dict[str, Any]],
) -> dict[str, int]:
    database_url = get_database_url()
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 20},
    )

    try:
        ensure_database_schema(engine)

        metadata = MetaData()
        teams_table = Table("teams", metadata, autoload_with=engine)
        matches_table = Table("matches", metadata, autoload_with=engine)

        # Bỏ 2 field nội bộ (_home_goals/_away_goals) trước khi insert
        # vào bảng matches — chúng chỉ dùng để ghi bảng match_goals.
        clean_matches = [
            {k: v for k, v in row.items() if not k.startswith("_")}
            for row in matches
        ]

        with engine.begin() as connection:
            existing_states = get_existing_result_states(
                connection,
                matches_table,
                [row["match_id"] for row in clean_matches],
            )

            changed_match_ids = []

            for row in clean_matches:
                old_state = existing_states.get(row["match_id"])
                new_state = result_state(row)

                if old_state != new_state:
                    changed_match_ids.append(row["match_id"])

            team_insert = pg_insert(teams_table).values(teams)
            team_upsert = team_insert.on_conflict_do_update(
                index_elements=[teams_table.c.team_id],
                set_={
                    "team_name": team_insert.excluded.team_name,
                    "short_name": team_insert.excluded.short_name,
                    "logo_path": team_insert.excluded.logo_path,
                    "stadium_name": team_insert.excluded.stadium_name,
                    "stadium_city": team_insert.excluded.stadium_city,
                },
            )
            connection.execute(team_upsert)

            match_insert = pg_insert(matches_table).values(clean_matches)
            match_upsert = match_insert.on_conflict_do_update(
                index_elements=[matches_table.c.match_id],
                set_={
                    column: getattr(match_insert.excluded, column)
                    for column in MATCH_COLUMNS
                    if column != "match_id"
                },
            )
            connection.execute(match_upsert)

            rescored_predictions = rescore_predictions(
                connection, changed_match_ids
            )

            database_counts = (
                connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT COUNT(*) FROM teams) AS teams,
                            (SELECT COUNT(*) FROM matches) AS matches,
                            (SELECT COUNT(*) FROM predictions) AS predictions
                        """
                    )
                )
                .mappings()
                .one()
            )

        return {
            "teams": int(database_counts["teams"]),
            "matches": int(database_counts["matches"]),
            "predictions": int(database_counts["predictions"]),
            "changed_matches": len(changed_match_ids),
            "rescored_predictions": rescored_predictions,
        }

    finally:
        engine.dispose()


def ensure_match_goals_table(engine) -> None:
    ddl = text(
        """
        CREATE TABLE IF NOT EXISTS public.match_goals (
            goal_key TEXT PRIMARY KEY,
            match_id INTEGER NOT NULL REFERENCES public.matches(match_id) ON DELETE CASCADE,
            team_id INTEGER REFERENCES public.teams(team_id),
            team_name TEXT NOT NULL,
            team_side TEXT NOT NULL CHECK (team_side IN ('home', 'away')),
            player_name TEXT NOT NULL,
            minute TEXT,
            is_penalty BOOLEAN NOT NULL DEFAULT FALSE,
            is_own_goal BOOLEAN NOT NULL DEFAULT FALSE
        );

        CREATE INDEX IF NOT EXISTS idx_match_goals_match_id
        ON public.match_goals(match_id);

        CREATE INDEX IF NOT EXISTS idx_match_goals_team_id
        ON public.match_goals(team_id);
        """
    )

    with engine.begin() as connection:
        connection.execute(ddl)

    inspector = inspect(engine)
    actual_columns = {
        column["name"]
        for column in inspector.get_columns("match_goals", schema="public")
    }
    required_columns = {
        "goal_key",
        "match_id",
        "team_id",
        "team_name",
        "team_side",
        "player_name",
        "minute",
        "is_penalty",
        "is_own_goal",
    }
    missing_columns = sorted(required_columns - actual_columns)

    if missing_columns:
        raise RuntimeError(
            "Bảng match_goals thiếu cột: " + ", ".join(missing_columns)
        )

    print("Đã kiểm tra bảng match_goals.")


def build_goal_rows(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    goal_rows: list[dict[str, Any]] = []

    for match in matches:
        if not match["is_finished"]:
            continue

        match_id = match["match_id"]

        for index, goal in enumerate(match["_home_goals"], start=1):
            goal_rows.append(
                {
                    "goal_key": f"openfootball:{match_id}:home:{index}",
                    "match_id": match_id,
                    "team_id": match["home_team_id"],
                    "team_name": match["home_team_name"],
                    "team_side": "home",
                    "player_name": goal["player_name"],
                    "minute": goal["minute"],
                    "is_penalty": goal["is_penalty"],
                    "is_own_goal": goal["is_own_goal"],
                }
            )

        for index, goal in enumerate(match["_away_goals"], start=1):
            goal_rows.append(
                {
                    "goal_key": f"openfootball:{match_id}:away:{index}",
                    "match_id": match_id,
                    "team_id": match["away_team_id"],
                    "team_name": match["away_team_name"],
                    "team_side": "away",
                    "player_name": goal["player_name"],
                    "minute": goal["minute"],
                    "is_penalty": goal["is_penalty"],
                    "is_own_goal": goal["is_own_goal"],
                }
            )

    return goal_rows


def write_match_goals(
    engine,
    goal_rows: list[dict[str, Any]],
    finished_match_ids: list[int],
) -> None:
    if not finished_match_ids:
        print("Không có trận nào cần ghi scorer.")
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM public.match_goals
                WHERE match_id IN :match_ids
                """
            ).bindparams(bindparam("match_ids", expanding=True)),
            {"match_ids": finished_match_ids},
        )

        if goal_rows:
            connection.execute(
                text(
                    """
                    INSERT INTO public.match_goals (
                        goal_key, match_id, team_id, team_name, team_side,
                        player_name, minute, is_penalty, is_own_goal
                    )
                    VALUES (
                        :goal_key, :match_id, :team_id, :team_name, :team_side,
                        :player_name, :minute, :is_penalty, :is_own_goal
                    )
                    """
                ),
                goal_rows,
            )

    print("Số trận đã ghi/refresh scorer:", len(finished_match_ids))
    print("Số dòng scorer đã insert:", len(goal_rows))


def main() -> None:
    print("=" * 72)
    print("EPL OPENFOOTBALL FIXTURE/SCORE/SCORER → SUPABASE")
    print("=" * 72)
    print("Season:", SEASON_SLUG)
    print("Source URL:", OPENFOOTBALL_URL)

    season_start_year = int(SEASON_SLUG.split("-")[0])

    print("Đang tải dữ liệu (1 request)...")
    raw_text = fetch_openfootball_text()
    print("Đã tải xong, kích thước:", len(raw_text), "ký tự")

    raw_matches = parse_openfootball_matches(raw_text, season_start_year)
    print("Số trận parse được từ file:", len(raw_matches))

    if not raw_matches:
        raise RuntimeError(
            "Không parse được trận nào — kiểm tra lại URL/định dạng nguồn."
        )

    team_metadata = load_team_metadata()
    teams, team_name_to_id = build_teams(raw_matches, team_metadata)
    matches, matchdays = normalize_matches(raw_matches, team_name_to_id)

    validate_dataset(teams, matches, matchdays)

    result = sync_database(teams, matches)

    print("\n" + "=" * 72)
    print("SYNC FIXTURE/SCORE THÀNH CÔNG")
    print("=" * 72)
    print("Số đội trong database:", result["teams"])
    print("Số trận trong database:", result["matches"])
    print("Số prediction hiện có:", result["predictions"])
    print("Số trận có dữ liệu thay đổi:", result["changed_matches"])
    print("Số prediction được chấm lại:", result["rescored_predictions"])

    database_url = get_database_url()
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 20},
    )

    try:
        ensure_match_goals_table(engine)

        finished_matches = [row for row in matches if row["is_finished"]]
        finished_match_ids = [row["match_id"] for row in finished_matches]
        goal_rows = build_goal_rows(finished_matches)

        write_match_goals(engine, goal_rows, finished_match_ids)

        with engine.connect() as connection:
            total_goals = connection.execute(
                text("SELECT COUNT(*) FROM public.match_goals")
            ).scalar_one()

        print("\n" + "=" * 72)
        print("SYNC SCORER THÀNH CÔNG")
        print("=" * 72)
        print("Tổng dòng scorer trong DB:", int(total_goals))

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
