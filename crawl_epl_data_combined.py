from __future__ import annotations
from pathlib import Path
import hashlib
import json
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
import datetime as dt
from datetime import datetime, timezone
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

SOURCE_TIMEZONE = "Europe/London"
TARGET_TIMEZONE = "Asia/Ho_Chi_Minh"

EXPECTED_TEAM_COUNT = 20
EXPECTED_MATCH_COUNT = 380
EXPECTED_MATCHDAYS = set(range(1, 39))

BASE_DIR = Path(__file__).resolve().parent

TEAM_METADATA_PATH = (
    BASE_DIR
    / "data"
    / "epl_team_metadata.json"
)

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
    session.headers.update(
        {
            "User-Agent": "EPL-Prediction-Arena-Crawler/1.0",
            "Accept": "application/json,text/plain,*/*",
            "Cache-Control": "no-cache",
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


HTTP_SESSION = create_http_session()


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None

    result = unicodedata.normalize("NFKC", str(value)).strip()
    return result or None


def canonical_key_text(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )


def stable_postgres_integer(namespace: str, value: str) -> int:
    digest = hashlib.sha256(
        f"{namespace}|{value}".encode("utf-8")
    ).digest()

    number = int.from_bytes(
        digest[:4],
        byteorder="big",
        signed=False,
    ) & 0x7FFFFFFF

    return number or 1


def translate_round_name(value: Any) -> str | None:
    round_text = normalize_text(value)

    if not round_text:
        return None

    match = re.fullmatch(
        r"matchday\s+(\d+)",
        round_text,
        flags=re.IGNORECASE,
    )

    if match:
        return f"Vòng {int(match.group(1))}"

    return round_text


def parse_matchday(round_name: str | None) -> int | None:
    if not round_name:
        return None

    match = re.search(r"(\d+)\s*$", round_name)

    if not match:
        return None

    return int(match.group(1))


def to_optional_score(value: Any) -> int | None:
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        raise TypeError(f"Tỉ số không hợp lệ: {value!r}")

    try:
        score = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Tỉ số không hợp lệ: {value!r}"
        ) from exc

    if score < 0:
        raise ValueError(f"Tỉ số không được âm: {score}")

    return score


def parse_score_pair(
    score_value: Any,
) -> tuple[int | None, int | None]:
    if score_value is None:
        return None, None

    pair = score_value

    if isinstance(score_value, dict):
        pair = None

        for key in ("ft", "fulltime", "full_time"):
            if key in score_value:
                pair = score_value.get(key)
                break

        if pair is None:
            return None, None

    if isinstance(pair, dict):
        return (
            to_optional_score(
                pair.get("home", pair.get("team1"))
            ),
            to_optional_score(
                pair.get("away", pair.get("team2"))
            ),
        )

    if isinstance(pair, (list, tuple)) and len(pair) >= 2:
        return (
            to_optional_score(pair[0]),
            to_optional_score(pair[1]),
        )

    return None, None


def parse_kickoff(
    date_value: Any,
    time_value: Any,
) -> tuple[datetime, datetime]:
    date_text = normalize_text(date_value)
    time_text = normalize_text(time_value)

    if not date_text or not time_text:
        raise ValueError(
            f"Thiếu date/time: date={date_text!r}, time={time_text!r}"
        )

    try:
        naive_datetime = datetime.strptime(
            f"{date_text} {time_text}",
            "%Y-%m-%d %H:%M",
        )
    except ValueError as exc:
        raise ValueError(
            f"Không parse được kickoff: {date_text} {time_text}"
        ) from exc

    london_datetime = naive_datetime.replace(
        tzinfo=ZoneInfo(SOURCE_TIMEZONE)
    )

    utc_datetime = london_datetime.astimezone(timezone.utc)
    vietnam_datetime = london_datetime.astimezone(
        ZoneInfo(TARGET_TIMEZONE)
    )

    return utc_datetime, vietnam_datetime


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
            f"Không tìm thấy metadata đội bóng: "
            f"{TEAM_METADATA_PATH}"
        )

    with TEAM_METADATA_PATH.open(
        "r",
        encoding="utf-8"
    ) as file:
        metadata = json.load(file)

    if not isinstance(metadata, dict):
        raise TypeError(
            "epl_team_metadata.json phải là JSON object."
        )

    normalized_metadata = {}

    for team_name, values in metadata.items():
        clean_team_name = normalize_text(team_name)

        if not clean_team_name:
            continue

        if not isinstance(values, dict):
            raise TypeError(
                f"Metadata của {clean_team_name} "
                f"không phải object."
            )

        normalized_metadata[clean_team_name] = {
            "short_name": normalize_text(
                values.get("short_name")
            ),
            "logo_path": normalize_text(
                values.get("logo_path")
            ),
            "stadium_name": normalize_text(
                values.get("stadium_name")
            ),
            "stadium_city": normalize_text(
                values.get("stadium_city")
            ),
        }

    return normalized_metadata

def get_espn_team_display_name(
    competitor: dict[str, Any],
) -> str | None:
    team = competitor.get("team") or {}
    return normalize_text(
        team.get("displayName")
        or team.get("name")
        or team.get("shortDisplayName")
        or team.get("abbreviation")
    )


def build_team_name_lookup(
    team_names: list[str] | set[str],
) -> dict[str, str]:
    return {
        clean_espn_text(team_name): team_name
        for team_name in team_names
    }


def resolve_team_name_from_metadata(
    source_name: str | None,
    metadata_lookup: dict[str, str],
) -> str:
    clean_name = normalize_text(source_name)

    if not clean_name:
        raise ValueError("ESPN event thiếu tên đội.")

    key = clean_espn_text(clean_name)
    resolved_name = metadata_lookup.get(key)

    if not resolved_name:
        raise KeyError(
            f"Đội ESPN chưa map được metadata: {clean_name}"
        )

    return resolved_name


