import argparse
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
THESPORTSDB_API_KEY = os.getenv("THESPORTSDB_API_KEY", "123").strip() or "123"
THESPORTSDB_LEAGUE_ID = os.getenv("THESPORTSDB_LEAGUE_ID", "4328").strip() or "4328"
THESPORTSDB_SEASON = os.getenv("THESPORTSDB_SEASON", "2025-2026").strip() or "2025-2026"
WRITE_PARTIAL_SCORERS = os.getenv("WRITE_PARTIAL_SCORERS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}
REQUEST_SLEEP_SECONDS = float(os.getenv("THESPORTSDB_REQUEST_SLEEP_SECONDS", "0.35"))

BASE_URL = f"https://www.thesportsdb.com/api/v1/json/{THESPORTSDB_API_KEY}"


TEAM_ALIASES = {
    "afc bournemouth": "bournemouth",
    "bournemouth": "bournemouth",
    "brighton hove albion": "brighton",
    "brighton and hove albion": "brighton",
    "brighton": "brighton",
    "man utd": "manchester united",
    "man united": "manchester united",
    "manchester utd": "manchester united",
    "manchester united": "manchester united",
    "man city": "manchester city",
    "manchester city": "manchester city",
    "newcastle": "newcastle united",
    "newcastle united": "newcastle united",
    "nottingham forest": "nottingham forest",
    "nottm forest": "nottingham forest",
    "spurs": "tottenham hotspur",
    "tottenham": "tottenham hotspur",
    "tottenham hotspur": "tottenham hotspur",
    "west ham": "west ham united",
    "west ham united": "west ham united",
    "wolves": "wolverhampton wanderers",
    "wolverhampton": "wolverhampton wanderers",
    "wolverhampton wanderers": "wolverhampton wanderers",
}


def normalize_team_name(value: str | None) -> str:
    if not value:
        return ""

    text_value = unicodedata.normalize("NFKD", str(value))
    text_value = "".join(ch for ch in text_value if not unicodedata.combining(ch))
    text_value = text_value.lower()
    text_value = text_value.replace("&", " and ")
    text_value = re.sub(r"\b(fc|afc)\b", " ", text_value)
    text_value = re.sub(r"[^a-z0-9]+", " ", text_value)
    text_value = re.sub(r"\s+", " ", text_value).strip()

    return TEAM_ALIASES.get(text_value, text_value)


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "t"}


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()

    raw = str(value).strip()
    if not raw:
        return None

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        pass

    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def match_dates(local_match_date: date | None, tsdb_date: date | None) -> bool:
    if local_match_date is None or tsdb_date is None:
        return True
    return abs((local_match_date - tsdb_date).days) <= 1


def get_engine() -> Engine:
    if not DATABASE_URL:
        raise RuntimeError("Missing DATABASE_URL environment variable.")

    return create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000 -c lock_timeout=5000",
        },
    )


