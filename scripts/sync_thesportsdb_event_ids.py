import argparse
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any

import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
THESPORTSDB_API_KEY = os.getenv("THESPORTSDB_API_KEY", "123").strip() or "123"
THESPORTSDB_LEAGUE_ID = os.getenv("THESPORTSDB_LEAGUE_ID", "4328").strip() or "4328"
THESPORTSDB_SEASON = os.getenv("THESPORTSDB_SEASON", "2025-2026").strip() or "2025-2026"
EPL_SEASON_SLUG = os.getenv("EPL_SEASON_SLUG", "2025-26").strip() or "2025-26"
REQUEST_SLEEP_SECONDS = float(os.getenv("THESPORTSDB_REQUEST_SLEEP_SECONDS", "2.1"))

BASE_URL = f"https://www.thesportsdb.com/api/v1/json/{THESPORTSDB_API_KEY}"


TEAM_ALIASES = {
    "afc bournemouth": "bournemouth",
    "bournemouth": "bournemouth",
    "brighton hove albion": "brighton",
    "brighton and hove albion": "brighton",
    "brighton": "brighton",
    "burnley": "burnley",
    "chelsea": "chelsea",
    "coventry city": "coventry city",
    "crystal palace": "crystal palace",
    "everton": "everton",
    "fulham": "fulham",
    "leeds": "leeds united",
    "leeds united": "leeds united",
    "liverpool": "liverpool",
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
    "sunderland": "sunderland",
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


def parse_date(value: Any) -> date | None:
    if value is None:
        return None

    text_value = str(value).strip()
    if not text_value:
        return None

    try:
        return datetime.fromisoformat(text_value.replace("Z", "+00:00")).date()
    except ValueError:
        pass

    try:
        return datetime.strptime(text_value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def get_engine() -> Engine:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing.")

    return create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        connect_args={"connect_timeout": 20},
    )


def api_get(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(
        f"{BASE_URL}/{endpoint}",
        params=params or {},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def ensure_schema(engine: Engine) -> None:
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


def fetch_matches_to_map(
    engine: Engine,
    match_id: int | None,
    remap_all: bool,
    limit: int | None,
) -> list[dict[str, Any]]:
    where_parts = [
        "source_match_id LIKE :season_filter",
    ]
    params: dict[str, Any] = {
        "season_filter": f"epl|{EPL_SEASON_SLUG}|%",
    }

    if not remap_all:
        where_parts.append("thesportsdb_event_id IS NULL")

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
            source_match_id,
            kickoff_date_vietnam,
            kickoff_time_utc,
            home_team_name,
            away_team_name,
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


def index_events(events: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    indexed: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for event in events:
        home_name = normalize_team_name(event.get("strHomeTeam"))
        away_name = normalize_team_name(event.get("strAwayTeam"))
        if not home_name or not away_name:
            continue

        indexed.setdefault((home_name, away_name), []).append(event)

    return indexed


def find_event_for_match(
    match: dict[str, Any],
    indexed_events: dict[tuple[str, str], list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str]:
    home_name = normalize_team_name(match.get("home_team_name"))
    away_name = normalize_team_name(match.get("away_team_name"))
    match_date = parse_date(match.get("kickoff_date_vietnam")) or parse_date(match.get("kickoff_time_utc"))

    candidates = indexed_events.get((home_name, away_name), [])
    if not candidates:
        return None, "no_team_pair_match"

    scored_candidates = []
    for event in candidates:
        event_date = parse_date(event.get("dateEvent"))
        if not match_date or not event_date:
            date_distance = 99
        else:
            date_distance = abs((match_date - event_date).days)

        if date_distance > 1:
            continue

        scored_candidates.append((date_distance, str(event.get("idEvent") or ""), event))

    if not scored_candidates:
        return None, "team_pair_found_but_date_mismatch"

    scored_candidates.sort(key=lambda item: (item[0], item[1]))

    best_distance = scored_candidates[0][0]
    same_best = [item for item in scored_candidates if item[0] == best_distance]
    if len(same_best) > 1:
        return None, "ambiguous_candidates"

    return scored_candidates[0][2], "matched"


def update_mapping(engine: Engine, match_id: int, event_id: str) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Map Supabase EPL matches to TheSportsDB idEvent.")
    parser.add_argument("--match-id", type=int, default=None, help="Only map one Supabase matches.match_id.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of Supabase matches processed.")
    parser.add_argument("--all", action="store_true", help="Remap all matches in the selected season, including already mapped rows.")
    parser.add_argument("--dry-run", action="store_true", help="Validate mapping without writing to Supabase.")
    args = parser.parse_args()

    engine = get_engine()
    ensure_schema(engine)

    matches = fetch_matches_to_map(
        engine=engine,
        match_id=args.match_id,
        remap_all=args.all,
        limit=args.limit,
    )

    if not matches:
        print("No matches need TheSportsDB mapping.")
        return 0

    print(
        f"Loading TheSportsDB season events: league={THESPORTSDB_LEAGUE_ID}, "
        f"season={THESPORTSDB_SEASON}, dry_run={args.dry_run}"
    )

    events = load_season_events()
    print(f"Loaded {len(events)} TheSportsDB events.")

    if not events:
        print("No TheSportsDB season events returned.")
        return 1

    indexed_events = index_events(events)
    matched_count = 0
    missed_count = 0

    for match in matches:
        event, reason = find_event_for_match(match, indexed_events)
        label = f"{match['match_id']} | {match['home_team_name']} vs {match['away_team_name']}"

        if not event:
            missed_count += 1
            print(f"MISS {label}: {reason}")
            continue

        event_id = str(event.get("idEvent") or "").strip()
        if not event_id:
            missed_count += 1
            print(f"MISS {label}: missing idEvent")
            continue

        matched_count += 1
        event_label = f"{event.get('dateEvent')} | {event.get('strHomeTeam')} vs {event.get('strAwayTeam')}"
        print(f"MAP  {label} -> {event_id} | {event_label}")

        if not args.dry_run:
            update_mapping(engine, int(match["match_id"]), event_id)

        time.sleep(REQUEST_SLEEP_SECONDS)

    print(f"Done. matched={matched_count}, missed={missed_count}, dry_run={args.dry_run}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