def parse_espn_event_datetime(
    event: dict[str, Any],
) -> tuple[datetime, datetime, datetime]:
    event_date = normalize_text(event.get("date"))

    if not event_date:
        raise ValueError(
            f"ESPN event {event.get('id')} thiếu date."
        )

    kickoff_utc = datetime.fromisoformat(
        event_date.replace("Z", "+00:00")
    )

    if kickoff_utc.tzinfo is None:
        kickoff_utc = kickoff_utc.replace(tzinfo=timezone.utc)

    kickoff_utc = kickoff_utc.astimezone(timezone.utc)
    kickoff_source = kickoff_utc.astimezone(
        ZoneInfo(SOURCE_TIMEZONE)
    )
    kickoff_vietnam = kickoff_utc.astimezone(
        ZoneInfo(TARGET_TIMEZONE)
    )

    return kickoff_utc, kickoff_source, kickoff_vietnam


def get_espn_matchday_number(
    event: dict[str, Any],
    fallback_order: int,
) -> int:
    week = event.get("week") or {}

    for key in ("number", "weekNumber"):
        value = week.get(key)

        if value not in (None, ""):
            return int(value)

    season = event.get("season") or {}
    value = season.get("type")

    if isinstance(value, dict):
        week_value = value.get("week")
        if week_value not in (None, ""):
            return int(week_value)

    return ((fallback_order - 1) // 10) + 1


def get_espn_event_status_completed(
    event: dict[str, Any],
) -> bool:
    status_type = ((event.get("status") or {}).get("type") or {})

    if bool(status_type.get("completed")):
        return True

    competitions = event.get("competitions") or []

    if competitions:
        competition_status = (
            (competitions[0].get("status") or {}).get("type") or {}
        )
        return bool(competition_status.get("completed"))

    return False


def parse_espn_competitor_score(
    competitor: dict[str, Any],
) -> int | None:
    value = competitor.get("score")

    if value in (None, ""):
        return None

    return to_optional_score(value)


def extract_espn_venue(
    event: dict[str, Any],
) -> tuple[str | None, str | None]:
    competitions = event.get("competitions") or []

    if not competitions:
        return None, None

    venue = competitions[0].get("venue") or {}
    venue_name = normalize_text(
        venue.get("fullName")
        or venue.get("name")
    )
    address = venue.get("address") or {}
    city = normalize_text(address.get("city"))

    return venue_name, city


def build_teams(
    raw_matches: list[dict[str, Any]],
    team_metadata: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    metadata_lookup = build_team_name_lookup(
        set(team_metadata)
    )
    team_names: set[str] = set()

    for event in raw_matches:
        home, away = get_espn_competitors(event)
        team_names.add(
            resolve_team_name_from_metadata(
                get_espn_team_display_name(home),
                metadata_lookup,
            )
        )
        team_names.add(
            resolve_team_name_from_metadata(
                get_espn_team_display_name(away),
                metadata_lookup,
            )
        )

    missing_metadata = sorted(
        team_name
        for team_name in team_names
        if team_name not in team_metadata
    )

    if missing_metadata:
        raise RuntimeError(
            "Các đội chưa có metadata:\n- "
            + "\n- ".join(missing_metadata)
        )

    records: list[dict[str, Any]] = []

    for team_name in sorted(
        team_names,
        key=str.casefold
    ):
        metadata = team_metadata[team_name]

        records.append(
            {
                "team_id": stable_postgres_integer(
                    "epl-team-v1",
                    canonical_key_text(team_name),
                ),
                "team_name": team_name,
                "short_name": metadata.get(
                    "short_name"
                ),
                "logo_path": metadata.get(
                    "logo_path"
                ),
                "stadium_name": metadata.get(
                    "stadium_name"
                ),
                "stadium_city": metadata.get(
                    "stadium_city"
                ),
            }
        )

    ids = [
        record["team_id"]
        for record in records
    ]

    if len(ids) != len(set(ids)):
        raise RuntimeError(
            "Phát hiện hash collision ở team_id."
        )

    name_to_id = {
        record["team_name"]: record["team_id"]
        for record in records
    }

    return records, name_to_id


def normalize_matches(
    raw_matches: list[dict[str, Any]],
    team_name_to_id: dict[str, int],
) -> tuple[list[dict[str, Any]], list[int]]:
    records: list[dict[str, Any]] = []
    matchdays: list[int] = []
    team_name_lookup = build_team_name_lookup(
        set(team_name_to_id)
    )

    sorted_events = sorted(
        raw_matches,
        key=lambda event: (
            str(event.get("date") or ""),
            str(event.get("id") or ""),
        ),
    )

    for source_order, event in enumerate(
        sorted_events,
        start=1,
    ):
        espn_event_id = normalize_text(event.get("id"))

        if not espn_event_id:
            raise ValueError("ESPN event thiếu id.")

        home, away = get_espn_competitors(event)
        home_name = resolve_team_name_from_metadata(
            get_espn_team_display_name(home),
            team_name_lookup,
        )
        away_name = resolve_team_name_from_metadata(
            get_espn_team_display_name(away),
            team_name_lookup,
        )

        matchday = get_espn_matchday_number(
            event,
            source_order,
        )
        round_name = f"Vòng {matchday}"

        context = (
            f"espn_event_id={espn_event_id}, "
            f"round={round_name!r}, "
            f"home={home_name!r}, away={away_name!r}"
        )

        if home_name == away_name:
            raise ValueError(
                f"Đội nhà và đội khách trùng nhau: {context}"
            )

        kickoff_utc, kickoff_source, kickoff_vietnam = (
            parse_espn_event_datetime(event)
        )

        is_finished = get_espn_event_status_completed(event)
        score_home = (
            parse_espn_competitor_score(home)
            if is_finished
            else None
        )
        score_away = (
            parse_espn_competitor_score(away)
            if is_finished
            else None
        )

        if is_finished and (
            score_home is None or score_away is None
        ):
            raise ValueError(
                f"Trận đã kết thúc nhưng thiếu tỉ số: {context}"
            )

        winner_name = None

        if is_finished:
            if score_home > score_away:
                winner_name = home_name
            elif score_away > score_home:
                winner_name = away_name

        winner_id = (
            team_name_to_id[winner_name]
            if winner_name is not None
            else None
        )

        venue_name, city = extract_espn_venue(event)

        source_match_id = espn_event_id
        match_id = stable_postgres_integer(
            "epl-match-v1",
            "|".join(
                [
                    COMPETITION_KEY,
                    SEASON_SLUG,
                    source_match_id,
                ]
            ),
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
                "kickoff_datetime_vietnam": (
                    kickoff_vietnam.isoformat()
                ),
                "kickoff_date_vietnam": (
                    kickoff_vietnam.strftime("%Y-%m-%d")
                ),
                "kickoff_date_display_vietnam": (
                    kickoff_vietnam.strftime("%d/%m/%Y")
                ),
                "kickoff_time_vietnam": (
                    kickoff_vietnam.strftime("%H:%M")
                ),
                "kickoff_weekday_vietnam": (
                    weekday_vietnamese(
                        kickoff_vietnam.strftime("%A")
                    )
                ),
                "kickoff_display_vietnam": (
                    kickoff_vietnam.strftime(
                        "%H:%M, %d/%m/%Y"
                    )
                ),
                "home_team_id": team_name_to_id[home_name],
                "home_team_name": home_name,
                "away_team_id": team_name_to_id[away_name],
                "away_team_name": away_name,
                "venue": venue_name,
                "city": city,
                "score_ft_home": score_home,
                "score_ft_away": score_away,
                "score_et_home": None,
                "score_et_away": None,
                "score_pen_home": None,
                "score_pen_away": None,
                "home_score_for_prediction": (
                    score_home if is_finished else None
                ),
                "away_score_for_prediction": (
                    score_away if is_finished else None
                ),
                "is_finished": is_finished,
                "winner_team_id": winner_id,
                "winner_team_name": winner_name,
            }
        )

    records.sort(
        key=lambda row: (
            row["kickoff_time_utc"],
            row["match_id"],
        )
    )

    return records, matchdays


TEAM_NAME_ALIASES = {
    "arsenal": "arsenal",
    "aston villa": "aston villa",
    "bournemouth": "bournemouth",
    "afc bournemouth": "bournemouth",
    "brentford": "brentford",
    "brighton": "brighton",
    "brighton and hove albion": "brighton",
    "brighton hove albion": "brighton",
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


def validate_dataset(
    teams: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    matchdays: list[int],
) -> None:
    errors: list[str] = []

    if len(teams) != EXPECTED_TEAM_COUNT:
        errors.append(
            f"Số đội={len(teams)}, kỳ vọng={EXPECTED_TEAM_COUNT}."
        )

    if len(matches) != EXPECTED_MATCH_COUNT:
        errors.append(
            f"Số trận={len(matches)}, kỳ vọng={EXPECTED_MATCH_COUNT}."
        )

    match_ids = [row["match_id"] for row in matches]
    source_ids = [row["source_match_id"] for row in matches]

    if len(match_ids) != len(set(match_ids)):
        errors.append("Có match_id bị trùng.")

    if len(source_ids) != len(set(source_ids)):
        errors.append("Có source_match_id bị trùng.")

    observed_matchdays = set(matchdays)

    if observed_matchdays != EXPECTED_MATCHDAYS:
        errors.append(
            "Vòng đấu không đủ 1 đến 38. "
            f"Đang có: {sorted(observed_matchdays)}"
        )

    matchday_counts = Counter(matchdays)

    invalid_round_counts = {
        round_no: count
        for round_no, count in matchday_counts.items()
        if count != 10
    }

    if invalid_round_counts:
        errors.append(
            "Một số vòng không có đúng 10 trận: "
            f"{invalid_round_counts}"
        )

    home_counts = Counter(
        row["home_team_name"] for row in matches
    )
    away_counts = Counter(
        row["away_team_name"] for row in matches
    )

    invalid_team_schedules = {}

    for team in teams:
        name = team["team_name"]
        home_count = home_counts[name]
        away_count = away_counts[name]

        if home_count != 19 or away_count != 19:
            invalid_team_schedules[name] = {
                "home": home_count,
                "away": away_count,
            }

    if invalid_team_schedules:
        errors.append(
            "Lịch sân nhà/sân khách không hợp lệ: "
            + json.dumps(
                invalid_team_schedules,
                ensure_ascii=False,
            )
        )

    for row in matches:
        if (
            row["score_ft_home"] is None
        ) != (
            row["score_ft_away"] is None
        ):
            errors.append(
                f"Tỉ số thiếu một phía tại match_id={row['match_id']}"
            )

    if errors:
        raise RuntimeError(
            "DATA VALIDATION FAILED:\n- "
            + "\n- ".join(errors)
        )

    finished_count = sum(
        1 for row in matches if row["is_finished"]
    )

    print("Validation thành công")
    print("Số đội:", len(teams))
    print("Số trận:", len(matches))
    print("Số vòng:", len(observed_matchdays))
    print("Đã có kết quả:", finished_count)
    print("Chưa có kết quả:", len(matches) - finished_count)


def get_database_url() -> str:
    database_url = os.getenv(
        "DATABASE_URL",
        "",
    ).strip()

    if not database_url:
        raise RuntimeError(
            "Thiếu environment variable DATABASE_URL."
        )

    parsed = make_url(database_url)

    if parsed.drivername != "postgresql+psycopg2":
        raise RuntimeError(
            "DATABASE_URL phải dùng postgresql+psycopg2."
        )

    if parsed.port != 5432:
        raise RuntimeError(
            "DATABASE_URL phải dùng Session Pooler port 5432."
        )

    return database_url


def ensure_database_schema(engine) -> None:
    required_tables = {
        "teams",
        "matches",
        "predictions",
    }

    inspector = inspect(engine)
    public_tables = set(
        inspector.get_table_names(schema="public")
    )

    missing_tables = sorted(
        required_tables - public_tables
    )

    if missing_tables:
        raise RuntimeError(
            "Database còn thiếu bảng: "
            + ", ".join(missing_tables)
        )

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

    for table_name, required_columns in (
        expected_columns.items()
    ):
        actual_columns = {
            column["name"]
            for column in inspector.get_columns(
                table_name,
                schema="public",
            )
        }

        missing_columns = sorted(
            required_columns - actual_columns
        )

        if missing_columns:
            raise RuntimeError(
                f"Bảng {table_name} thiếu cột: "
                + ", ".join(missing_columns)
            )

def result_state(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        row.get(column)
        for column in RESULT_STATE_COLUMNS
    )


def get_existing_result_states(
    connection,
    matches_table: Table,
    match_ids: list[int],
) -> dict[int, tuple[Any, ...]]:
    statement = select(
        matches_table.c.match_id,
        *[
            matches_table.c[column]
            for column in RESULT_STATE_COLUMNS
        ],
    ).where(
        matches_table.c.match_id.in_(match_ids)
    )

    existing = {}

    for row in connection.execute(
        statement
    ).mappings():
        existing[int(row["match_id"])] = tuple(
            row[column]
            for column in RESULT_STATE_COLUMNS
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
    if (
        predicted_home == actual_home
        and predicted_away == actual_away
    ):
        return 3

    if (
        get_outcome(predicted_home, predicted_away)
        == get_outcome(actual_home, actual_away)
    ):
        return 1

    return 0


def star_multiplier(star_type: Any) -> int:
    normalized = str(star_type or "none").strip().lower()

    return {
        "none": 1,
        "hope": 2,
        "super": 3,
    }.get(normalized, 1)


def rescore_predictions(
    connection,
    changed_match_ids: list[int],
) -> int:
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
        JOIN matches AS m
          ON m.match_id = p.match_id
        WHERE p.match_id IN :match_ids
        """
    ).bindparams(
        bindparam(
            "match_ids",
            expanding=True,
        )
    )

    updates = []

    for row in connection.execute(
        statement,
        {"match_ids": changed_match_ids},
    ).mappings():
        if not bool(row["is_finished"]):
            continue

        actual_home = row[
            "home_score_for_prediction"
        ]
        actual_away = row[
            "away_score_for_prediction"
        ]

        if actual_home is None or actual_away is None:
            continue

        base_points = calculate_base_points(
            int(row["predicted_home_score"]),
            int(row["predicted_away_score"]),
            int(actual_home),
            int(actual_away),
        )

        multiplier = star_multiplier(
            row["star_type"]
        )

        final_points = base_points * multiplier
        bonus_points = final_points - base_points

        updates.append(
            {
                "prediction_id": int(
                    row["prediction_id"]
                ),
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
            SET
                base_points = :base_points,
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
        connect_args={
            "connect_timeout": 20,
        },
    )

    try:
        ensure_database_schema(engine)

        metadata = MetaData()
        teams_table = Table(
            "teams",
            metadata,
            autoload_with=engine,
        )
        matches_table = Table(
            "matches",
            metadata,
            autoload_with=engine,
        )

        with engine.begin() as connection:
            existing_states = get_existing_result_states(
                connection,
                matches_table,
                [row["match_id"] for row in matches],
            )

            changed_match_ids = []

            for row in matches:
                old_state = existing_states.get(
                    row["match_id"]
                )
                new_state = result_state(row)

                if old_state != new_state:
                    changed_match_ids.append(
                        row["match_id"]
                    )

            team_insert = pg_insert(
                teams_table
            ).values(teams)

            team_upsert = (
                team_insert
                .on_conflict_do_update(
                    index_elements=[
                        teams_table.c.team_id
                    ],
                    set_={
                        "team_name": (
                            team_insert.excluded.team_name
                        ),
                        "short_name": (
                            team_insert.excluded.short_name
                        ),
                        "logo_path": (
                            team_insert.excluded.logo_path
                        ),
                        "stadium_name": (
                            team_insert.excluded.stadium_name
                        ),
                        "stadium_city": (
                            team_insert.excluded.stadium_city
                        ),
                    },
                )
            )

            connection.execute(team_upsert)

            match_insert = pg_insert(
                matches_table
            ).values(matches)

            match_upsert = (
                match_insert
                .on_conflict_do_update(
                    index_elements=[
                        matches_table.c.match_id
                    ],
                    set_={
                        column: getattr(
                            match_insert.excluded,
                            column,
                        )
                        for column in MATCH_COLUMNS
                        if column != "match_id"
                    },
                )
            )

            connection.execute(match_upsert)

            rescored_predictions = (
                rescore_predictions(
                    connection,
                    changed_match_ids,
                )
            )

            database_counts = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM teams)
                            AS teams,
                        (SELECT COUNT(*) FROM matches)
                            AS matches,
                        (SELECT COUNT(*) FROM predictions)
                            AS predictions
                    """
                )
            ).mappings().one()

        return {
            "teams": int(database_counts["teams"]),
            "matches": int(database_counts["matches"]),
            "predictions": int(
                database_counts["predictions"]
            ),
            "changed_matches": len(
                changed_match_ids
            ),
            "rescored_predictions": (
                rescored_predictions
            ),
        }

    finally:
        engine.dispose()


ESPN_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "soccer/eng.1/scoreboard"
)
ESPN_SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "soccer/eng.1/summary"
)
ESPN_SEASON_SEED_DATE = os.getenv(
    "ESPN_SEASON_SEED_DATE",
    "20260815",
).strip()
ESPN_SEASON_START_DATE = os.getenv(
    "ESPN_SEASON_START_DATE",
    "20260801",
).strip()
ESPN_SEASON_END_DATE = os.getenv(
    "ESPN_SEASON_END_DATE",
    "20270531",
).strip()
ESPN_RECENT_DAYS = int(
    os.getenv(
        "ESPN_RECENT_DAYS",
        os.getenv("RECENT_DAYS", "3"),
    )
)
ESPN_FORCE_REFRESH = os.getenv(
    "ESPN_FORCE_REFRESH",
    os.getenv("FORCE_REFRESH", "false"),
).strip().casefold() == "true"


