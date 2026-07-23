"""
Free ESPN EPL goal scorer crawler.

Purpose
-------
Crawler rieng de lay du lieu cau thu ghi ban EPL tu ESPN public JSON va xuat
ve dung shape gan voi bang match_goals cua app World Cup / EPL:

goal_key, match_id, team_id, team_name, team_side, player_name, minute,
is_penalty, is_own_goal, source_provider, source_event_id, raw_goal_text

Nguon du lieu
-------------
- Scoreboard theo ngay:
  https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard
- Summary theo event:
  https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/summary?event=...

ESPN public JSON la nguon free/unofficial, nen script nay chi ghi row scorer
khi so ban parse duoc khop chinh xac voi ti so ESPN.

Cach chay tren Colab
--------------------
1. Paste toan bo file nay vao 1 cell hoac upload file len Colab.
2. Chay:

   !python crawl_epl_espn_goal_scorers_full.py

3. De dung cho mua sau:

   !EPL_SEASON_SLUG=2026-27 EPL_SEASON_START=2026-08-14 EPL_SEASON_END=2027-05-23 \
     python crawl_epl_espn_goal_scorers_full.py

4. Neu co file export tu bang matches cua Supabase, them:

   !MATCHES_CSV_PATH=matches_export.csv python crawl_epl_espn_goal_scorers_full.py

Output mac dinh
---------------
- epl_match_goals_espn_<season>.csv
- epl_match_goals_espn_audit_<season>.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


LEAGUE = os.getenv("ESPN_LEAGUE", "eng.1").strip()
SITE_BASE = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{LEAGUE}"

SEASON_SLUG = os.getenv("EPL_SEASON_SLUG", "2025-26").strip()
SEASON_START = os.getenv("EPL_SEASON_START", "2025-08-15").strip()
SEASON_END = os.getenv("EPL_SEASON_END", "2026-05-24").strip()

MATCHES_CSV_PATH = os.getenv("MATCHES_CSV_PATH", "").strip()
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", ".")).resolve()

REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "25"))
REQUEST_RETRIES = int(os.getenv("REQUEST_RETRIES", "3"))
REQUEST_SLEEP_SECONDS = float(os.getenv("REQUEST_SLEEP_SECONDS", "0.15"))

ONLY_FINISHED = os.getenv("ONLY_FINISHED", "1").strip() != "0"
STOP_AT_TODAY = os.getenv("STOP_AT_TODAY", "1").strip() != "0"
STRICT_HOME_AWAY = os.getenv("STRICT_HOME_AWAY", "1").strip() != "0"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

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

AUDIT_COLUMNS = [
    "season_slug",
    "event_id",
    "competition_id",
    "espn_date_utc",
    "espn_date_vietnam",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "status",
    "completed",
    "selected_source",
    "key_events",
    "commentary",
    "scoring_plays",
    "plays",
    "parsed_home_goals",
    "parsed_away_goals",
    "unknown_team_goals",
    "expected_home",
    "expected_away",
    "validation_status",
    "records_written",
    "match_id",
    "note",
]

TEAM_ALIASES = {
    "afc bournemouth": "bournemouth",
    "bournemouth": "bournemouth",
    "brighton": "brighton and hove albion",
    "brighton hove albion": "brighton and hove albion",
    "brighton and hove": "brighton and hove albion",
    "brighton and hove albion": "brighton and hove albion",
    "crystal palace": "crystal palace",
    "leeds": "leeds united",
    "leeds united": "leeds united",
    "man city": "manchester city",
    "manchester city": "manchester city",
    "man united": "manchester united",
    "man utd": "manchester united",
    "manchester united": "manchester united",
    "newcastle": "newcastle united",
    "newcastle united": "newcastle united",
    "nottm forest": "nottingham forest",
    "nottingham": "nottingham forest",
    "nottingham forest": "nottingham forest",
    "spurs": "tottenham hotspur",
    "tottenham": "tottenham hotspur",
    "tottenham hotspur": "tottenham hotspur",
    "west ham": "west ham united",
    "west ham united": "west ham united",
    "wolves": "wolverhampton wanderers",
    "wolverhampton": "wolverhampton wanderers",
    "wolverhampton wanderers": "wolverhampton wanderers",
}


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def daterange(start_value: date, end_value: date) -> Iterable[date]:
    current = start_value
    while current <= end_value:
        yield current
        current += timedelta(days=1)


def yyyymmdd(value: date | str) -> str:
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")


def safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def fetch_json(
    url: str,
    params: dict[str, Any] | None = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
    retries: int = REQUEST_RETRIES,
) -> dict[str, Any]:
    if params:
        query = urllib.parse.urlencode(params)
        url = f"{url}?{query}"

    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc
            time.sleep(min(attempt * 1.5, 6))

    raise RuntimeError(f"Cannot fetch JSON from {url}: {last_error}")


def normalize_team_key(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\b(fc|afc|the)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return TEAM_ALIASES.get(text, text)


def team_matches(expected: Any, actual: Any) -> bool:
    expected_key = normalize_team_key(expected)
    actual_key = normalize_team_key(actual)
    return bool(
        expected_key
        and actual_key
        and (
            expected_key == actual_key
            or expected_key in actual_key
            or actual_key in expected_key
        )
    )


def parse_espn_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    text = value.replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def espn_date_utc(value: str | None) -> str:
    parsed = parse_espn_datetime(value)
    if not parsed:
        return ""
    return parsed.date().isoformat()


def espn_date_vietnam(value: str | None) -> str:
    parsed = parse_espn_datetime(value)
    if not parsed:
        return ""
    return (parsed + timedelta(hours=7)).date().isoformat()


def get_scoreboard(day: date) -> dict[str, Any]:
    return fetch_json(
        f"{SITE_BASE}/scoreboard",
        params={"dates": yyyymmdd(day), "limit": 100},
    )


def flatten_scoreboard_events(scoreboard: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for event in scoreboard.get("events") or []:
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors") or []
        home = next((row for row in competitors if row.get("homeAway") == "home"), {})
        away = next((row for row in competitors if row.get("homeAway") == "away"), {})
        home_team = home.get("team") or {}
        away_team = away.get("team") or {}
        status = ((competition.get("status") or {}).get("type") or {})

        rows.append(
            {
                "event_id": str(event.get("id") or ""),
                "competition_id": str(competition.get("id") or event.get("id") or ""),
                "espn_date_utc": event.get("date") or "",
                "home_team": home_team.get("displayName") or home_team.get("name") or "",
                "away_team": away_team.get("displayName") or away_team.get("name") or "",
                "home_score": safe_int(home.get("score")),
                "away_score": safe_int(away.get("score")),
                "status": status.get("description") or status.get("name") or "",
                "completed": bool(status.get("completed")),
                "raw_event": event,
            }
        )

    return rows


def get_summary(event_id: str) -> dict[str, Any]:
    return fetch_json(f"{SITE_BASE}/summary", params={"event": event_id})


def unwrap_play(item: dict[str, Any]) -> dict[str, Any]:
    play = item.get("play")
    return play if isinstance(play, dict) else item


def type_text(item: dict[str, Any]) -> str:
    typ = item.get("type")

    if isinstance(typ, dict):
        parts = [
            typ.get("text"),
            typ.get("description"),
            typ.get("name"),
            typ.get("type"),
        ]
        return " ".join(str(part) for part in parts if part)

    if isinstance(typ, str):
        return typ

    return ""


def is_goal_item(item: dict[str, Any]) -> bool:
    item = unwrap_play(item)
    if not isinstance(item, dict):
        return False

    raw_type = type_text(item).casefold()
    text = str(item.get("text") or item.get("shortText") or "").strip()
    text_cf = text.casefold()

    if item.get("shootout") is True or "shootout" in raw_type or "shootout" in text_cf:
        return False

    if item.get("scoringPlay") is True:
        return True

    if raw_type.startswith(("goal", "own goal", "penalty - scored", "penalty goal")):
        return True

    if text.startswith("Goal!") or text.startswith("Own Goal by"):
        return True

    return False


def extract_minute(item: dict[str, Any]) -> str:
    item = unwrap_play(item)

    for key in ("clock", "time"):
        value = item.get(key)
        if isinstance(value, dict) and value.get("displayValue"):
            return str(value["displayValue"])

    for key in ("displayTime", "minute"):
        value = item.get(key)
        if value is not None and value != "":
            return str(value)

    text = str(item.get("text") or item.get("shortText") or "")
    match = re.search(r"(\d{1,3}(?:'\+\d{1,2})?|\d{1,3}(?:\+\d{1,2})?['’])", text)
    return match.group(1) if match else ""


def minute_sort_key(value: str) -> tuple[int, int]:
    match = re.search(r"(\d{1,3})(?:['’]\+(\d{1,2})|\+(\d{1,2}))?", value or "")
    if not match:
        return (999, 0)

    return (int(match.group(1)), int(match.group(2) or match.group(3) or 0))


def athlete_name(athlete: dict[str, Any]) -> str:
    for key in ("displayName", "fullName", "name", "shortName"):
        if athlete.get(key):
            return str(athlete[key])
    return ""


def extract_player_name(item: dict[str, Any]) -> str:
    item = unwrap_play(item)

    text = str(item.get("text") or item.get("shortText") or "")
    own_goal_match = re.search(r"Own Goal by\s+([^,.]+)", text)
    if own_goal_match:
        return own_goal_match.group(1).strip()

    for list_key in ("participants", "athletes", "players"):
        values = item.get(list_key)
        if not isinstance(values, list):
            continue

        for value in values:
            if not isinstance(value, dict):
                continue

            athlete = value.get("athlete") if isinstance(value.get("athlete"), dict) else value
            name = athlete_name(athlete)
            if name:
                return name

    for key in ("athlete", "player"):
        value = item.get(key)
        if isinstance(value, dict):
            name = athlete_name(value)
            if name:
                return name

    goal_match = re.search(r"Goal!\s*[^.]+\.\s*([^(.]+?)\s*\(", text)
    if goal_match:
        return goal_match.group(1).strip()

    short_text = str(item.get("shortText") or "")
    short_match = re.match(r"(.+?)\s+(?:Goal|Own Goal|Penalty)", short_text)
    if short_match:
        return short_match.group(1).strip()

    return ""


def extract_team_name(item: dict[str, Any]) -> str:
    item = unwrap_play(item)
    team = item.get("team")

    if isinstance(team, dict):
        for key in ("displayName", "name", "shortDisplayName", "abbreviation"):
            if team.get(key):
                return str(team[key])

    text = str(item.get("text") or item.get("shortText") or "")
    goal_match = re.search(r"Goal!\s*([^,.]+)", text)
    if goal_match:
        scoreboard_text = goal_match.group(1)
        score_team_match = re.match(r"(.+?)\s+\d", scoreboard_text)
        if score_team_match:
            return score_team_match.group(1).strip()

    return ""


def is_penalty_goal(item: dict[str, Any]) -> bool:
    item = unwrap_play(item)
    text = " ".join(
        [
            type_text(item),
            str(item.get("text") or ""),
            str(item.get("shortText") or ""),
        ]
    ).casefold()
    return "penalty" in text and "shootout" not in text


def is_own_goal(item: dict[str, Any]) -> bool:
    item = unwrap_play(item)
    text = " ".join(
        [
            type_text(item),
            str(item.get("text") or ""),
            str(item.get("shortText") or ""),
        ]
    ).casefold()
    return item.get("ownGoal") is True or "own goal" in text


def parse_goal_rows(items: Iterable[dict[str, Any]], source_provider: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for original_item in items or []:
        if not isinstance(original_item, dict) or not is_goal_item(original_item):
            continue

        item = unwrap_play(original_item)
        minute = extract_minute(item)
        team_name = extract_team_name(item)
        player_name = extract_player_name(item)
        raw_text = str(item.get("text") or original_item.get("text") or item.get("shortText") or "")
        source_event_id = str(item.get("id") or original_item.get("id") or "")

        dedupe_key = (
            source_event_id,
            minute,
            normalize_team_key(team_name),
            unicodedata.normalize("NFKD", player_name).casefold(),
            raw_text[:120],
        )

        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        rows.append(
            {
                "minute": minute,
                "team_name": team_name,
                "player_name": player_name,
                "is_penalty": is_penalty_goal(item),
                "is_own_goal": is_own_goal(item),
                "source_provider": source_provider,
                "source_event_id": source_event_id,
                "raw_goal_text": raw_text,
                "raw_type": type_text(item),
            }
        )

    rows.sort(key=lambda row: (minute_sort_key(row["minute"]), row["source_event_id"]))
    return rows


def choose_best_goal_source(summary: dict[str, Any]) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    source_items = [
        ("espn_keyEvents", summary.get("keyEvents") or []),
        ("espn_commentary", summary.get("commentary") or []),
        ("espn_scoringPlays", summary.get("scoringPlays") or []),
        ("espn_plays", summary.get("plays") or []),
    ]
    source_counts = {
        "key_events": len(summary.get("keyEvents") or []),
        "commentary": len(summary.get("commentary") or []),
        "scoring_plays": len(summary.get("scoringPlays") or []),
        "plays": len(summary.get("plays") or []),
    }

    parsed = [
        (source_name, parse_goal_rows(items, source_name))
        for source_name, items in source_items
    ]

    for source_name, goals in parsed:
        if source_name == "espn_keyEvents" and goals:
            return source_name, goals, source_counts

    selected_source, selected_goals = max(parsed, key=lambda row: len(row[1]))
    return selected_source, selected_goals, source_counts


def side_for_goal(team_name: str, home_team: str, away_team: str) -> str | None:
    if team_matches(home_team, team_name):
        return "home"
    if team_matches(away_team, team_name):
        return "away"
    return None


def validate_goals(
    goals: list[dict[str, Any]],
    home_team: str,
    away_team: str,
    expected_home: int | None,
    expected_away: int | None,
) -> dict[str, Any]:
    home_count = 0
    away_count = 0
    unknown_count = 0

    for goal in goals:
        side = side_for_goal(goal.get("team_name", ""), home_team, away_team)
        if side == "home":
            home_count += 1
        elif side == "away":
            away_count += 1
        else:
            unknown_count += 1

    if expected_home is None or expected_away is None:
        return {
            "status": "NO_SCORE",
            "home_goals": home_count,
            "away_goals": away_count,
            "unknown_team_goals": unknown_count,
        }

    ok = (
        home_count == expected_home
        and away_count == expected_away
        and unknown_count == 0
        and len(goals) == expected_home + expected_away
    )

    return {
        "status": "OK" if ok else "MISMATCH",
        "home_goals": home_count,
        "away_goals": away_count,
        "unknown_team_goals": unknown_count,
    }


def load_matches_csv(path: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    if not path:
        return {}

    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Không tìm thấy MATCHES_CSV_PATH: {csv_path}")

    index: dict[tuple[str, str, str], dict[str, Any]] = {}

    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            home_team = row.get("home_team_name") or row.get("home_team") or ""
            away_team = row.get("away_team_name") or row.get("away_team") or ""
            if not home_team or not away_team:
                continue

            date_candidates = [
                row.get("date_source"),
                row.get("kickoff_date_utc"),
                row.get("kickoff_date_vietnam"),
                row.get("date"),
            ]

            for date_value in date_candidates:
                if not date_value:
                    continue

                key = (
                    str(date_value)[:10],
                    normalize_team_key(home_team),
                    normalize_team_key(away_team),
                )
                index[key] = row

    return index


def find_db_match(
    event: dict[str, Any],
    match_index: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    if not match_index:
        return None

    home_key = normalize_team_key(event["home_team"])
    away_key = normalize_team_key(event["away_team"])
    dates = {
        espn_date_utc(event["espn_date_utc"]),
        espn_date_vietnam(event["espn_date_utc"]),
    }
    dates.discard("")

    for date_value in sorted(dates):
        row = match_index.get((date_value, home_key, away_key))
        if row:
            return row

    return None


def csv_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None


def build_match_goal_records(
    goals: list[dict[str, Any]],
    event: dict[str, Any],
    db_match: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    home_team = event["home_team"]
    away_team = event["away_team"]
    match_id = csv_int((db_match or {}).get("match_id"))
    home_team_id = csv_int((db_match or {}).get("home_team_id"))
    away_team_id = csv_int((db_match or {}).get("away_team_id"))

    counters: dict[str, int] = defaultdict(int)
    records: list[dict[str, Any]] = []

    for goal in goals:
        side = side_for_goal(goal["team_name"], home_team, away_team)
        if side not in {"home", "away"}:
            continue

        counters[side] += 1
        records.append(
            {
                "goal_key": f"{side}_{counters[side]:03d}",
                "match_id": match_id,
                "team_id": home_team_id if side == "home" else away_team_id,
                "team_name": home_team if side == "home" else away_team,
                "team_side": side,
                "player_name": goal["player_name"],
                "minute": goal["minute"],
                "is_penalty": bool(goal["is_penalty"]),
                "is_own_goal": bool(goal["is_own_goal"]),
                "source_provider": goal["source_provider"],
                "source_event_id": goal["source_event_id"],
                "raw_goal_text": goal["raw_goal_text"],
            }
        )

    return records


def process_event(
    event: dict[str, Any],
    match_index: dict[tuple[str, str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], int | None]:
    expected_home = event["home_score"]
    expected_away = event["away_score"]
    db_match = find_db_match(event, match_index)
    match_id = csv_int((db_match or {}).get("match_id"))

    audit = {
        "season_slug": SEASON_SLUG,
        "event_id": event["event_id"],
        "competition_id": event["competition_id"],
        "espn_date_utc": espn_date_utc(event["espn_date_utc"]),
        "espn_date_vietnam": espn_date_vietnam(event["espn_date_utc"]),
        "home_team": event["home_team"],
        "away_team": event["away_team"],
        "home_score": expected_home,
        "away_score": expected_away,
        "status": event["status"],
        "completed": event["completed"],
        "selected_source": "",
        "key_events": 0,
        "commentary": 0,
        "scoring_plays": 0,
        "plays": 0,
        "parsed_home_goals": 0,
        "parsed_away_goals": 0,
        "unknown_team_goals": 0,
        "expected_home": expected_home,
        "expected_away": expected_away,
        "validation_status": "SKIPPED",
        "records_written": 0,
        "match_id": match_id,
        "note": "",
    }

    if ONLY_FINISHED and not event["completed"]:
        audit["note"] = "skip_not_finished"
        return [], audit, None

    if expected_home is None or expected_away is None:
        audit["validation_status"] = "NO_SCORE"
        audit["note"] = "skip_no_score"
        return [], audit, None

    total_goals = int(expected_home) + int(expected_away)

    if total_goals == 0:
        audit["validation_status"] = "OK"
        audit["note"] = "finished_0_0_clear_existing_goals_if_match_id_exists"
        return [], audit, match_id

    summary = get_summary(event["event_id"])
    selected_source, goals, source_counts = choose_best_goal_source(summary)
    validation = validate_goals(
        goals,
        event["home_team"],
        event["away_team"],
        int(expected_home),
        int(expected_away),
    )

    audit.update(source_counts)
    audit["selected_source"] = selected_source
    audit["parsed_home_goals"] = validation["home_goals"]
    audit["parsed_away_goals"] = validation["away_goals"]
    audit["unknown_team_goals"] = validation["unknown_team_goals"]
    audit["validation_status"] = validation["status"]

    if validation["status"] != "OK":
        audit["note"] = "do_not_insert_validation_mismatch"
        return [], audit, None

    records = build_match_goal_records(goals, event, db_match)
    audit["records_written"] = len(records)

    if match_index and not db_match:
        audit["note"] = "validated_but_no_db_match_mapping"
    elif not match_index:
        audit["note"] = "validated_without_db_mapping"
    else:
        audit["note"] = "validated_with_db_mapping"

    return records, audit, match_id


def crawl_scoreboard_events(
    start_date: date,
    end_date: date,
    dry_run_limit: int | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for day in daterange(start_date, end_date):
        scoreboard = get_scoreboard(day)
        day_events = flatten_scoreboard_events(scoreboard)

        if day_events:
            print(f"{day.isoformat()}: {len(day_events)} events")

        events.extend(day_events)
        time.sleep(REQUEST_SLEEP_SECONDS)

        if dry_run_limit and len(events) >= dry_run_limit:
            return events[:dry_run_limit]

    return events


def crawl_season_goal_scorers(
    start_date: date,
    end_date: date,
    matches_csv_path: str = "",
    dry_run_limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[int]]:
    match_index = load_matches_csv(matches_csv_path)
    if match_index:
        print("Loaded DB match mapping rows:", len(match_index))

    events = crawl_scoreboard_events(start_date, end_date, dry_run_limit=dry_run_limit)
    print("Total ESPN events found:", len(events))

    goal_records: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    clear_match_ids: list[int] = []

    for index, event in enumerate(events, start=1):
        print(
            f"[{index}/{len(events)}] "
            f"{event['home_team']} vs {event['away_team']} "
            f"{event['home_score']}-{event['away_score']} | {event['status']}"
        )

        try:
            records, audit, clear_match_id = process_event(event, match_index)
        except Exception as exc:
            records = []
            clear_match_id = None
            audit = {
                "season_slug": SEASON_SLUG,
                "event_id": event.get("event_id"),
                "competition_id": event.get("competition_id"),
                "espn_date_utc": espn_date_utc(event.get("espn_date_utc")),
                "espn_date_vietnam": espn_date_vietnam(event.get("espn_date_utc")),
                "home_team": event.get("home_team"),
                "away_team": event.get("away_team"),
                "home_score": event.get("home_score"),
                "away_score": event.get("away_score"),
                "status": event.get("status"),
                "completed": event.get("completed"),
                "selected_source": "",
                "key_events": 0,
                "commentary": 0,
                "scoring_plays": 0,
                "plays": 0,
                "parsed_home_goals": 0,
                "parsed_away_goals": 0,
                "unknown_team_goals": 0,
                "expected_home": event.get("home_score"),
                "expected_away": event.get("away_score"),
                "validation_status": "ERROR",
                "records_written": 0,
                "match_id": None,
                "note": repr(exc),
            }

        goal_records.extend(records)
        audit_rows.append(audit)

        if clear_match_id is not None:
            clear_match_ids.append(clear_match_id)

        time.sleep(REQUEST_SLEEP_SECONDS)

    return goal_records, audit_rows, clear_match_ids


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sync_match_goals_to_postgres(
    goal_records: list[dict[str, Any]],
    clear_match_ids: list[int],
) -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is empty. Skip database sync.")
        return

    if not clear_match_ids:
        print("No mapped match_id to sync. Skip database sync.")
        return

    try:
        from sqlalchemy import MetaData, Table, bindparam, create_engine, text
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.pool import NullPool
    except ImportError as exc:
        raise RuntimeError(
            "Database sync needs sqlalchemy and psycopg2. "
            "On Colab: !pip install sqlalchemy psycopg2-binary"
        ) from exc

    valid_goal_records = [row for row in goal_records if row.get("match_id") is not None]

    engine = create_engine(database_url, poolclass=NullPool, pool_pre_ping=True)
    metadata = MetaData()

    try:
        match_goals_table = Table("match_goals", metadata, autoload_with=engine)

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DELETE FROM match_goals
                    WHERE match_id IN :match_ids
                    """
                ).bindparams(bindparam("match_ids", expanding=True)),
                {"match_ids": sorted(set(clear_match_ids))},
            )

            if valid_goal_records:
                insert_statement = pg_insert(match_goals_table).values(valid_goal_records)
                upsert_statement = insert_statement.on_conflict_do_update(
                    index_elements=[
                        match_goals_table.c.match_id,
                        match_goals_table.c.goal_key,
                    ],
                    set_={
                        column: getattr(insert_statement.excluded, column)
                        for column in MATCH_GOAL_COLUMNS
                        if column not in {"match_id", "goal_key"}
                    },
                )
                connection.execute(upsert_statement)

        print("Database sync done.")
        print("Cleared match IDs:", len(set(clear_match_ids)))
        print("Upserted goal rows:", len(valid_goal_records))
    finally:
        engine.dispose()


