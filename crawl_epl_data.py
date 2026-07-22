from __future__ import annotations
from pathlib import Path
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

THESPORTSDB_API_KEY = os.getenv(
    "THESPORTSDB_API_KEY",
    "123",
).strip()
THESPORTSDB_LEAGUE_ID = os.getenv(
    "THESPORTSDB_LEAGUE_ID",
    "4328",
).strip()
THESPORTSDB_BASE_URL = (
    f"https://www.thesportsdb.com/api/v1/json/"
    f"{THESPORTSDB_API_KEY}"
)

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

MATCH_GOAL_COLUMNS = [
    "goal_key",
    "match_id",
    "team_id",
    "team_name",
    "team_side",
    "player_name",
    "minute",
    "is_penalty",
    "is_own_goal",
    "source_provider",
    "source_event_id",
    "raw_goal_text",
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
        return f"VÃ²ng {int(match.group(1))}"

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
        raise TypeError(f"Tá»‰ sá»‘ khÃ´ng há»£p lá»‡: {value!r}")

    try:
        score = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Tá»‰ sá»‘ khÃ´ng há»£p lá»‡: {value!r}"
        ) from exc

    if score < 0:
        raise ValueError(f"Tá»‰ sá»‘ khÃ´ng Ä‘Æ°á»£c Ã¢m: {score}")

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
            f"Thiáº¿u date/time: date={date_text!r}, time={time_text!r}"
        )

    try:
        naive_datetime = datetime.strptime(
            f"{date_text} {time_text}",
            "%Y-%m-%d %H:%M",
        )
    except ValueError as exc:
        raise ValueError(
            f"KhÃ´ng parse Ä‘Æ°á»£c kickoff: {date_text} {time_text}"
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
        "Monday": "Thá»© 2",
        "Tuesday": "Thá»© 3",
        "Wednesday": "Thá»© 4",
        "Thursday": "Thá»© 5",
        "Friday": "Thá»© 6",
        "Saturday": "Thá»© 7",
        "Sunday": "Chá»§ nháº­t",
    }.get(weekday_en, weekday_en)


def download_source() -> dict[str, Any]:
    print("Äang táº£i:", SOURCE_URL)

    response = HTTP_SESSION.get(
        SOURCE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Nguá»“n khÃ´ng tráº£ JSON há»£p lá»‡."
        ) from exc

    if not isinstance(payload, dict):
        raise TypeError(
            "JSON top-level pháº£i lÃ  object."
        )

    return payload