@dataclass(frozen=True)
class EspnMatchMeta:
    espn_event_id: str
    match_date_vietnam: str
    raw_name: str | None
    home_team_name: str
    away_team_name: str
    home_espn_team_id: str
    away_espn_team_id: str
    home_score: int
    away_score: int


def fetch_espn_scoreboard(date_yyyymmdd: str) -> dict[str, Any]:
    response = HTTP_SESSION.get(
        ESPN_SCOREBOARD_URL,
        params={"dates": date_yyyymmdd},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "ESPN scoreboard không trả JSON hợp lệ."
        ) from exc

    if not isinstance(payload, dict):
        raise TypeError("ESPN scoreboard top-level phải là object.")

    return payload


def normalize_espn_date_param(value: str) -> str:
    clean_value = value.strip()

    if re.fullmatch(r"\d{8}", clean_value):
        return clean_value

    return dt.date.fromisoformat(clean_value).strftime("%Y%m%d")


def resolve_espn_season_dates() -> list[str]:
    explicit_dates = os.getenv(
        "ESPN_TASK1_DATES",
        "",
    ).strip()

    if explicit_dates:
        return sorted(
            {
                normalize_espn_date_param(part)
                for part in explicit_dates.split(",")
                if part.strip()
            }
        )

    scoreboard = fetch_espn_scoreboard(ESPN_SEASON_SEED_DATE)
    leagues = scoreboard.get("leagues") or []

    if not leagues:
        raise RuntimeError("ESPN response không có league calendar.")

    calendar = leagues[0].get("calendar") or []
    dates = sorted(
        {
            str(item)[:10].replace("-", "")
            for item in calendar
            if item
        }
    )

    if not dates:
        raise RuntimeError("ESPN calendar rỗng.")

    start_date = yyyymmdd_to_date(
        normalize_espn_date_param(ESPN_SEASON_START_DATE)
    )
    end_date = yyyymmdd_to_date(
        normalize_espn_date_param(ESPN_SEASON_END_DATE)
    )

    season_dates = [
        value
        for value in dates
        if start_date <= yyyymmdd_to_date(value) <= end_date
    ]

    if not season_dates:
        raise RuntimeError(
            "Không tìm thấy ngày thi đấu EPL trong khoảng mùa "
            f"{ESPN_SEASON_START_DATE} đến {ESPN_SEASON_END_DATE}."
        )

    return season_dates


