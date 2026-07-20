from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections import Counter
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


SOURCE_URL = os.getenv(
    "EPL_SOURCE_URL",
    (
        "https://raw.githubusercontent.com/"
        "openfootball/football.json/"
        "master/2025-26/en.1.json"
    ),
).strip()

COMPETITION_KEY = "epl"
SEASON_SLUG = os.getenv("EPL_SEASON_SLUG", "2025-26").strip()

SOURCE_TIMEZONE = "Europe/London"
TARGET_TIMEZONE = "Asia/Ho_Chi_Minh"

EXPECTED_TEAM_COUNT = 20
EXPECTED_MATCH_COUNT = 380
EXPECTED_MATCHDAYS = set(range(1, 39))

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


def download_source() -> dict[str, Any]:
    print("Đang tải:", SOURCE_URL)

    response = HTTP_SESSION.get(
        SOURCE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Nguồn không trả JSON hợp lệ."
        ) from exc

    if not isinstance(payload, dict):
        raise TypeError(
            "JSON top-level phải là object."
        )

    return payload


def extract_raw_matches(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    matches = payload.get("matches")

    if not isinstance(matches, list):
        raise ValueError(
            "JSON không có key matches dạng list."
        )

    for index, item in enumerate(matches):
        if not isinstance(item, dict):
            raise TypeError(
                f"matches[{index}] không phải object."
            )

    return matches


def build_teams(
    raw_matches: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    team_names: set[str] = set()

    for item in raw_matches:
        home_name = normalize_text(item.get("team1"))
        away_name = normalize_text(item.get("team2"))

        if home_name:
            team_names.add(home_name)

        if away_name:
            team_names.add(away_name)

    records: list[dict[str, Any]] = []

    for team_name in sorted(team_names, key=str.casefold):
        records.append(
            {
                "team_id": stable_postgres_integer(
                    "epl-team-v1",
                    canonical_key_text(team_name),
                ),
                "team_name": team_name,
            }
        )

    ids = [record["team_id"] for record in records]

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

    for source_order, item in enumerate(
        raw_matches,
        start=1,
    ):
        round_name = translate_round_name(
            item.get("round")
        )
        date_source = normalize_text(item.get("date"))
        time_source = normalize_text(item.get("time"))
        home_name = normalize_text(item.get("team1"))
        away_name = normalize_text(item.get("team2"))

        context = (
            f"order={source_order}, round={round_name!r}, "
            f"home={home_name!r}, away={away_name!r}"
        )

        if not round_name:
            raise ValueError(f"Thiếu round: {context}")

        if not home_name or not away_name:
            raise ValueError(f"Thiếu tên đội: {context}")

        if home_name == away_name:
            raise ValueError(
                f"Đội nhà và đội khách trùng nhau: {context}"
            )

        if home_name not in team_name_to_id:
            raise KeyError(
                f"Không tìm thấy team_id cho {home_name}"
            )

        if away_name not in team_name_to_id:
            raise KeyError(
                f"Không tìm thấy team_id cho {away_name}"
            )

        kickoff_utc, kickoff_vietnam = parse_kickoff(
            date_source,
            time_source,
        )

        score_home, score_away = parse_score_pair(
            item.get("score")
        )

        if (score_home is None) != (score_away is None):
            raise ValueError(
                f"Tỉ số chỉ có một phía: {context}"
            )

        is_finished = (
            score_home is not None
            and score_away is not None
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

        source_match_id = "|".join(
            [
                COMPETITION_KEY,
                SEASON_SLUG,
                canonical_key_text(home_name),
                canonical_key_text(away_name),
            ]
        )

        match_id = stable_postgres_integer(
            "epl-match-v1",
            source_match_id,
        )

        matchday = parse_matchday(round_name)

        if matchday is None:
            raise ValueError(
                f"Không đọc được số vòng: {round_name}"
            )

        matchdays.append(matchday)

        records.append(
            {
                "match_id": match_id,
                "source_match_id": source_match_id,
                "round_name": round_name,
                "stage_type": "league",
                "is_knockout": False,
                "date_source": date_source,
                "time_source": time_source,
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
                "venue": None,
                "city": None,
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
        "teams": {"team_id", "team_name"},
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
                        )
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


def main() -> None:
    print("=" * 72)
    print("EPL OPENFOOTBALL → SUPABASE")
    print("=" * 72)
    print("Season:", SEASON_SLUG)

    payload = download_source()
    print("Tên giải:", payload.get("name"))

    raw_matches = extract_raw_matches(payload)

    teams, team_name_to_id = build_teams(
        raw_matches
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
    print("SYNC THÀNH CÔNG")
    print("=" * 72)
    print(
        "Số đội trong database:",
        result["teams"],
    )
    print(
        "Số trận trong database:",
        result["matches"],
    )
    print(
        "Số prediction hiện có:",
        result["predictions"],
    )
    print(
        "Số trận có dữ liệu thay đổi:",
        result["changed_matches"],
    )
    print(
        "Số prediction được chấm lại:",
        result["rescored_predictions"],
    )


if __name__ == "__main__":
    main()