def resolve_date_range(args: argparse.Namespace) -> tuple[date, date]:
    start_date = parse_iso_date(args.start)
    end_date = parse_iso_date(args.end)

    if STOP_AT_TODAY and not args.ignore_today_cap:
        end_date = min(end_date, datetime.now().date())

    if end_date < start_date:
        raise ValueError(f"Invalid date range: {start_date} -> {end_date}")

    return start_date, end_date


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl EPL goal scorers from ESPN public JSON.",
    )
    parser.add_argument("--season", default=SEASON_SLUG)
    parser.add_argument("--start", default=SEASON_START)
    parser.add_argument("--end", default=SEASON_END)
    parser.add_argument("--matches-csv", default=MATCHES_CSV_PATH)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--dry-run-limit", type=int, default=0)
    parser.add_argument("--sync-db", action="store_true")
    parser.add_argument("--ignore-today-cap", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    global SEASON_SLUG
    SEASON_SLUG = args.season

    output_dir = Path(args.output_dir).resolve()
    start_date, end_date = resolve_date_range(args)
    dry_run_limit = args.dry_run_limit or None

    safe_season = re.sub(r"[^0-9A-Za-z_-]+", "_", args.season)
    goals_path = output_dir / f"epl_match_goals_espn_{safe_season}.csv"
    audit_path = output_dir / f"epl_match_goals_espn_audit_{safe_season}.csv"

    print("=" * 80)
    print("ESPN EPL GOAL SCORER CRAWLER")
    print("=" * 80)
    print("League:", LEAGUE)
    print("Season:", args.season)
    print("Date range:", start_date.isoformat(), "->", end_date.isoformat())
    print("Only finished:", ONLY_FINISHED)
    print("Matches CSV:", args.matches_csv or "(none)")
    print("Output goals:", goals_path)
    print("Output audit:", audit_path)

    goal_records, audit_rows, clear_match_ids = crawl_season_goal_scorers(
        start_date=start_date,
        end_date=end_date,
        matches_csv_path=args.matches_csv,
        dry_run_limit=dry_run_limit,
    )

    write_csv(goals_path, goal_records, MATCH_GOAL_COLUMNS)
    write_csv(audit_path, audit_rows, AUDIT_COLUMNS)

    ok_matches = sum(1 for row in audit_rows if row["validation_status"] == "OK")
    mismatch_matches = sum(1 for row in audit_rows if row["validation_status"] == "MISMATCH")
    error_matches = sum(1 for row in audit_rows if row["validation_status"] == "ERROR")
    skipped_matches = sum(1 for row in audit_rows if row["validation_status"] == "SKIPPED")

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)
    print("Events audited:", len(audit_rows))
    print("OK matches:", ok_matches)
    print("Mismatch matches:", mismatch_matches)
    print("Error matches:", error_matches)
    print("Skipped matches:", skipped_matches)
    print("Goal rows written:", len(goal_records))
    print("Clear match IDs:", len(set(clear_match_ids)))

    if mismatch_matches or error_matches:
        print("\nCheck audit CSV before inserting into database.")

    if args.sync_db:
        sync_match_goals_to_postgres(goal_records, clear_match_ids)


if __name__ == "__main__":
    main()