def download_espn_season_events() -> list[dict[str, Any]]:
    dates = resolve_espn_season_dates()
    events_by_id: dict[str, dict[str, Any]] = {}

    print("Số ngày ESPN của cả mùa cần tải:", len(dates))

    for index, date_yyyymmdd in enumerate(dates, start=1):
        print(
            "Đang tải ESPN fixture/score",
            f"{index}/{len(dates)}:",
            date_yyyymmdd,
        )
        scoreboard = fetch_espn_scoreboard(date_yyyymmdd)

        for event in scoreboard.get("events") or []:
            event_id = normalize_text(event.get("id"))

            if not event_id:
                continue

            events_by_id[event_id] = event

    events = sorted(
        events_by_id.values(),
        key=lambda event: (
            str(event.get("date") or ""),
            str(event.get("id") or ""),
        ),
    )

    if not events:
        raise RuntimeError("Không tải được trận nào từ ESPN.")

    print("Số trận ESPN tải được:", len(events))
    return events


def fetch_espn_summary(event_id: str) -> dict[str, Any]:
    response = HTTP_SESSION.get(
        ESPN_SUMMARY_URL,
        params={"event": event_id},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "ESPN summary không trả JSON hợp lệ."
        ) from exc

    if not isinstance(payload, dict):
        raise TypeError("ESPN summary top-level phải là object.")

    return payload


