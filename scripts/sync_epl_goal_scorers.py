import argparse
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from typing import Any

import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
THESPORTSDB_API_KEY = os.getenv("THESPORTSDB_API_KEY", "123").strip() or "123"
THESPORTSDB_LEAGUE_ID = os.getenv("THESPORTSDB_LEAGUE_ID", "4328").strip() or "4328"
THESPORTSDB_SEASON = os.getenv("THESPORTSDB_SEASON", "2025-2026").strip() or "2025-2026"
REQUEST_SLEEP_SECONDS = float(os.getenv("THESPORTSDB_REQUEST_SLEEP_SECONDS", "2.1"))
WRITE_PARTIAL_SCORERS = os.getenv("WRITE_PARTIAL_SCORERS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}

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


def normalize_team_name(value: Any) -> str:
    if value is None:
        return ""

    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = value.replace("&", " and ")
    value = re.sub(r"\b(fc|afc)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    return TEAM_ALIASES.get(value, value)


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

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    value = str(value).strip()
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass

    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def dates_match(local_date: date | None, event_date: date | None) -> bool:
    if local_date is None or event_date is None:
        return True

    return abs((local_date - event_date).days) <= 1


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


def api_get(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def ensure_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE matches
                ADD COLUMN IF NOT EXISTS thesportsdb_event_id TEXT
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_thesportsdb_event_id
                ON matches(thesportsdb_event_id)
                WHERE thesportsdb_event_id IS NOT NULL
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS match_goals (
                    goal_id BIGSERIAL PRIMARY KEY,
                    goal_key TEXT NOT NULL,
                    match_id BIGINT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
                    team_id BIGINT,
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
                    match_id BIGINT PRIMARY KEY REFERENCES matches(match_id) ON DELETE CASCADE,
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


def fetch_finished_matches(
    engine: Engine,
    match_id: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
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
            away_score_for_prediction,
            thesportsdb_event_id
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


def fetch_event_detail(event_id: str) -> dict[str, Any] | None:
    data = api_get("lookupevent.php", {"id": event_id})
    events = data.get("events") or []

    if not events:
        return None

    return events[0]


def fetch_timeline(event_id: str) -> list[dict[str, Any]]:
    data = api_get("lookuptimeline.php", {"id": event_id})
    return data.get("timeline") or []


def find_tsdb_event(
    match: dict[str, Any],
    season_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    local_home = normalize_team_name(match.get("home_team_name"))
    local_away = normalize_team_name(match.get("away_team_name"))
    local_date = parse_date(match.get("kickoff_date_vietnam")) or parse_date(match.get("kickoff_time_utc"))

    local_home_score = parse_int(match.get("home_score_for_prediction"))
    local_away_score = parse_int(match.get("away_score_for_prediction"))

    candidates = []

    for event in season_events:
        event_home = normalize_team_name(event.get("strHomeTeam"))
        event_away = normalize_team_name(event.get("strAwayTeam"))
        event_date = parse_date(event.get("dateEvent"))

        if event_home != local_home or event_away != local_away:
            continue

        if not dates_match(local_date, event_date):
            continue

        event_home_score = parse_int(event.get("intHomeScore"))
        event_away_score = parse_int(event.get("intAwayScore"))

        has_both_scores = all(
            value is not None
            for value in (
                local_home_score,
                local_away_score,
                event_home_score,
                event_away_score,
            )
        )

        if has_both_scores and (
            event_home_score != local_home_score
            or event_away_score != local_away_score
        ):
            continue

        date_distance = 0
        if local_date and event_date:
            date_distance = abs((local_date - event_date).days)

        score_bonus = 0
        if event_home_score == local_home_score:
            score_bonus += 1
        if event_away_score == local_away_score:
            score_bonus += 1

        candidates.append((score_bonus, -date_distance, event))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def validate_event_score(match: dict[str, Any], event: dict[str, Any]) -> str | None:
    local_home_score = parse_int(match.get("home_score_for_prediction"))
    local_away_score = parse_int(match.get("away_score_for_prediction"))
    event_home_score = parse_int(event.get("intHomeScore"))
    event_away_score = parse_int(event.get("intAwayScore"))

    values = (
        local_home_score,
        local_away_score,
        event_home_score,
        event_away_score,
    )

    if any(value is None for value in values):
        return None

    if local_home_score == event_home_score and local_away_score == event_away_score:
        return None

    return (
        f"TheSportsDB score {event_home_score}-{event_away_score} "
        f"does not match Supabase score {local_home_score}-{local_away_score}."
    )


def clean_player_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def format_minute(value: Any) -> str:
    value = str(value or "").strip()
    value = value.replace("`", "'").replace("’", "'")
    value = value.replace("'", "").strip()

    if not value:
        return ""

    return f"{value}'"


def goal_sort_value(minute: str) -> int:
    raw = minute.replace("'", "").strip()

    if "+" in raw:
        base, _, extra = raw.partition("+")
        return (parse_int(base) or 0) * 100 + (parse_int(extra) or 0)

    return (parse_int(raw) or 0) * 100


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")

    return value[:50] or "goal"


def parse_goal_events(
    match: dict[str, Any],
    event: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    local_home = normalize_team_name(match.get("home_team_name"))
    local_away = normalize_team_name(match.get("away_team_name"))
    event_home = normalize_team_name(event.get("strHomeTeam"))
    event_away = normalize_team_name(event.get("strAwayTeam"))

    goals = []

    for row in timeline:
        timeline_type = str(row.get("strTimeline") or "").strip().lower()
        if timeline_type != "goal":
            continue

        player_name = clean_player_name(row.get("strPlayer"))
        if not player_name:
            continue

        tsdb_team = normalize_team_name(row.get("strTeam"))
        detail = str(row.get("strTimelineDetail") or "").strip().lower()

        if tsdb_team in {local_home, event_home}:
            team_side = "home"
            team_id = match.get("home_team_id")
            team_name = match.get("home_team_name")
        elif tsdb_team in {local_away, event_away}:
            team_side = "away"
            team_id = match.get("away_team_id")
            team_name = match.get("away_team_name")
        else:
            print(
                "SKIP goal row because strTeam cannot map:",
                row.get("strTeam"),
                player_name,
            )
            continue

        minute = format_minute(row.get("intTime"))
        is_penalty = "penalty" in detail
        is_own_goal = "own goal" in detail

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

    goals.sort(
        key=lambda goal: (
            goal["sort_value"],
            goal["team_side"],
            goal["player_name"],
        )
    )

    for index, goal in enumerate(goals, start=1):
        goal["goal_key"] = (
            f"{goal['sort_value']:05d}_"
            f"{index:02d}_"
            f"{goal['team_side']}_"
            f"{slugify(goal['player_name'])}"
        )

    return goals


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
                    "goal_key": goal["goal_key"],
                    "match_id": match_id,
                    "team_id": goal["team_id"],
                    "team_name": goal["team_name"],
                    "team_side": goal["team_side"],
                    "player_name": goal["player_name"],
                    "minute": goal["minute"],
                    "is_penalty": goal["is_penalty"],
                    "is_own_goal": goal["is_own_goal"],
                },
            )


def upsert_sync_status(
    engine: Engine,
    match_id: int,
    event_id: str | None,
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
                    :event_id,
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
                "event_id": event_id,
                "status": status,
                "expected_goals": expected_goals,
                "fetched_goals": fetched_goals,
                "message": message[:1000],
            },
        )


def update_match_event_id(engine: Engine, match_id: int, event_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE matches
                SET thesportsdb_event_id = :event_id
                WHERE match_id = :match_id
                """
            ),
            {
                "match_id": match_id,
                "event_id": event_id,
            },
        )


def sync_one_match(
    engine: Engine,
    match: dict[str, Any],
    season_events: list[dict[str, Any]],
    dry_run: bool,
    forced_event_id: str | None = None,
) -> str:
    match_id = int(match["match_id"])
    label = f"{match_id} | {match.get('home_team_name')} vs {match.get('away_team_name')}"

    expected_goals = (parse_int(match.get("home_score_for_prediction")) or 0) + (
        parse_int(match.get("away_score_for_prediction")) or 0
    )

    if expected_goals == 0:
        if not dry_run:
            replace_match_goals(engine, match_id, [])
            upsert_sync_status(
                engine,
                match_id,
                None,
                "synced_zero_zero",
                0,
                0,
                "0-0 match, no scorers.",
            )
        return f"OK {label}: 0-0, cleared scorers."

    event_id = str(forced_event_id or match.get("thesportsdb_event_id") or "").strip()

    if event_id:
        event = fetch_event_detail(event_id)
        if not event:
            message = f"TheSportsDB lookupevent returned no event for idEvent={event_id}."
            if not dry_run:
                upsert_sync_status(
                    engine,
                    match_id,
                    event_id,
                    "event_detail_not_found",
                    expected_goals,
                    0,
                    message,
                )
            return f"MISS {label}: {message}"

        if forced_event_id and not dry_run:
            update_match_event_id(engine, match_id, event_id)
    else:
        event = find_tsdb_event(match, season_events)
        if not event:
            message = "Could not find matching TheSportsDB event."
            if not dry_run:
                upsert_sync_status(
                    engine,
                    match_id,
                    None,
                    "event_not_found",
                    expected_goals,
                    0,
                    message,
                )
            return f"MISS {label}: {message}"

        event_id = str(event.get("idEvent") or "").strip()

        if event_id and not dry_run:
            update_match_event_id(engine, match_id, event_id)

    score_error = validate_event_score(match, event)
    if score_error:
        if not dry_run:
            upsert_sync_status(
                engine,
                match_id,
                event_id,
                "event_score_mismatch",
                expected_goals,
                0,
                score_error,
            )
        return f"WARN {label}: {score_error}"

    timeline = fetch_timeline(event_id)
    goals = parse_goal_events(match, event, timeline)
    fetched_goals = len(goals)

    if fetched_goals != expected_goals and not WRITE_PARTIAL_SCORERS:
        message = (
            f"Fetched {fetched_goals} goal events but match score expects {expected_goals}. "
            "Skipped writing to avoid incomplete scorer display."
        )
        if not dry_run:
            upsert_sync_status(
                engine,
                match_id,
                event_id,
                "goal_count_mismatch",
                expected_goals,
                fetched_goals,
                message,
            )
        return f"WARN {label}: {message}"

    status = "synced"
    message = "Scorers synced successfully."

    if fetched_goals != expected_goals:
        status = "synced_partial"
        message = f"Partial sync allowed: fetched {fetched_goals}, expected {expected_goals}."

    if not dry_run:
        replace_match_goals(engine, match_id, goals)
        upsert_sync_status(
            engine,
            match_id,
            event_id,
            status,
            expected_goals,
            fetched_goals,
            message,
        )

    display_goals = ", ".join(
        f"{goal['player_name']} {goal['minute']}".strip()
        + (" (OG)" if goal["is_own_goal"] else "")
        + (" (P)" if goal["is_penalty"] else "")
        for goal in goals
    )

    return f"OK {label}: {status} from event {event_id} -> {display_goals}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync EPL goal scorers from TheSportsDB into Supabase."
    )
    parser.add_argument("--match-id", type=int, default=None)
    parser.add_argument("--event-id", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.event_id and args.match_id is None:
        raise SystemExit("--event-id requires --match-id.")

    engine = get_engine()
    ensure_tables(engine)

    matches = fetch_finished_matches(
        engine,
        match_id=args.match_id,
        limit=args.limit,
    )

    if not matches:
        print("No finished matches found.")
        return 0

    needs_season_events = False
    if not args.event_id:
        needs_season_events = any(
            not str(match.get("thesportsdb_event_id") or "").strip()
            for match in matches
        )

    season_events: list[dict[str, Any]] = []

    print(
        f"TheSportsDB league={THESPORTSDB_LEAGUE_ID}, "
        f"season={THESPORTSDB_SEASON}, "
        f"dry_run={args.dry_run}, "
        f"partial={WRITE_PARTIAL_SCORERS}"
    )

    if needs_season_events:
        season_events = load_season_events()
        print(f"Loaded {len(season_events)} TheSportsDB season events.")

    results = []

    for match in matches:
        try:
            forced_event_id = None
            if args.event_id and int(match["match_id"]) == args.match_id:
                forced_event_id = args.event_id.strip()

            result = sync_one_match(
                engine=engine,
                match=match,
                season_events=season_events,
                dry_run=args.dry_run,
                forced_event_id=forced_event_id,
            )
            results.append(result)
        except Exception as exc:
            match_id = int(match["match_id"])
            expected_goals = (parse_int(match.get("home_score_for_prediction")) or 0) + (
                parse_int(match.get("away_score_for_prediction")) or 0
            )
            message = f"{type(exc).__name__}: {exc}"

            if not args.dry_run:
                upsert_sync_status(
                    engine,
                    match_id,
                    None,
                    "error",
                    expected_goals,
                    0,
                    message,
                )

            results.append(f"ERR {match_id}: {message}")

        time.sleep(REQUEST_SLEEP_SECONDS)

    for result in results:
        print(result)

    warnings = [
        result
        for result in results
        if result.startswith(("WARN", "MISS", "ERR"))
    ]

    print(f"Done. processed={len(results)}, warnings={len(warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