def extract_raw_matches(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    matches = payload.get("matches")

    if not isinstance(matches, list):
        raise ValueError(
            "JSON khÃ´ng cÃ³ key matches dáº¡ng list."
        )

    for index, item in enumerate(matches):
        if not isinstance(item, dict):
            raise TypeError(
                f"matches[{index}] khÃ´ng pháº£i object."
            )

    return matches

def load_team_metadata() -> dict[str, dict[str, Any]]:
    if not TEAM_METADATA_PATH.exists():
        raise FileNotFoundError(
            f"KhÃ´ng tÃ¬m tháº¥y metadata Ä‘á»™i bÃ³ng: "
            f"{TEAM_METADATA_PATH}"
        )

    with TEAM_METADATA_PATH.open(
        "r",
        encoding="utf-8"
    ) as file:
        metadata = json.load(file)

    if not isinstance(metadata, dict):
        raise TypeError(
            "epl_team_metadata.json pháº£i lÃ  JSON object."
        )

    normalized_metadata = {}

    for team_name, values in metadata.items():
        clean_team_name = normalize_text(team_name)

        if not clean_team_name:
            continue

        if not isinstance(values, dict):
            raise TypeError(
                f"Metadata cá»§a {clean_team_name} "
                f"khÃ´ng pháº£i object."
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

def build_teams(
    raw_matches: list[dict[str, Any]],
    team_metadata: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    team_names: set[str] = set()

    for item in raw_matches:
        home_name = normalize_text(item.get("team1"))
        away_name = normalize_text(item.get("team2"))

        if home_name:
            team_names.add(home_name)

        if away_name:
            team_names.add(away_name)

    missing_metadata = sorted(
        team_name
        for team_name in team_names
        if team_name not in team_metadata
    )

    if missing_metadata:
        raise RuntimeError(
            "CÃ¡c Ä‘á»™i chÆ°a cÃ³ metadata:\n- "
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
            "PhÃ¡t hiá»‡n hash collision á»Ÿ team_id."
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
            raise ValueError(f"Thiáº¿u round: {context}")

        if not home_name or not away_name:
            raise ValueError(f"Thiáº¿u tÃªn Ä‘á»™i: {context}")

        if home_name == away_name:
            raise ValueError(
                f"Äá»™i nhÃ  vÃ  Ä‘á»™i khÃ¡ch trÃ¹ng nhau: {context}"
            )

        if home_name not in team_name_to_id:
            raise KeyError(
                f"KhÃ´ng tÃ¬m tháº¥y team_id cho {home_name}"
            )

        if away_name not in team_name_to_id:
            raise KeyError(
                f"KhÃ´ng tÃ¬m tháº¥y team_id cho {away_name}"
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
                f"Tá»‰ sá»‘ chá»‰ cÃ³ má»™t phÃ­a: {context}"
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
                f"KhÃ´ng Ä‘á»c Ä‘Æ°á»£c sá»‘ vÃ²ng: {round_name}"
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


def to_thesportsdb_season(season_slug: str) -> str:
    parts = season_slug.split("-")

    if len(parts) != 2:
        return season_slug

    start, end = parts

    if len(end) == 2 and len(start) == 4:
        end = start[:2] + end

    return f"{start}-{end}"


def normalize_team_match_key(value: Any) -> str:
    text_value = normalize_text(value)

    if not text_value:
        return ""

    normalized = (
        unicodedata.normalize("NFKD", text_value)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    normalized = normalized.casefold()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"\bfc\b|\bafc\b", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = " ".join(normalized.split())

    return TEAM_NAME_ALIASES.get(normalized, normalized)


def download_thesportsdb_season_events() -> list[dict[str, Any]]:
    if not THESPORTSDB_API_KEY:
        print("Bá» qua TheSportsDB vÃ¬ chÆ°a cÃ³ API key.")
        return []

    season = to_thesportsdb_season(SEASON_SLUG)
    print("Äang táº£i TheSportsDB EPL season:", season)

    response = HTTP_SESSION.get(
        f"{THESPORTSDB_BASE_URL}/eventsseason.php",
        params={
            "id": THESPORTSDB_LEAGUE_ID,
            "s": season,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "TheSportsDB khÃ´ng tráº£ JSON há»£p lá»‡."
        ) from exc

    events = payload.get("events") or []

    if not isinstance(events, list):
        return []

    return [
        event
        for event in events
        if isinstance(event, dict)
    ]


def download_thesportsdb_event_detail(
    event_id: str,
    cache: dict[str, dict[str, Any] | None],
) -> dict[str, Any] | None:
    if not event_id:
        return None

    if event_id in cache:
        return cache[event_id]

    response = HTTP_SESSION.get(
        f"{THESPORTSDB_BASE_URL}/lookupevent.php",
        params={
            "id": event_id,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError:
        cache[event_id] = None
        return None

    events = payload.get("events") or []

    if not isinstance(events, list) or not events:
        cache[event_id] = None
        return None

    detail = events[0]
    cache[event_id] = detail if isinstance(detail, dict) else None
    return cache[event_id]


def build_thesportsdb_event_index(
    events: list[dict[str, Any]],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}

    for event in events:
        date_value = normalize_text(
            event.get("dateEventLocal")
            or event.get("dateEvent")
        )
        home_key = normalize_team_match_key(
            event.get("strHomeTeam")
        )
        away_key = normalize_team_match_key(
            event.get("strAwayTeam")
        )

        if not date_value or not home_key or not away_key:
            continue

        index[(date_value, home_key, away_key)] = event

    return index


def split_goal_detail_chunks(detail_text: Any) -> list[str]:
    text_value = normalize_text(detail_text)

    if not text_value:
        return []

    normalized = text_value.replace("\r", "\n")
    chunks = [
        chunk.strip()
        for chunk in re.split(r";|\n", normalized)
        if chunk.strip()
    ]

    if len(chunks) <= 1 and "," in normalized:
        chunks = [
            chunk.strip()
            for chunk in re.split(r",\s+", normalized)
            if chunk.strip()
        ]

    return chunks


def parse_goal_detail_text(
    detail_text: Any,
    match: dict[str, Any],
    team_side: str,
    source_event_id: str,
) -> list[dict[str, Any]]:
    chunks = split_goal_detail_chunks(detail_text)

    if not chunks:
        return []

    if team_side == "home":
        team_id = match["home_team_id"]
        team_name = match["home_team_name"]
    elif team_side == "away":
        team_id = match["away_team_id"]
        team_name = match["away_team_name"]
    else:
        raise ValueError(f"team_side khÃ´ng há»£p lá»‡: {team_side}")

    records: list[dict[str, Any]] = []

    for order, raw_goal_text in enumerate(chunks, start=1):
        lowered = raw_goal_text.casefold()
        is_penalty = bool(
            re.search(
                r"\bpen\b|\bpenalty\b|\(p\)",
                lowered,
            )
        )
        is_own_goal = bool(
            re.search(
                r"\bog\b|\bown goal\b",
                lowered,
            )
        )

        minute_match = re.search(
            r"(\d{1,3}(?:\+\d{1,2})?)\s*['â€™]?",
            raw_goal_text,
        )
        minute = (
            f"{minute_match.group(1)}'"
            if minute_match
            else None
        )

        player_name = raw_goal_text
        player_name = re.sub(
            r"\d{1,3}(?:\+\d{1,2})?\s*['â€™]?",
            " ",
            player_name,
        )
        player_name = re.sub(
            r"\(?\bpenalty\b\)?|\(?\bpen\b\)?|\(?\bp\b\)?",
            " ",
            player_name,
            flags=re.IGNORECASE,
        )
        player_name = re.sub(
            r"\(?\bown goal\b\)?|\(?\bog\b\)?",
            " ",
            player_name,
            flags=re.IGNORECASE,
        )
        player_name = re.sub(r"\s+", " ", player_name)
        player_name = player_name.strip(" -,:;()[]{}")

        if not player_name:
            continue

        records.append(
            {
                "goal_key": f"{team_side}_{order:03d}",
                "match_id": match["match_id"],
                "team_id": team_id,
                "team_name": team_name,
                "team_side": team_side,
                "player_name": player_name,
                "minute": minute,
                "is_penalty": is_penalty,
                "is_own_goal": is_own_goal,
                "source_provider": "thesportsdb",
                "source_event_id": source_event_id,
                "raw_goal_text": raw_goal_text,
            }
        )

    return records


def score_value_matches(
    event_score: Any,
    match_score: int | None,
) -> bool:
    if event_score in (None, ""):
        return True

    try:
        return int(event_score) == int(match_score)
    except (TypeError, ValueError):
        return True


def build_match_goals_from_thesportsdb(
    matches: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[int]]:
    events = download_thesportsdb_season_events()

    if not events:
        print("KhÃ´ng cÃ³ event TheSportsDB Ä‘á»ƒ sync scorer.")
        return [], []

    event_index = build_thesportsdb_event_index(events)
    event_detail_cache: dict[str, dict[str, Any] | None] = {}
    goal_records: list[dict[str, Any]] = []
    clear_goal_match_ids: list[int] = []

    for match in matches:
        if not match["is_finished"]:
            continue

        home_score = match["score_ft_home"]
        away_score = match["score_ft_away"]

        total_goals = int(home_score or 0) + int(away_score or 0)

        if total_goals == 0:
            clear_goal_match_ids.append(match["match_id"])
            continue

        event_key = (
            match["date_source"],
            normalize_team_match_key(match["home_team_name"]),
            normalize_team_match_key(match["away_team_name"]),
        )
        event = event_index.get(event_key)

        if not event:
            print("KhÃ´ng map Ä‘Æ°á»£c TheSportsDB event:", event_key)
            continue

        if not (
            score_value_matches(
                event.get("intHomeScore"),
                home_score,
            )
            and score_value_matches(
                event.get("intAwayScore"),
                away_score,
            )
        ):
            print(
                "Bá» qua scorer vÃ¬ tá»‰ sá»‘ TheSportsDB lá»‡ch:",
                match["home_team_name"],
                "vs",
                match["away_team_name"],
            )
            continue

        source_event_id = str(
            event.get("idEvent") or ""
        ).strip()

        detail = event

        if not (
            normalize_text(event.get("strHomeGoalDetails"))
            or normalize_text(event.get("strAwayGoalDetails"))
        ):
            event_detail = download_thesportsdb_event_detail(
                source_event_id,
                event_detail_cache,
            )

            if event_detail:
                detail = event_detail

        records: list[dict[str, Any]] = []
        records.extend(
            parse_goal_detail_text(
                detail.get("strHomeGoalDetails"),
                match,
                "home",
                source_event_id,
            )
        )
        records.extend(
            parse_goal_detail_text(
                detail.get("strAwayGoalDetails"),
                match,
                "away",
                source_event_id,
            )
        )

        if len(records) != total_goals:
            print(
                "Bá» qua scorer vÃ¬ sá»‘ bÃ n khÃ´ng khá»›p:",
                match["home_team_name"],
                "vs",
                match["away_team_name"],
                "score_goals=",
                total_goals,
                "parsed_goals=",
                len(records),
            )
            continue

        clear_goal_match_ids.append(match["match_id"])
        goal_records.extend(records)

    print("Sá»‘ tráº­n sáº½ cáº­p nháº­t scorer:", len(clear_goal_match_ids))
    print("Sá»‘ dÃ²ng scorer parse Ä‘Æ°á»£c:", len(goal_records))

    return goal_records, clear_goal_match_ids


def validate_dataset(
    teams: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    matchdays: list[int],
) -> None:
    errors: list[str] = []

    if len(teams) != EXPECTED_TEAM_COUNT:
        errors.append(
            f"Sá»‘ Ä‘á»™i={len(teams)}, ká»³ vá»ng={EXPECTED_TEAM_COUNT}."
        )

    if len(matches) != EXPECTED_MATCH_COUNT:
        errors.append(
            f"Sá»‘ tráº­n={len(matches)}, ká»³ vá»ng={EXPECTED_MATCH_COUNT}."
        )

    match_ids = [row["match_id"] for row in matches]
    source_ids = [row["source_match_id"] for row in matches]

    if len(match_ids) != len(set(match_ids)):
        errors.append("CÃ³ match_id bá»‹ trÃ¹ng.")

    if len(source_ids) != len(set(source_ids)):
        errors.append("CÃ³ source_match_id bá»‹ trÃ¹ng.")

    observed_matchdays = set(matchdays)

    if observed_matchdays != EXPECTED_MATCHDAYS:
        errors.append(
            "VÃ²ng Ä‘áº¥u khÃ´ng Ä‘á»§ 1 Ä‘áº¿n 38. "
            f"Äang cÃ³: {sorted(observed_matchdays)}"
        )

    matchday_counts = Counter(matchdays)

    invalid_round_counts = {
        round_no: count
        for round_no, count in matchday_counts.items()
        if count != 10
    }

    if invalid_round_counts:
        errors.append(
            "Má»™t sá»‘ vÃ²ng khÃ´ng cÃ³ Ä‘Ãºng 10 tráº­n: "
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
            "Lá»‹ch sÃ¢n nhÃ /sÃ¢n khÃ¡ch khÃ´ng há»£p lá»‡: "
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
                f"Tá»‰ sá»‘ thiáº¿u má»™t phÃ­a táº¡i match_id={row['match_id']}"
            )

    if errors:
        raise RuntimeError(
            "DATA VALIDATION FAILED:\n- "
            + "\n- ".join(errors)
        )

    finished_count = sum(
        1 for row in matches if row["is_finished"]
    )

    print("Validation thÃ nh cÃ´ng")
    print("Sá»‘ Ä‘á»™i:", len(teams))
    print("Sá»‘ tráº­n:", len(matches))
    print("Sá»‘ vÃ²ng:", len(observed_matchdays))
    print("ÄÃ£ cÃ³ káº¿t quáº£:", finished_count)
    print("ChÆ°a cÃ³ káº¿t quáº£:", len(matches) - finished_count)


def get_database_url() -> str:
    database_url = os.getenv(
        "DATABASE_URL",
        "",
    ).strip()

    if not database_url:
        raise RuntimeError(
            "Thiáº¿u environment variable DATABASE_URL."
        )

    parsed = make_url(database_url)

    if parsed.drivername != "postgresql+psycopg2":
        raise RuntimeError(
            "DATABASE_URL pháº£i dÃ¹ng postgresql+psycopg2."
        )

    if parsed.port != 5432:
        raise RuntimeError(
            "DATABASE_URL pháº£i dÃ¹ng Session Pooler port 5432."
        )

    return database_url


def ensure_database_schema(engine) -> None:
    required_tables = {
        "teams",
        "matches",
        "match_goals",
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
            "Database cÃ²n thiáº¿u báº£ng: "
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
        "match_goals": {
            "goal_key",
            "match_id",
            "team_id",
            "team_name",
            "team_side",
            "player_name",
            "minute",
            "is_penalty",
            "is_own_goal",
            "source_provider",
            "source_event_id",
            "raw_goal_text",
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
                f"Báº£ng {table_name} thiáº¿u cá»™t: "
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
    match_goals: list[dict[str, Any]] | None = None,
    clear_goal_match_ids: list[int] | None = None,
) -> dict[str, int]:
    match_goals = match_goals or []
    clear_goal_match_ids = clear_goal_match_ids or []

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
        match_goals_table = Table(
            "match_goals",
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

            if clear_goal_match_ids:
                connection.execute(
                    text(
                        """
                        DELETE FROM match_goals
                        WHERE match_id IN :match_ids
                        """
                    ).bindparams(
                        bindparam(
                            "match_ids",
                            expanding=True,
                        )
                    ),
                    {
                        "match_ids": clear_goal_match_ids,
                    },
                )

            if match_goals:
                goal_insert = pg_insert(
                    match_goals_table
                ).values(match_goals)

                goal_upsert = (
                    goal_insert
                    .on_conflict_do_update(
                        index_elements=[
                            match_goals_table.c.match_id,
                            match_goals_table.c.goal_key,
                        ],
                        set_={
                            column: getattr(
                                goal_insert.excluded,
                                column,
                            )
                            for column in MATCH_GOAL_COLUMNS
                            if column not in {
                                "match_id",
                                "goal_key",
                            }
                        },
                    )
                )

                connection.execute(goal_upsert)

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
                        (SELECT COUNT(*) FROM match_goals)
                            AS match_goals,
                        (SELECT COUNT(*) FROM predictions)
                            AS predictions
                    """
                )
            ).mappings().one()

        return {
            "teams": int(database_counts["teams"]),
            "matches": int(database_counts["matches"]),
            "match_goals": int(
                database_counts["match_goals"]
            ),
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
    print("EPL OPENFOOTBALL â†’ SUPABASE")
    print("=" * 72)
    print("Season:", SEASON_SLUG)

    payload = download_source()
    print("TÃªn giáº£i:", payload.get("name"))

    raw_matches = extract_raw_matches(payload)

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

    match_goals, clear_goal_match_ids = (
        build_match_goals_from_thesportsdb(
            matches,
        )
    )

    result = sync_database(
        teams,
        matches,
        match_goals=match_goals,
        clear_goal_match_ids=clear_goal_match_ids,
    )

    print("\n" + "=" * 72)
    print("SYNC THÃ€NH CÃ”NG")
    print("=" * 72)
    print(
        "Sá»‘ Ä‘á»™i trong database:",
        result["teams"],
    )
    print(
        "Sá»‘ tráº­n trong database:",
        result["matches"],
    )
    print(
        "Sá»‘ dÃ²ng scorer trong database:",
        result["match_goals"],
    )
    print(
        "Sá»‘ prediction hiá»‡n cÃ³:",
        result["predictions"],
    )
    print(
        "Sá»‘ tráº­n cÃ³ dá»¯ liá»‡u thay Ä‘á»•i:",
        result["changed_matches"],
    )
    print(
        "Sá»‘ prediction Ä‘Æ°á»£c cháº¥m láº¡i:",
        result["rescored_predictions"],
    )


if __name__ == "__main__":
    main()