def date_to_yyyymmdd(value: dt.date) -> str:
    return value.strftime("%Y%m%d")


def yyyymmdd_to_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y%m%d").date()


def resolve_espn_dates() -> list[str]:
    explicit_dates = os.getenv("SYNC_DATES", "").strip()

    if explicit_dates:
        return sorted(
            {
                dt.date.fromisoformat(part.strip()).strftime("%Y%m%d")
                for part in explicit_dates.split(",")
                if part.strip()
            }
        )

    scoreboard = fetch_espn_scoreboard(ESPN_SEASON_SEED_DATE)
    leagues = scoreboard.get("leagues") or []

    if not leagues:
        raise RuntimeError("ESPN response không có league calendar.")

    calendar = leagues[0].get("calendar") or []
    dates = sorted(
        {
            str(item)[:10].replace("-", "")
            for item in calendar
            if item
        }
    )

    if not dates:
        raise RuntimeError("ESPN calendar rỗng.")

    today = dt.datetime.now(
        ZoneInfo(TARGET_TIMEZONE)
    ).date()
    cutoff = today - dt.timedelta(days=ESPN_RECENT_DAYS)

    return [
        value
        for value in dates
        if cutoff <= yyyymmdd_to_date(value) <= today
    ]


def clean_espn_text(value: Any) -> str:
    if value is None:
        return ""

    cleaned = str(value).strip().lower()
    cleaned = unicodedata.normalize("NFKD", cleaned)
    cleaned = "".join(
        ch
        for ch in cleaned
        if not unicodedata.combining(ch)
    )
    cleaned = cleaned.replace("&", "and")
    cleaned = re.sub(
        r"\b(fc|afc|football club)\b",
        "",
        cleaned,
    )
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return TEAM_NAME_ALIASES.get(cleaned, cleaned)


