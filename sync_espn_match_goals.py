#!/usr/bin/env python3
"""
Sync Premier League goal scorers from ESPN into public.match_goals.

Designed for GitHub Actions:
  DATABASE_URL="postgresql://..." python sync_espn_match_goals.py --write

Dependencies:
  pip install requests sqlalchemy psycopg2-binary
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine


ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1"
VN_TZ = ZoneInfo("Asia/Bangkok")

MATCHES_TABLE = "public.matches"
GOALS_TABLE = "public.match_goals"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EPLPredictionArenaBot/1.0)",
    "Accept": "application/json",
}

TEAM_ALIASES = {
    "manchester united": "man united",
    "man utd": "man united",
    "manchester city": "man city",
    "tottenham hotspur": "tottenham",
    "spurs": "tottenham",
    "wolverhampton wanderers": "wolves",
    "wolverhampton": "wolves",
    "brighton and hove albion": "brighton",
    "newcastle united": "newcastle",
    "west ham united": "west ham",
    "leeds united": "leeds",
    "afc bournemouth": "bournemouth",
    "bournemouth": "bournemouth",
    "nottingham forest": "nottingham forest",
}


@dataclass(frozen=True)
class MatchMeta:
    espn_event_id: str
    match_date_vn: str
    raw_name: str | None
    home_team_name: str
    away_team_name: str
    home_espn_team_id: str
    away_espn_team_id: str
    home_score: int
    away_score: int


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def normalize_database_url(database_url: str) -> str:
    url = database_url.strip()
    if not url:
        raise RuntimeError("DATABASE_URL is empty.")

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    if "sslmode=" not in url:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}sslmode=require"

    return url


def build_engine(database_url: str) -> Engine:
    return create_engine(
        normalize_database_url(database_url),
        pool_pre_ping=True,
        future=True,
    )


def espn_get(path: str, params: dict[str, Any] | None = None, retries: int = 3) -> dict[str, Any]:
    url = f"{ESPN_BASE_URL}/{path.lstrip('/')}"
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                params=params or {},
                timeout=30,
            )
            response.raise_for_status()
            time.sleep(0.35)
            return response.json()
        except Exception as exc:  # noqa: BLE001 - log and retry network/API errors.
            last_error = exc
            logging.warning("ESPN request failed, attempt %s/%s: %s", attempt, retries, exc)
            time.sleep(1.2 * attempt)

    raise RuntimeError(f"ESPN request failed: {url} params={params} error={last_error}")


def fetch_scoreboard(date_yyyymmdd: str) -> dict[str, Any]:
    return espn_get("scoreboard", {"dates": date_yyyymmdd, "limit": 1000})


def fetch_summary(event_id: str) -> dict[str, Any]:
    return espn_get("summary", {"event": event_id})


def yyyymmdd_to_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y%m%d").date()


def date_to_yyyymmdd(value: dt.date) -> str:
    return value.strftime("%Y%m%d")


def parse_iso_date_to_yyyymmdd(value: str) -> str:
    return dt.datetime.strptime(value, "%Y-%m-%d").strftime("%Y%m%d")


def iter_date_range(start_date: str, end_date: str) -> list[str]:
    start = dt.datetime.strptime(start_date, "%Y-%m-%d").date()
    end = dt.datetime.strptime(end_date, "%Y-%m-%d").date()

    if end < start:
        raise RuntimeError("--end-date must be greater than or equal to --start-date.")

    days = []
    current = start
    while current <= end:
        days.append(date_to_yyyymmdd(current))
        current += dt.timedelta(days=1)

    return days


def get_calendar_dates(seed_date: str) -> list[str]:
    data = fetch_scoreboard(seed_date)
    leagues = data.get("leagues") or []
    if not leagues:
        raise RuntimeError("ESPN scoreboard response does not contain leagues/calendar.")

    league = leagues[0]
    calendar = league.get("calendar") or []

    logging.info("League: %s", league.get("name"))
    logging.info("Season: %s", (league.get("season") or {}).get("displayName"))

    dates = sorted({str(item)[:10].replace("-", "") for item in calendar if item})
    if not dates:
        raise RuntimeError("ESPN calendar is empty.")

    return dates


def resolve_dates(args: argparse.Namespace) -> list[str]:
    if args.dates:
        return sorted({parse_iso_date_to_yyyymmdd(part.strip()) for part in args.dates.split(",") if part.strip()})

    if args.start_date or args.end_date:
        if not args.start_date or not args.end_date:
            raise RuntimeError("Use both --start-date and --end-date.")
        return iter_date_range(args.start_date, args.end_date)

    dates = get_calendar_dates(args.seed_date)

    if args.recent_days is not None:
        today = dt.datetime.now(VN_TZ).date()
        cutoff = today - dt.timedelta(days=args.recent_days)
        dates = [
            value
            for value in dates
            if cutoff <= yyyymmdd_to_date(value) <= today
        ]

    return dates


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text_value = str(value).strip().lower()
    text_value = unicodedata.normalize("NFKD", text_value)
    text_value = "".join(ch for ch in text_value if not unicodedata.combining(ch))
    text_value = text_value.replace("&", "and")
    text_value = re.sub(r"\b(fc|afc|football club)\b", "", text_value)
    text_value = re.sub(r"[^a-z0-9]+", " ", text_value)
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return text_value


def normalize_team_name(name: Any) -> str:
    cleaned = clean_text(name)
    return TEAM_ALIASES.get(cleaned, cleaned)


def parse_db_date(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, dt.datetime):
        return value.date().isoformat()

    if isinstance(value, dt.date):
        return value.isoformat()

    text_value = str(value).strip()
    if not text_value:
        return None

    try:
        return dt.date.fromisoformat(text_value[:10]).isoformat()
    except ValueError:
        return text_value[:10]


def ensure_match_goals_table(engine: Engine) -> None:
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

    with engine.begin() as conn:
        conn.execute(ddl)

    logging.info("Ensured table %s exists.", GOALS_TABLE)


def load_db_matches(engine: Engine) -> list[dict[str, Any]]:
    query = text(
        f"""
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
        FROM {MATCHES_TABLE}
        """
    )

    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(query).mappings()]

    for row in rows:
        row["_kickoff_date_key"] = parse_db_date(row.get("kickoff_date_vietnam"))
        row["_home_key"] = normalize_team_name(row.get("home_team_name"))
        row["_away_key"] = normalize_team_name(row.get("away_team_name"))
        row["_source_match_id_key"] = str(row.get("source_match_id") or "").strip()

    logging.info("Loaded %s DB matches.", len(rows))
    return rows


def get_competitors(event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    competitions = event.get("competitions") or []
    if not competitions:
        raise RuntimeError(f"Event {event.get('id')} has no competitions.")

    competitors = competitions[0].get("competitors") or []
    home = next((item for item in competitors if item.get("homeAway") == "home"), None)
    away = next((item for item in competitors if item.get("homeAway") == "away"), None)

    if not home or not away:
        raise RuntimeError(f"Event {event.get('id')} missing home/away competitors.")

    return home, away


def get_match_meta(event: dict[str, Any]) -> MatchMeta:
    home, away = get_competitors(event)

    event_date_raw = event.get("date")
    if not event_date_raw:
        raise RuntimeError(f"Event {event.get('id')} missing date.")

    event_datetime_utc = dt.datetime.fromisoformat(event_date_raw.replace("Z", "+00:00"))
    event_date_vn = event_datetime_utc.astimezone(VN_TZ).date().isoformat()

    home_team = home.get("team") or {}
    away_team = away.get("team") or {}

    return MatchMeta(
        espn_event_id=str(event.get("id")),
        match_date_vn=event_date_vn,
        raw_name=event.get("name"),
        home_team_name=str(home_team.get("displayName") or home_team.get("name") or ""),
        away_team_name=str(away_team.get("displayName") or away_team.get("name") or ""),
        home_espn_team_id=str(home_team.get("id")),
        away_espn_team_id=str(away_team.get("id")),
        home_score=int(home.get("score") or 0),
        away_score=int(away.get("score") or 0),
    )


def find_db_match(meta: MatchMeta, db_matches: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    by_source_id = [
        row
        for row in db_matches
        if row["_source_match_id_key"] == meta.espn_event_id
    ]
    if len(by_source_id) == 1:
        return by_source_id[0], "source_match_id"

    home_key = normalize_team_name(meta.home_team_name)
    away_key = normalize_team_name(meta.away_team_name)
    by_date_and_teams = [
        row
        for row in db_matches
        if row["_kickoff_date_key"] == meta.match_date_vn
        and row["_home_key"] == home_key
        and row["_away_key"] == away_key
    ]

    if len(by_date_and_teams) == 1:
        return by_date_and_teams[0], "date_and_teams"

    if len(by_date_and_teams) > 1:
        return None, f"ambiguous:{len(by_date_and_teams)}"

    return None, "unmatched"


def is_completed_event(event: dict[str, Any]) -> bool:
    status_type = ((event.get("status") or {}).get("type") or {})
    return bool(status_type.get("completed"))


def is_goal_event(item: dict[str, Any]) -> bool:
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


def parse_goal_minute(value: Any) -> str | None:
    if value is None:
        return None

    minute = str(value).strip()
    if not minute:
        return None

    minute = minute.replace("'", "").replace("’", "").replace("′", "")
    minute = re.sub(r"\s+", "", minute)

    return f"{minute}'"


def detect_goal_flags(item: dict[str, Any]) -> tuple[bool, bool]:
    type_text = str((item.get("type") or {}).get("text", "")).lower()
    event_text = str(item.get("text", "")).lower()
    short_text = str(item.get("shortText", "")).lower()
    full_text = f"{type_text} {event_text} {short_text}"

    is_own_goal = bool(item.get("ownGoal")) or "own goal" in full_text
    is_penalty = bool(item.get("penaltyKick")) or "penalty - scored" in full_text

    return is_penalty, is_own_goal


def get_player_name(item: dict[str, Any]) -> str:
    participants = item.get("participants") or []
    for participant in participants:
        athlete = participant.get("athlete") or {}
        name = athlete.get("displayName") or athlete.get("shortName")
        if name:
            return str(name).strip()

    text_value = str(item.get("text") or item.get("shortText") or "").strip()
    fallback = text_value.split("(")[0].strip()
    return fallback or "Unknown"


def parse_goals_for_match(
    event: dict[str, Any],
    db_match: dict[str, Any],
    meta: MatchMeta,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    summary = fetch_summary(meta.espn_event_id)
    rows: list[dict[str, Any]] = []
    side_counts = {"home": 0, "away": 0}

    for item in summary.get("keyEvents") or []:
        if not is_goal_event(item):
            continue

        team = item.get("team") or {}
        espn_team_id = str(team.get("id")) if team.get("id") is not None else None

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
        goal_key = f"espn:{meta.espn_event_id}:{source_event_id or fallback_goal_index}"
        is_penalty, is_own_goal = detect_goal_flags(item)

        rows.append(
            {
                "goal_key": goal_key,
                "match_id": int(db_match["match_id"]),
                "team_id": int(team_id) if team_id is not None else None,
                "team_name": str(team_name),
                "team_side": team_side,
                "player_name": get_player_name(item),
                "minute": parse_goal_minute((item.get("clock") or {}).get("displayValue")),
                "is_penalty": is_penalty,
                "is_own_goal": is_own_goal,
            }
        )

    expected_total = meta.home_score + meta.away_score
    if len(rows) == expected_total:
        return rows, None

    return rows, {
        "source_match_id": meta.espn_event_id,
        "match_id": db_match.get("match_id"),
        "match": meta.raw_name,
        "score": f"{meta.home_score}-{meta.away_score}",
        "expected_goals": expected_total,
        "parsed_goals": len(rows),
        "home_parsed": side_counts["home"],
        "away_parsed": side_counts["away"],
    }


def crawl_match_goals(
    engine: Engine,
    dates: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    db_matches = load_db_matches(engine)
    all_goal_rows: list[dict[str, Any]] = []
    matched_matches: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []

    for index, date_yyyymmdd in enumerate(dates, start=1):
        logging.info("Fetching scoreboard %s/%s: %s", index, len(dates), date_yyyymmdd)
        scoreboard = fetch_scoreboard(date_yyyymmdd)

        for event in scoreboard.get("events") or []:
            if not is_completed_event(event):
                continue

            meta = get_match_meta(event)
            db_match, match_method = find_db_match(meta, db_matches)

            if db_match is None:
                unmatched.append(
                    {
                        "espn_event_id": meta.espn_event_id,
                        "match_date_vn": meta.match_date_vn,
                        "home_team": meta.home_team_name,
                        "away_team": meta.away_team_name,
                        "score": f"{meta.home_score}-{meta.away_score}",
                        "reason": match_method,
                    }
                )
                continue

            matched_matches.append(
                {
                    "match_id": int(db_match["match_id"]),
                    "source_match_id": str(db_match.get("source_match_id") or ""),
                    "espn_event_id": meta.espn_event_id,
                    "home_score": meta.home_score,
                    "away_score": meta.away_score,
                    "home_team_id": db_match.get("home_team_id"),
                    "home_team_name": db_match.get("home_team_name"),
                    "away_team_id": db_match.get("away_team_id"),
                    "away_team_name": db_match.get("away_team_name"),
                    "match_method": match_method,
                }
            )

            goal_rows, problem = parse_goals_for_match(event, db_match, meta)
            all_goal_rows.extend(goal_rows)

            if problem:
                problems.append(problem)

    return all_goal_rows, matched_matches, unmatched, problems


def write_match_goals(
    engine: Engine,
    goal_rows: list[dict[str, Any]],
    matched_matches: list[dict[str, Any]],
    update_matches: bool,
    backfill_source_match_id: bool,
) -> None:
    matched_by_id = {int(row["match_id"]): row for row in matched_matches}
    match_ids = sorted(matched_by_id)

    if not match_ids:
        logging.info("No completed matched DB matches to write.")
        return

    with engine.begin() as conn:
        delete_stmt = text(
            f"""
            DELETE FROM {GOALS_TABLE}
            WHERE match_id IN :match_ids
            """
        ).bindparams(bindparam("match_ids", expanding=True))

        conn.execute(delete_stmt, {"match_ids": match_ids})

        if goal_rows:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {GOALS_TABLE} (
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

        if update_matches:
            for match in matched_by_id.values():
                winner_team_id = None
                winner_team_name = None
                if match["home_score"] > match["away_score"]:
                    winner_team_id = match.get("home_team_id")
                    winner_team_name = match.get("home_team_name")
                elif match["away_score"] > match["home_score"]:
                    winner_team_id = match.get("away_team_id")
                    winner_team_name = match.get("away_team_name")

                update_sql = f"""
                    UPDATE {MATCHES_TABLE}
                    SET
                        score_ft_home = :home_score,
                        score_ft_away = :away_score,
                        home_score_for_prediction = :home_score,
                        away_score_for_prediction = :away_score,
                        is_finished = TRUE,
                        winner_team_id = :winner_team_id,
                        winner_team_name = :winner_team_name
                """

                params = {
                    "match_id": int(match["match_id"]),
                    "home_score": int(match["home_score"]),
                    "away_score": int(match["away_score"]),
                    "winner_team_id": int(winner_team_id) if winner_team_id is not None else None,
                    "winner_team_name": winner_team_name,
                    "espn_event_id": str(match["espn_event_id"]),
                }

                if backfill_source_match_id:
                    update_sql += ", source_match_id = :espn_event_id"

                update_sql += " WHERE match_id = :match_id"
                conn.execute(text(update_sql), params)

    logging.info("Deleted/replaced goals for %s matches.", len(match_ids))
    logging.info("Inserted %s goal rows.", len(goal_rows))


def print_report(
    goal_rows: list[dict[str, Any]],
    matched_matches: list[dict[str, Any]],
    unmatched: list[dict[str, Any]],
    problems: list[dict[str, Any]],
) -> None:
    logging.info("Matched completed matches: %s", len(matched_matches))
    logging.info("Goal rows parsed: %s", len(goal_rows))
    logging.info("Unmatched completed matches: %s", len(unmatched))
    logging.info("Problem matches: %s", len(problems))

    if unmatched:
        logging.error("Unmatched completed matches:")
        for row in unmatched[:30]:
            logging.error("  %s", row)
        if len(unmatched) > 30:
            logging.error("  ... and %s more", len(unmatched) - 30)

    if problems:
        logging.error("Matches with goal count mismatch:")
        for row in problems[:30]:
            logging.error("  %s", row)
        if len(problems) > 30:
            logging.error("  ... and %s more", len(problems) - 30)

    if goal_rows:
        logging.info("First parsed goals:")
        for row in goal_rows[:10]:
            logging.info("  %s", row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync ESPN Premier League goal events into public.match_goals."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="Postgres/Supabase URL. Defaults to DATABASE_URL env var.",
    )
    parser.add_argument(
        "--seed-date",
        default=os.getenv("ESPN_SEASON_SEED_DATE", "20260524"),
        help="YYYYMMDD date inside the target ESPN season. Used to read the season calendar.",
    )
    parser.add_argument(
        "--dates",
        default=os.getenv("SYNC_DATES"),
        help="Comma-separated ISO dates, e.g. 2026-07-20,2026-07-21.",
    )
    parser.add_argument("--start-date", help="ISO date YYYY-MM-DD. Use with --end-date.")
    parser.add_argument("--end-date", help="ISO date YYYY-MM-DD. Use with --start-date.")
    parser.add_argument(
        "--recent-days",
        type=int,
        default=None,
        help="Only crawl ESPN calendar dates from today minus N days through today.",
    )
    parser.add_argument(
        "--create-table",
        action="store_true",
        help="Create public.match_goals if it does not exist.",
    )
    parser.add_argument(
        "--update-matches",
        action="store_true",
        help="Also update public.matches scores, is_finished, and winner fields.",
    )
    parser.add_argument(
        "--backfill-source-match-id",
        action="store_true",
        help="When --update-matches is enabled, overwrite source_match_id with ESPN event id.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually write to DB. Without this flag, the script only dry-runs.",
    )
    parser.add_argument(
        "--allow-unmatched",
        action="store_true",
        help="Do not fail when completed ESPN matches cannot map to DB matches.",
    )
    parser.add_argument(
        "--allow-problems",
        action="store_true",
        help="Do not fail when parsed goal count differs from ESPN final score.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Do not fail when no completed DB matches are found.",
    )
    return parser.parse_args()


def main() -> int:
    setup_logging()
    args = parse_args()

    if not args.database_url:
        logging.error("Missing DATABASE_URL. Set a GitHub secret named DATABASE_URL.")
        return 2

    try:
        dates = resolve_dates(args)
        logging.info("Resolved %s ESPN date(s).", len(dates))

        engine = build_engine(args.database_url)

        if args.create_table:
            ensure_match_goals_table(engine)

        goal_rows, matched_matches, unmatched, problems = crawl_match_goals(engine, dates)
        print_report(goal_rows, matched_matches, unmatched, problems)

        if unmatched and not args.allow_unmatched:
            logging.error("Stopping because unmatched matches exist.")
            return 1

        if problems and not args.allow_problems:
            logging.error("Stopping because goal count problems exist.")
            return 1

        if not matched_matches and not args.allow_empty:
            logging.error("Stopping because no completed DB matches were matched.")
            return 1

        if not args.write:
            logging.info("Dry run only. Add --write to write to database.")
            return 0

        write_match_goals(
            engine=engine,
            goal_rows=goal_rows,
            matched_matches=matched_matches,
            update_matches=args.update_matches,
            backfill_source_match_id=args.backfill_source_match_id,
        )
        logging.info("Sync completed successfully.")
        return 0

    except Exception as exc:  # noqa: BLE001 - CLI entrypoint should log any fatal error.
        logging.exception("Sync failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