def api_get(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{BASE_URL}/{endpoint}"
    response = requests.get(url, params=params or {}, timeout=30)
    response.raise_for_status()
    return response.json()


def ensure_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS match_goals (
                    goal_id SERIAL PRIMARY KEY,
                    goal_key TEXT NOT NULL,
                    match_id INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
                    team_id INTEGER,
                    team_name TEXT NOT NULL,
                    team_side TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    minute TEXT,
                    is_penalty BOOLEAN NOT NULL DEFAULT FALSE,
                    is_own_goal BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    UNIQUE(match_id, goal_key)
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS match_goal_sync_status (
                    match_id INTEGER PRIMARY KEY REFERENCES matches(match_id) ON DELETE CASCADE,
                    source TEXT NOT NULL DEFAULT 'thesportsdb',
                    source_event_id TEXT,
                    status TEXT NOT NULL,
                    expected_goals INTEGER,
                    fetched_goals INTEGER,
                    message TEXT,
                    synced_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
        )


def fetch_finished_matches(engine: Engine, match_id: int | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    where_parts = [
        "COALESCE(is_finished, FALSE) = TRUE",
        "home_score_for_prediction IS NOT NULL",
        "away_score_for_prediction IS NOT NULL",
    ]
    params: dict[str, Any] = {}

    if match_id is not None:
        where_parts.append("match_id = :match_id")
        params["match_id"] = match_id

    limit_sql = ""
    if limit is not None and limit > 0:
        limit_sql = "LIMIT :limit"
        params["limit"] = limit

    query = f"""
        SELECT
            match_id,
            home_team_id,
            away_team_id,
            home_team_name,
            away_team_name,
            kickoff_time_utc,
            kickoff_date_vietnam,
            home_score_for_prediction,
            away_score_for_prediction
        FROM matches
        WHERE {" AND ".join(where_parts)}
        ORDER BY kickoff_time_utc, match_id
        {limit_sql}
    """

    with engine.connect() as conn:
        rows = conn.execute(text(query), params).mappings().all()

    return [dict(row) for row in rows]


def load_season_events() -> list[dict[str, Any]]:
    data = api_get(
        "eventsseason.php",
        {
            "id": THESPORTSDB_LEAGUE_ID,
            "s": THESPORTSDB_SEASON,
        },
    )
    return data.get("events") or []


def find_tsdb_event(match: dict[str, Any], season_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    home_name = normalize_team_name(match.get("home_team_name"))
    away_name = normalize_team_name(match.get("away_team_name"))
    local_date = parse_date(match.get("kickoff_date_vietnam")) or parse_date(match.get("kickoff_time_utc"))
    home_score = parse_int(match.get("home_score_for_prediction"))
    away_score = parse_int(match.get("away_score_for_prediction"))

    candidates = []

    for event in season_events:
        event_home = normalize_team_name(event.get("strHomeTeam"))
        event_away = normalize_team_name(event.get("strAwayTeam"))
        event_date = parse_date(event.get("dateEvent"))

        if event_home != home_name or event_away != away_name:
            continue
        if not match_dates(local_date, event_date):
            continue

        score_bonus = 0
        if parse_int(event.get("intHomeScore")) == home_score:
            score_bonus += 1
        if parse_int(event.get("intAwayScore")) == away_score:
            score_bonus += 1

        date_distance = 0
        if local_date and event_date:
            date_distance = abs((local_date - event_date).days)

        candidates.append((score_bonus, -date_distance, event))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def fetch_timeline(event_id: str) -> list[dict[str, Any]]:
    data = api_get("lookuptimeline.php", {"id": event_id})
    return data.get("timeline") or data.get("timelines") or []


def clean_player_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def format_minute(value: Any) -> str:
    raw = str(value or "").strip().replace("`", "'").replace("’", "'")
    raw = raw.replace("'", "").strip()

    if not raw:
        return ""

    return f"{raw}'"


def goal_sort_value(minute: str) -> int:
    raw = minute.replace("'", "").strip()
    if "+" in raw:
        first, _, extra = raw.partition("+")
        return (parse_int(first) or 0) * 100 + (parse_int(extra) or 0)
    return (parse_int(raw) or 0) * 100


def parse_goal_events(match: dict[str, Any], tsdb_event: dict[str, Any], timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    home_tsdb = normalize_team_name(tsdb_event.get("strHomeTeam"))
    away_tsdb = normalize_team_name(tsdb_event.get("strAwayTeam"))
    home_local = normalize_team_name(match.get("home_team_name"))
    away_local = normalize_team_name(match.get("away_team_name"))

    goals: list[dict[str, Any]] = []

    for row in timeline:
        if str(row.get("strTimeline") or "").strip().lower() != "goal":
            continue

        detail = str(row.get("strTimelineDetail") or "").strip()
        detail_lower = detail.lower()
        player_name = clean_player_name(row.get("strPlayer"))

        if not player_name:
            continue

        scoring_team = normalize_team_name(row.get("strTeam"))
        if scoring_team in {home_tsdb, home_local}:
            team_side = "home"
            team_id = match.get("home_team_id")
            team_name = match.get("home_team_name")
        elif scoring_team in {away_tsdb, away_local}:
            team_side = "away"
            team_id = match.get("away_team_id")
            team_name = match.get("away_team_name")
        else:
            continue

        minute = format_minute(row.get("intTime"))
        is_penalty = "penalty" in detail_lower
        is_own_goal = "own goal" in detail_lower

        goals.append(
            {
                "team_id": team_id,
                "team_name": team_name,
                "team_side": team_side,
                "player_name": player_name,
                "minute": minute,
                "is_penalty": is_penalty,
                "is_own_goal": is_own_goal,
                "sort_value": goal_sort_value(minute),
            }
        )

    goals.sort(key=lambda item: (item["sort_value"], item["team_side"], item["player_name"]))

    for index, goal in enumerate(goals, start=1):
        safe_name = re.sub(r"[^a-z0-9]+", "_", goal["player_name"].lower()).strip("_")[:40]
        goal["goal_key"] = f"{goal['sort_value']:05d}_{index:02d}_{safe_name}"

    return goals


def upsert_sync_status(
    engine: Engine,
    match_id: int,
    source_event_id: str | None,
    status: str,
    expected_goals: int,
    fetched_goals: int,
    message: str,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO match_goal_sync_status (
                    match_id,
                    source,
                    source_event_id,
                    status,
                    expected_goals,
                    fetched_goals,
                    message,
                    synced_at
                )
                VALUES (
                    :match_id,
                    'thesportsdb',
                    :source_event_id,
                    :status,
                    :expected_goals,
                    :fetched_goals,
                    :message,
                    NOW()
                )
                ON CONFLICT (match_id)
                DO UPDATE SET
                    source = EXCLUDED.source,
                    source_event_id = EXCLUDED.source_event_id,
                    status = EXCLUDED.status,
                    expected_goals = EXCLUDED.expected_goals,
                    fetched_goals = EXCLUDED.fetched_goals,
                    message = EXCLUDED.message,
                    synced_at = NOW()
                """
            ),
            {
                "match_id": match_id,
                "source_event_id": source_event_id,
                "status": status,
                "expected_goals": expected_goals,
                "fetched_goals": fetched_goals,
                "message": message[:1000],
            },
        )


def replace_match_goals(engine: Engine, match_id: int, goals: list[dict[str, Any]]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM match_goals WHERE match_id = :match_id"),
            {"match_id": match_id},
        )

        for goal in goals:
            conn.execute(
                text(
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
                    ON CONFLICT (match_id, goal_key)
                    DO UPDATE SET
                        team_id = EXCLUDED.team_id,
                        team_name = EXCLUDED.team_name,
                        team_side = EXCLUDED.team_side,
                        player_name = EXCLUDED.player_name,
                        minute = EXCLUDED.minute,
                        is_penalty = EXCLUDED.is_penalty,
                        is_own_goal = EXCLUDED.is_own_goal
                    """
                ),
                {
                    **goal,
                    "match_id": match_id,
                },
            )


def sync_one_match(engine: Engine, match: dict[str, Any], season_events: list[dict[str, Any]], dry_run: bool) -> str:
    match_id = int(match["match_id"])
    label = f"{match_id} | {match.get('home_team_name')} vs {match.get('away_team_name')}"
    expected_goals = (parse_int(match.get("home_score_for_prediction")) or 0) + (
        parse_int(match.get("away_score_for_prediction")) or 0
    )

    if expected_goals == 0:
        if not dry_run:
            replace_match_goals(engine, match_id, [])
            upsert_sync_status(engine, match_id, None, "synced_zero_zero", 0, 0, "0-0 match, no scorers.")
        return f"OK  {label}: 0-0, cleared scorers."

    tsdb_event = find_tsdb_event(match, season_events)
    if not tsdb_event:
        if not dry_run:
            upsert_sync_status(
                engine,
                match_id,
                None,
                "event_not_found",
                expected_goals,
                0,
                "Could not match this Supabase match to a TheSportsDB event.",
            )
        return f"MISS {label}: no TheSportsDB event found."

    event_id = str(tsdb_event.get("idEvent") or "")
    timeline = fetch_timeline(event_id)
    goals = parse_goal_events(match, tsdb_event, timeline)
    fetched_goals = len(goals)

    if fetched_goals != expected_goals and not WRITE_PARTIAL_SCORERS:
        message = (
            f"Fetched {fetched_goals} goal events but match score expects {expected_goals}. "
            "Skipped writing to avoid incomplete scorer display."
        )
        if not dry_run:
            upsert_sync_status(engine, match_id, event_id, "goal_count_mismatch", expected_goals, fetched_goals, message)
        return f"WARN {label}: {message}"

    status = "synced"
    message = "Scorers synced successfully."

    if fetched_goals != expected_goals:
        status = "synced_partial"
        message = f"Partial sync allowed: fetched {fetched_goals}, expected {expected_goals}."

    if not dry_run:
        replace_match_goals(engine, match_id, goals)
        upsert_sync_status(engine, match_id, event_id, status, expected_goals, fetched_goals, message)

    goal_labels = ", ".join(f"{goal['player_name']} {goal['minute']}".strip() for goal in goals)
    return f"OK  {label}: {status} from event {event_id} -> {goal_labels}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync EPL goal scorers from TheSportsDB into Supabase.")
    parser.add_argument("--match-id", type=int, default=None, help="Only sync one Supabase match_id.")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of finished matches processed.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without writing to Supabase.")
    args = parser.parse_args()

    engine = get_engine()
    ensure_tables(engine)

    matches = fetch_finished_matches(engine, match_id=args.match_id, limit=args.limit)
    if not matches:
        print("No finished matches found in Supabase.")
        return 0

    print(
        f"Loading TheSportsDB season events: league={THESPORTSDB_LEAGUE_ID}, "
        f"season={THESPORTSDB_SEASON}, partial={WRITE_PARTIAL_SCORERS}, dry_run={args.dry_run}"
    )
    season_events = load_season_events()
    print(f"Loaded {len(season_events)} season events.")

    if not season_events:
        print("No TheSportsDB season events returned. Stop.")
        return 1

    results = []
    for match in matches:
        try:
            results.append(sync_one_match(engine, match, season_events, dry_run=args.dry_run))
        except Exception as exc:
            match_id = int(match["match_id"])
            message = f"{type(exc).__name__}: {exc}"
            if not args.dry_run:
                expected_goals = (parse_int(match.get("home_score_for_prediction")) or 0) + (
                    parse_int(match.get("away_score_for_prediction")) or 0
                )
                upsert_sync_status(engine, match_id, None, "error", expected_goals, 0, message)
            results.append(f"ERR {match_id}: {message}")

        time.sleep(REQUEST_SLEEP_SECONDS)

    for line in results:
        print(line)

    warnings = [line for line in results if line.startswith(("WARN", "MISS", "ERR"))]
    print(f"Done. processed={len(results)}, warnings={len(warnings)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