def parse_db_date(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, dt.datetime):
        return value.date().isoformat()

    if isinstance(value, dt.date):
        return value.isoformat()

    value = str(value).strip()

    if not value:
        return None

    try:
        return dt.date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return value[:10]


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
        for column in inspector.get_columns(
            "match_goals",
            schema="public",
        )
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
            "Bảng match_goals thiếu cột: "
            + ", ".join(missing_columns)
        )

    print("Đã kiểm tra bảng match_goals.")


def load_db_matches_for_goals(engine) -> list[dict[str, Any]]:
    query = text(
        """
        SELECT
            match_id,
            source_match_id,
            kickoff_date_vietnam,
            home_team_id,
            home_team_name,
            away_team_id,
            away_team_name,
            home_score_for_prediction,
            away_score_for_prediction,
            is_finished
        FROM public.matches
        """
    )

    with engine.connect() as connection:
        rows = [
            dict(row)
            for row in connection.execute(query).mappings()
        ]

    for row in rows:
        row["_source_match_id_key"] = str(
            row.get("source_match_id") or ""
        ).strip()
        row["_kickoff_date_key"] = parse_db_date(
            row.get("kickoff_date_vietnam")
        )
        row["_home_key"] = clean_espn_text(
            row.get("home_team_name")
        )
        row["_away_key"] = clean_espn_text(
            row.get("away_team_name")
        )

    print("Số trận load từ DB để sync scorer:", len(rows))
    return rows


def load_existing_goal_state(engine) -> dict[int, dict[str, int]]:
    query = text(
        """
        SELECT
            match_id,
            COUNT(*) AS goal_count,
            COUNT(*) FILTER (
                WHERE minute IS NOT NULL
                AND minute <> ''
                AND RIGHT(minute, 1) <> CHR(39)
            ) AS bad_minute_count
        FROM public.match_goals
        GROUP BY match_id
        """
    )

    with engine.connect() as connection:
        rows = connection.execute(query).mappings()

        return {
            int(row["match_id"]): {
                "goal_count": int(row["goal_count"]),
                "bad_minute_count": int(row["bad_minute_count"]),
            }
            for row in rows
        }


def get_espn_competitors(
    event: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    competitions = event.get("competitions") or []

    if not competitions:
        raise RuntimeError(
            f"ESPN event {event.get('id')} không có competitions."
        )

    competitors = competitions[0].get("competitors") or []
    home = next(
        (
            item
            for item in competitors
            if item.get("homeAway") == "home"
        ),
        None,
    )
    away = next(
        (
            item
            for item in competitors
            if item.get("homeAway") == "away"
        ),
        None,
    )

    if not home or not away:
        raise RuntimeError(
            f"ESPN event {event.get('id')} thiếu home/away."
        )

    return home, away


def get_espn_match_meta(event: dict[str, Any]) -> EspnMatchMeta:
    home, away = get_espn_competitors(event)

    event_datetime_utc = dt.datetime.fromisoformat(
        str(event["date"]).replace("Z", "+00:00")
    )
    event_date_vietnam = event_datetime_utc.astimezone(
        ZoneInfo(TARGET_TIMEZONE)
    ).date().isoformat()

    home_team = home.get("team") or {}
    away_team = away.get("team") or {}

    return EspnMatchMeta(
        espn_event_id=str(event.get("id")),
        match_date_vietnam=event_date_vietnam,
        raw_name=event.get("name"),
        home_team_name=str(
            home_team.get("displayName")
            or home_team.get("name")
            or ""
        ),
        away_team_name=str(
            away_team.get("displayName")
            or away_team.get("name")
            or ""
        ),
        home_espn_team_id=str(home_team.get("id")),
        away_espn_team_id=str(away_team.get("id")),
        home_score=int(home.get("score") or 0),
        away_score=int(away.get("score") or 0),
    )


def find_db_match_for_espn(
    meta: EspnMatchMeta,
    db_matches: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    by_source_id = [
        row
        for row in db_matches
        if row["_source_match_id_key"] == meta.espn_event_id
    ]

    if len(by_source_id) == 1:
        return by_source_id[0], "source_match_id"

    home_key = clean_espn_text(meta.home_team_name)
    away_key = clean_espn_text(meta.away_team_name)

    candidates = [
        row
        for row in db_matches
        if row["_kickoff_date_key"] == meta.match_date_vietnam
        and row["_home_key"] == home_key
        and row["_away_key"] == away_key
    ]

    if len(candidates) == 1:
        return candidates[0], "date_and_teams"

    if len(candidates) > 1:
        return None, f"ambiguous:{len(candidates)}"

    return None, "unmatched"


def is_completed_espn_event(event: dict[str, Any]) -> bool:
    status_type = ((event.get("status") or {}).get("type") or {})
    return bool(status_type.get("completed"))


def is_espn_goal_event(item: dict[str, Any]) -> bool:
    type_obj = item.get("type") or {}
    type_text = str(type_obj.get("text", "")).lower()
    type_type = str(type_obj.get("type", "")).lower()
    short_text = str(item.get("shortText", "")).lower()

    if "missed" in type_text or "missed" in short_text:
        return False

    return bool(
        item.get("scoringPlay") is True
        and (
            "goal" in type_text
            or "goal" in type_type
            or "penalty - scored" in type_text
        )
    )


def parse_espn_goal_minute(value: Any) -> str | None:
    if value is None:
        return None

    minute = str(value).strip()

    if not minute:
        return None

    minute = minute.replace("'", "").replace("’", "").replace("′", "")
    minute = re.sub(r"\s+", "", minute)

    return f"{minute}'"


def detect_espn_goal_flags(item: dict[str, Any]) -> tuple[bool, bool]:
    type_text = str((item.get("type") or {}).get("text", "")).lower()
    event_text = str(item.get("text", "")).lower()
    short_text = str(item.get("shortText", "")).lower()
    full_text = f"{type_text} {event_text} {short_text}"

    is_own_goal = bool(item.get("ownGoal")) or "own goal" in full_text
    is_penalty = bool(item.get("penaltyKick")) or "penalty - scored" in full_text

    return is_penalty, is_own_goal


def get_espn_player_name(item: dict[str, Any]) -> str:
    participants = item.get("participants") or []

    for participant in participants:
        athlete = participant.get("athlete") or {}
        name = athlete.get("displayName") or athlete.get("shortName")

        if name:
            return str(name).strip()

    text_value = str(item.get("text") or item.get("shortText") or "").strip()
    fallback = text_value.split("(")[0].strip()

    return fallback or "Unknown"


def parse_espn_goals_for_match(
    event: dict[str, Any],
    db_match: dict[str, Any],
    meta: EspnMatchMeta,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    summary = fetch_espn_summary(meta.espn_event_id)
    rows: list[dict[str, Any]] = []
    side_counts = {"home": 0, "away": 0}

    for item in summary.get("keyEvents") or []:
        if not is_espn_goal_event(item):
            continue

        team = item.get("team") or {}
        espn_team_id = (
            str(team.get("id"))
            if team.get("id") is not None
            else None
        )

        if espn_team_id == meta.home_espn_team_id:
            team_side = "home"
            team_id = db_match.get("home_team_id")
            team_name = db_match.get("home_team_name")
        elif espn_team_id == meta.away_espn_team_id:
            team_side = "away"
            team_id = db_match.get("away_team_id")
            team_name = db_match.get("away_team_name")
        else:
            continue

        side_counts[team_side] += 1

        source_event_id = item.get("id")
        fallback_goal_index = len(rows) + 1
        goal_key = (
            f"espn:{meta.espn_event_id}:"
            f"{source_event_id or fallback_goal_index}"
        )
        is_penalty, is_own_goal = detect_espn_goal_flags(item)

        rows.append(
            {
                "goal_key": goal_key,
                "match_id": int(db_match["match_id"]),
                "team_id": int(team_id) if team_id is not None else None,
                "team_name": str(team_name),
                "team_side": team_side,
                "player_name": get_espn_player_name(item),
                "minute": parse_espn_goal_minute(
                    (item.get("clock") or {}).get("displayValue")
                ),
                "is_penalty": is_penalty,
                "is_own_goal": is_own_goal,
            }
        )

    expected_total = meta.home_score + meta.away_score

    if len(rows) == expected_total:
        return rows, None

    return rows, {
        "espn_event_id": meta.espn_event_id,
        "match_id": db_match.get("match_id"),
        "match": meta.raw_name,
        "score": f"{meta.home_score}-{meta.away_score}",
        "expected_goals": expected_total,
        "parsed_goals": len(rows),
        "home_parsed": side_counts["home"],
        "away_parsed": side_counts["away"],
    }


def crawl_espn_match_goals(
    engine,
    dates: list[str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    db_matches = load_db_matches_for_goals(engine)
    existing_goal_state = load_existing_goal_state(engine)

    goal_rows: list[dict[str, Any]] = []
    matched_matches: list[dict[str, Any]] = []
    skipped_matches: list[dict[str, Any]] = []
    unmatched_matches: list[dict[str, Any]] = []
    problem_matches: list[dict[str, Any]] = []

    for index, date_yyyymmdd in enumerate(dates, start=1):
        print(
            "Đang tải ESPN scoreboard",
            f"{index}/{len(dates)}:",
            date_yyyymmdd,
        )
        scoreboard = fetch_espn_scoreboard(date_yyyymmdd)

        for event in scoreboard.get("events") or []:
            if not is_completed_espn_event(event):
                continue

            meta = get_espn_match_meta(event)
            db_match, match_method = find_db_match_for_espn(
                meta,
                db_matches,
            )

            if db_match is None:
                unmatched_matches.append(
                    {
                        "espn_event_id": meta.espn_event_id,
                        "match_date_vietnam": meta.match_date_vietnam,
                        "home_team": meta.home_team_name,
                        "away_team": meta.away_team_name,
                        "score": f"{meta.home_score}-{meta.away_score}",
                        "reason": match_method,
                    }
                )
                continue

            match_id = int(db_match["match_id"])
            expected_total = meta.home_score + meta.away_score
            existing_state = existing_goal_state.get(
                match_id,
                {"goal_count": 0, "bad_minute_count": 0},
            )
            existing_total = existing_state["goal_count"]
            bad_minute_count = existing_state["bad_minute_count"]

            match_record = {
                "match_id": match_id,
                "espn_event_id": meta.espn_event_id,
                "home_score": meta.home_score,
                "away_score": meta.away_score,
                "home_team_name": db_match.get("home_team_name"),
                "away_team_name": db_match.get("away_team_name"),
                "match_method": match_method,
            }

            if expected_total == 0:
                if (
                    not ESPN_FORCE_REFRESH
                    and existing_total == 0
                ):
                    skipped_matches.append(
                        {
                            **match_record,
                            "skip_reason": "zero_goal_match",
                        }
                    )
                    continue

                matched_matches.append(match_record)
                continue

            if (
                not ESPN_FORCE_REFRESH
                and existing_total == expected_total
                and bad_minute_count == 0
            ):
                skipped_matches.append(
                    {
                        **match_record,
                        "skip_reason": "existing_goal_count_matches_score",
                    }
                )
                continue

            rows, problem = parse_espn_goals_for_match(
                event,
                db_match,
                meta,
            )

            if problem:
                problem_matches.append(problem)
                continue

            matched_matches.append(match_record)
            goal_rows.extend(rows)

    return (
        goal_rows,
        matched_matches,
        skipped_matches,
        unmatched_matches,
        problem_matches,
    )


def write_espn_match_goals(
    engine,
    goal_rows: list[dict[str, Any]],
    matched_matches: list[dict[str, Any]],
) -> None:
    match_ids = sorted(
        {
            int(match["match_id"])
            for match in matched_matches
        }
    )

    if not match_ids:
        print("Không có trận nào cần ghi scorer.")
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM public.match_goals
                WHERE match_id IN :match_ids
                """
            ).bindparams(
                bindparam("match_ids", expanding=True)
            ),
            {"match_ids": match_ids},
        )

        if goal_rows:
            connection.execute(
                text(
                    """
                    INSERT INTO public.match_goals (
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
                ),
                goal_rows,
            )

    print("Số trận đã thay scorer:", len(match_ids))
    print("Số dòng scorer đã insert:", len(goal_rows))


def sync_espn_match_goals() -> dict[str, int]:
    database_url = get_database_url()
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 20,
        },
    )

    try:
        ensure_match_goals_table(engine)
        dates = resolve_espn_dates()
        print("Số ngày ESPN cần kiểm tra:", len(dates))

        (
            goal_rows,
            matched_matches,
            skipped_matches,
            unmatched_matches,
            problem_matches,
        ) = crawl_espn_match_goals(engine, dates)

        print("Số trận scorer sẽ ghi DB:", len(matched_matches))
        print("Số trận scorer đã skip:", len(skipped_matches))
        print("Số dòng scorer parse được:", len(goal_rows))
        print("Số trận ESPN không map được:", len(unmatched_matches))
        print("Số trận ESPN bị lệch số bàn:", len(problem_matches))

        if unmatched_matches:
            print("Một số trận không map được:")
            for row in unmatched_matches[:10]:
                print(row)

        if problem_matches:
            print("Một số trận lệch số bàn, sẽ không ghi partial scorer:")
            for row in problem_matches[:10]:
                print(row)

        write_espn_match_goals(
            engine,
            goal_rows,
            matched_matches,
        )

        with engine.connect() as connection:
            total_goals = connection.execute(
                text("SELECT COUNT(*) FROM public.match_goals")
            ).scalar_one()

        return {
            "matched_matches": len(matched_matches),
            "skipped_matches": len(skipped_matches),
            "goal_rows": len(goal_rows),
            "unmatched_matches": len(unmatched_matches),
            "problem_matches": len(problem_matches),
            "match_goals_total": int(total_goals),
        }

    finally:
        engine.dispose()


def main() -> None:
    print("=" * 72)
    print("TASK 1 - EPL ESPN FIXTURE/SCORE → SUPABASE")
    print("=" * 72)
    print("Season:", SEASON_SLUG)
    print("ESPN season seed date:", ESPN_SEASON_SEED_DATE)
    print("ESPN season start date:", ESPN_SEASON_START_DATE)
    print("ESPN season end date:", ESPN_SEASON_END_DATE)

    raw_matches = download_espn_season_events()

    team_metadata = load_team_metadata()

    teams, team_name_to_id = build_teams(
        raw_matches,
        team_metadata,
    )

    matches, matchdays = normalize_matches(
        raw_matches,
        team_name_to_id,
    )

    validate_dataset(
        teams,
        matches,
        matchdays,
    )

    result = sync_database(
        teams,
        matches,
    )

    print("\n" + "=" * 72)
    print("TASK 1 SYNC THÀNH CÔNG")
    print("=" * 72)
    print("Số đội trong database:", result["teams"])
    print("Số trận trong database:", result["matches"])
    print("Số prediction hiện có:", result["predictions"])
    print("Số trận có dữ liệu thay đổi:", result["changed_matches"])
    print("Số prediction được chấm lại:", result["rescored_predictions"])

    print("\n" + "=" * 72)
    print("TASK 2 - ESPN MATCH GOALS → SUPABASE")
    print("=" * 72)
    print("ESPN recent days:", ESPN_RECENT_DAYS)
    print("ESPN force refresh:", ESPN_FORCE_REFRESH)

    goal_result = sync_espn_match_goals()

    print("\n" + "=" * 72)
    print("TASK 2 SYNC THÀNH CÔNG")
    print("=" * 72)
    print("Số trận scorer ghi mới:", goal_result["matched_matches"])
    print("Số trận scorer skip:", goal_result["skipped_matches"])
    print("Số dòng scorer parse được:", goal_result["goal_rows"])
    print("Tổng dòng scorer trong DB:", goal_result["match_goals_total"])
    print("Số trận ESPN không map được:", goal_result["unmatched_matches"])
    print("Số trận ESPN lệch số bàn:", goal_result["problem_matches"])


if __name__ == "__main__":
    main()
