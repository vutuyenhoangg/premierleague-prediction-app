from __future__ import annotations
from pathlib import Path
import hashlib
import json
import os
import re
import time
import unicodedata
from collections import Counter, defaultdict
import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from sqlalchemy import (
    MetaData,
    Table,
    and_,
    bindparam,
    case,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool


# ============================================================
# CHANGELOG (v2 — xem lịch sử fix trong PR/issue liên quan)
# ============================================================
# 1. FIX GỐC: "source_match_id" (khoá tự nhiên của 1 trận) trước đây
#    nhúng NGÀY thi đấu vào (vd "2026-08-21|arsenal|coventry city").
#    Hệ quả: mỗi khi lịch thi đấu bị dời ngày/giờ (rất thường xuyên với
#    Premier League vì lịch TV, cúp châu Âu...), source_match_id đổi
#    -> match_id (hash từ source_match_id) đổi theo -> hệ thống hiểu
#    NHẦM thành 1 trận hoàn toàn mới, trong khi dòng cũ (ngày cũ) vẫn
#    còn trong DB -> trùng lặp dữ liệu / vi phạm unique constraint.
#
#    SỬA: khoá tự nhiên của 1 trận trong 1 mùa giải Premier League chỉ
#    cần "đội nhà + đội khách" (KHÔNG có ngày) vì đây là giải vòng tròn
#    2 lượt - mỗi cặp đội với đúng vai trò nhà/khách đó CHỈ gặp nhau
#    ĐÚNG 1 LẦN trong cả mùa. Khoá này bất biến bất kể lịch bị dời bao
#    nhiêu lần.
#
# 2. TỰ PHỤC HỒI (self-heal) TỪ DATABASE: trước khi tính match_id mới
#    cho 1 trận, script tra cứu DB xem cặp (home_team_id, away_team_id)
#    trong mùa giải đó đã có match_id nào chưa, và TÁI SỬ DỤNG match_id
#    đó nếu có — bất kể trước đây match_id được tính bằng công thức nào.
#    Nhờ vậy: (a) tự động "chữa lành" dữ liệu cũ bị lỗi ở mục 1 mà không
#    cần chạy SQL tay, (b) miễn nhiễm nếu SEASON_SLUG/công thức hash có
#    vô tình lệch giữa các lần chạy trong tương lai.
#
# 3. Parser chặt hơn: dòng nào trông giống dòng trận đấu (chứa " v "
#    hoặc mẫu "số-số") nhưng không khớp được regex sẽ làm crawl DỪNG
#    LẠI với lỗi rõ ràng, thay vì âm thầm bỏ qua trận đó.
#
# 4. Bắt buộc mỗi trận phải có vòng đấu (Matchday) xác định từ nguồn —
#    bỏ hẳn kiểu suy đoán vòng đấu theo vị trí (silent fallback) vì có
#    thể sai lệch mà không ai biết.
#
# 5. Thêm kiểm tra nội dung tải về không phải trang lỗi (HTML) trước
#    khi parse, và thêm biến môi trường CRAWL_DRY_RUN=1 để chạy thử
#    toàn bộ pipeline (fetch/parse/validate/so khớp DB) mà KHÔNG ghi gì
#    vào database — dùng để kiểm thử an toàn trước khi áp dụng thật.
#
# 6. Toàn bộ việc: tra cứu match_id cũ, tính lại dữ liệu trận, validate,
#    upsert teams/matches, chấm lại prediction — chạy trong ĐÚNG 1
#    transaction duy nhất (atomic): hỏng ở đâu thì rollback sạch, không
#    để lại trạng thái nửa vời.
# ============================================================


COMPETITION_KEY = "epl"
SEASON_SLUG = os.getenv("EPL_SEASON_SLUG", "2026-27").strip()

TARGET_TIMEZONE = "Asia/Ho_Chi_Minh"
SOURCE_TIMEZONE = "Europe/London"

EXPECTED_TEAM_COUNT = 20
EXPECTED_MATCH_COUNT = 380
EXPECTED_MATCHDAYS = set(range(1, 39))
EXPECTED_MATCHES_PER_ROUND = 10
EXPECTED_HOME_AWAY_PER_TEAM = 19  # 20 đội - 1, đá nhà 19 & khách 19 trận/mùa

BASE_DIR = Path(__file__).resolve().parent

TEAM_METADATA_PATH = BASE_DIR / "data" / "epl_team_metadata.json"

REQUEST_TIMEOUT_SECONDS = 30

# Chạy thử toàn bộ pipeline (tải, parse, validate, so khớp DB, tính
# toán thay đổi) nhưng KHÔNG ghi gì vào database. Dùng để kiểm thử an
# toàn: `CRAWL_DRY_RUN=1 python crawl_epl_data_combined.py`
DRY_RUN = os.getenv("CRAWL_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}

MATCH_COLUMNS = [
    "match_id",
    "source_match_id",
    "season_slug",
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

# Các cột dùng để phát hiện & log việc lịch thi đấu (ngày/giờ) bị dời so
# với lần crawl trước — CHỈ dùng để in log cho người vận hành yên tâm là
# thay đổi lịch đã được ghi nhận đúng vào ĐÚNG trận cũ, không ảnh hưởng
# gì đến việc chấm điểm prediction.
KICKOFF_DIAGNOSTIC_COLUMNS = [
    "date_source",
    "time_source",
    "kickoff_time_utc",
]

# Các cột kết quả trận đấu — chỉ cho phép "hạ cấp" is_finished True -> False
# (tức nguồn tạm thời chưa cập nhật kịp) khi trận đó KHÔNG phải đang finished
# trong DB. Nếu DB đang finished mà nguồn báo chưa finished, giữ nguyên toàn
# bộ các cột này — tránh crawl ghi đè NULL lên dữ liệu admin đã sửa tay
# trong lúc chờ nguồn cập nhật.
PROTECTED_RESULT_COLUMNS = {
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
}


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
# Ngưỡng an toàn: file thật của cả mùa EPL luôn > 15KB. Nếu nhỏ hơn hẳn,
# rất có thể đây là trang lỗi (404/5xx) hoặc file rỗng/placeholder chứ
# không phải dữ liệu thật — chặn lại thay vì parse ra 0 trận rồi mới báo
# lỗi khó hiểu ở bước sau.
MIN_EXPECTED_SOURCE_LENGTH = 5000


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
            body = response.text

            stripped = body.strip()

            if len(body) < MIN_EXPECTED_SOURCE_LENGTH:
                raise RuntimeError(
                    f"Nội dung tải về quá ngắn ({len(body)} ký tự, kỳ vọng "
                    f">= {MIN_EXPECTED_SOURCE_LENGTH}). Rất có thể đây là "
                    f"trang lỗi/placeholder chứ không phải dữ liệu thật. "
                    f"URL: {OPENFOOTBALL_URL}"
                )

            if stripped.startswith("<"):
                raise RuntimeError(
                    "Nội dung tải về có vẻ là HTML (trang lỗi GitHub), "
                    f"không phải file text thuần. URL: {OPENFOOTBALL_URL}"
                )

            return body
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
# Mùa đang cập nhật theo tuần (vd 2026-27) LUÔN giữ "v" giữa 2 đội, kể cả khi
# đã có tỉ số — tỉ số được nối thêm SAU tên đội khách, ví dụ:
#   "20:00  Arsenal FC              v Coventry City FC         3-0 (2-0)"
# Thử regex này TRƯỚC vì đặc trưng hơn (bắt buộc có " v " tách 2 đội).
MATCH_WITH_V_RE = re.compile(
    r"^(?:(\d{1,2}:\d{2})\s+)?"
    r"(.+?)\s+v\s+(.+?)"
    r"(?:\s+(\d+)-(\d+)(?:\s*\((\d+)-(\d+)\))?)?"
    r"\s*$"
)

# Các mùa đã hoàn tất, không cập nhật theo tuần (vd 2025-26) KHÔNG giữ "v"
# một khi đã có tỉ số — tỉ số nằm xen giữa 2 tên đội, ví dụ:
#   "19:00   Liverpool  4-2 (1-0)  Bournemouth"
# Chỉ thử regex này khi MATCH_WITH_V_RE không khớp.
MATCH_NO_V_RE = re.compile(
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

# Nếu 1 dòng không khớp MATCH_WITH_V_RE/MATCH_NO_V_RE nhưng "trông giống"
# một dòng trận đấu (có " v " tách 2 đội, hoặc có mẫu tỉ số "số-số"), rất
# có thể định dạng nguồn đã đổi theo cách script chưa xử lý được — DỪNG
# LẠI với lỗi rõ ràng thay vì âm thầm bỏ qua, làm mất trận mà không ai biết.
UNRECOGNIZED_MATCH_HINT_RE = re.compile(r"(?:\bv\b)|(?:\d+-\d+)")


def parse_round_number(round_text: str) -> int | None:
    match = re.search(r"(\d+)\s*$", round_text)
    return int(match.group(1)) if match else None


def infer_year(month: int, season_start_year: int) -> int:
    """Suy luận năm cho 1 dòng ngày KHÔNG ghi rõ năm.

    QUAN TRỌNG: hàm này KHÔNG dựa vào "dòng ngày liền trước" (thứ tự vật
    lý trong file) mà chỉ dựa thuần vào THÁNG + năm bắt đầu mùa giải.
    Lý do: khi 1 trận bị hoãn và đá bù rất trễ, nguồn openfootball lặp
    lại header "▪ Matchday N" ở đúng vị trí (theo ngày đá bù thực tế)
    trong file — đã xác nhận bằng dữ liệu thật mùa 2015-16 (trận vòng 35
    đá bù ngày 2016-05-10, SAU CẢ vòng 37 đã đá ngày 2016-05-08). Nếu suy
    luận năm dựa vào "trạng thái dòng trước" (kiểu last_month/last_year),
    một trận đá bù nằm ở vị trí bất thường trong file có thể làm suy luận
    sai năm. Neo thẳng vào THÁNG là cách duy nhất miễn nhiễm hoàn toàn với
    việc file bị xáo trộn thứ tự do các trận hoãn đá bù.

    Quy ước mùa giải Anh luôn bắt đầu tháng 8 (season_start_year) và kết
    thúc muộn nhất khoảng tháng 7 năm sau (trường hợp cực đoan như mùa
    2019-20 bị hoãn vì COVID, kết thúc tháng 7/2020) -> tháng 8-12 thuộc
    season_start_year, tháng 1-7 thuộc season_start_year + 1.
    """

    return season_start_year if month >= 8 else season_start_year + 1


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

    for line_number, raw_line in enumerate(text_content.splitlines(), start=1):
        line = raw_line.strip()

        if not line or line.startswith("=") or line.startswith("#"):
            continue

        round_match = ROUND_LINE_RE.match(line)
        if round_match:
            flush_pending()
            current_round = parse_round_number(round_match.group(1))
            if current_round is None:
                raise RuntimeError(
                    f"Dòng {line_number}: không đọc được số vòng đấu từ "
                    f"'{line}'. Định dạng nguồn có thể đã thay đổi."
                )
            continue

        date_match = DATE_LINE_RE.match(line)
        if date_match:
            flush_pending()
            month_abbr, day, year_str = date_match.groups()
            month = MONTHS[month_abbr]
            year = (
                int(year_str)
                if year_str
                else infer_year(month, season_start_year)
            )
            current_date = dt.date(year, month, int(day))
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

        # Thử MATCH_WITH_V_RE trước (đặc trưng hơn, bắt buộc có " v ").
        # Nếu không khớp mới thử MATCH_NO_V_RE (định dạng mùa cũ, không có "v"
        # một khi đã có tỉ số).
        match_with_v = MATCH_WITH_V_RE.match(line)
        match_no_v = None if match_with_v else MATCH_NO_V_RE.match(line)

        if (match_with_v or match_no_v) and current_date is not None:
            flush_pending()

            if current_round is None:
                raise RuntimeError(
                    f"Dòng {line_number}: gặp dòng trận đấu '{line}' nhưng "
                    "chưa xác định được vòng đấu (thiếu header '▪ Matchday "
                    "N' phía trước). Không đoán vòng đấu để tránh sai lệch "
                    "âm thầm — hãy kiểm tra lại định dạng file nguồn."
                )

            if match_with_v:
                (
                    time_str,
                    home_name,
                    away_name,
                    home_score,
                    away_score,
                    ht_home,
                    ht_away,
                ) = match_with_v.groups()
            else:
                (
                    time_str,
                    home_name,
                    home_score,
                    away_score,
                    ht_home,
                    ht_away,
                    away_name,
                ) = match_no_v.groups()

            if time_str:
                current_time = time_str

            pending = {
                "round": current_round,
                "date": current_date,
                "time": current_time or "15:00",
                "home_name": home_name.strip(),
                "away_name": away_name.strip(),
                "home_score": int(home_score) if home_score is not None else None,
                "away_score": int(away_score) if away_score is not None else None,
                "ht_home": int(ht_home) if ht_home is not None else None,
                "ht_away": int(ht_away) if ht_away is not None else None,
                "raw_goals": "",
            }
            continue

        # Không khớp round/date/goal-block/match, nhưng "trông giống" một
        # dòng trận đấu (có " v " hoặc mẫu tỉ số) và đang trong lúc đọc
        # danh sách trận (đã có current_date) -> rất có thể là lỗi định
        # dạng chưa xử lý được. Dừng hẳn thay vì âm thầm mất trận.
        if current_date is not None and UNRECOGNIZED_MATCH_HINT_RE.search(line):
            raise RuntimeError(
                f"Dòng {line_number}: '{line}' trông giống dòng trận đấu "
                "nhưng không khớp được với định dạng đã biết "
                "(MATCH_WITH_V_RE / MATCH_NO_V_RE). Định dạng nguồn có thể "
                "đã thay đổi — cần cập nhật regex trước khi chạy tiếp, "
                "tránh làm mất trận một cách âm thầm."
            )

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
    "hull": "hull city",
    "hull city": "hull city",
    "ipswich": "ipswich town",
    "ipswich town": "ipswich town",
    "coventry": "coventry city",
    "coventry city": "coventry city",
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


def build_source_match_id(season_slug: str, home_name: str, away_name: str) -> str:
    """Khoá tự nhiên (bất biến) của 1 trận trong 1 mùa giải: chỉ dựa vào
    đội nhà + đội khách, KHÔNG có ngày thi đấu. Vì Premier League là
    vòng tròn 2 lượt, mỗi cặp (đội nhà, đội khách) chỉ xuất hiện đúng 1
    lần trong cả mùa -> khoá này không bao giờ đổi kể cả khi trận bị dời
    ngày/giờ bao nhiêu lần đi nữa."""

    return "|".join(
        [season_slug, clean_team_text(home_name), clean_team_text(away_name)]
    )


def compute_fallback_match_id(source_match_id: str) -> int:
    """match_id mặc định cho 1 trận CHƯA từng có trong database (lần đầu
    crawl một mùa giải mới). Với trận ĐÃ có trong DB, luôn ưu tiên tái sử
    dụng match_id cũ (xem fetch_existing_match_lookup) thay vì hash lại,
    để không bao giờ đổi ID của 1 trận đã tồn tại."""

    return stable_postgres_integer(
        "epl-match-v2", f"{COMPETITION_KEY}|{source_match_id}"
    )


def normalize_matches(
    raw_matches: list[dict[str, Any]],
    team_name_to_id: dict[str, int],
    existing_match_lookup: dict[tuple[int, int], int],
) -> tuple[list[dict[str, Any]], list[int], dict[str, int]]:
    """Chuẩn hoá dữ liệu trận đấu thô từ nguồn.

    existing_match_lookup: {(home_team_id, away_team_id): match_id} lấy
    từ database hiện có (cùng season_slug) — dùng để TÁI SỬ DỤNG match_id
    cũ cho các trận đã tồn tại, thay vì tính hash mới. Đây là bước tự
    phục hồi (self-heal) cốt lõi giúp lịch thi đấu bị dời ngày/giờ luôn
    được cập nhật (UPDATE) vào đúng dòng cũ, không bao giờ bị hiểu nhầm
    thành trận mới.
    """

    records: list[dict[str, Any]] = []
    matchdays: list[int] = []
    team_name_lookup = build_team_name_lookup(set(team_name_to_id))

    stats = {"reused_match_id": 0, "new_match_id": 0}

    sorted_matches = sorted(
        raw_matches,
        key=lambda m: (
            m["date"].isoformat(),
            m["time"] or "",
            m["home_name"],
        ),
    )

    for match in sorted_matches:
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

        matchday = match["round"]
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

        home_team_id = team_name_to_id[home_name]
        away_team_id = team_name_to_id[away_name]

        source_match_id = build_source_match_id(SEASON_SLUG, home_name, away_name)

        existing_match_id = existing_match_lookup.get((home_team_id, away_team_id))

        if existing_match_id is not None:
            match_id = existing_match_id
            stats["reused_match_id"] += 1
        else:
            match_id = compute_fallback_match_id(source_match_id)
            stats["new_match_id"] += 1

        matchdays.append(matchday)

        records.append(
            {
                "match_id": match_id,
                "source_match_id": source_match_id,
                "season_slug": SEASON_SLUG,
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
                "home_team_id": home_team_id,
                "home_team_name": home_name,
                "away_team_id": away_team_id,
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

    return records, matchdays, stats


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
    team_pairs = [(row["home_team_id"], row["away_team_id"]) for row in matches]

    if len(match_ids) != len(set(match_ids)):
        dup = [mid for mid, cnt in Counter(match_ids).items() if cnt > 1]
        errors.append(f"Có match_id bị trùng: {dup}")

    if len(source_ids) != len(set(source_ids)):
        dup = [sid for sid, cnt in Counter(source_ids).items() if cnt > 1]
        errors.append(f"Có source_match_id bị trùng: {dup}")

    if len(team_pairs) != len(set(team_pairs)):
        dup = [pair for pair, cnt in Counter(team_pairs).items() if cnt > 1]
        errors.append(
            "Có cặp (home_team_id, away_team_id) bị trùng — vi phạm giả "
            f"định vòng tròn 2 lượt: {dup}"
        )

    observed_matchdays = set(matchdays)

    if observed_matchdays != EXPECTED_MATCHDAYS:
        errors.append(
            f"Vòng đấu không đủ 1-38. Đang có: {sorted(observed_matchdays)}"
        )

    matchday_counts = Counter(matchdays)
    invalid_round_counts = {
        round_no: count
        for round_no, count in matchday_counts.items()
        if count != EXPECTED_MATCHES_PER_ROUND
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

        if (
            home_count != EXPECTED_HOME_AWAY_PER_TEAM
            or away_count != EXPECTED_HOME_AWAY_PER_TEAM
        ):
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

        if (
            row["is_finished"]
            and parsed_goals > 0
            and expected_goals != parsed_goals
        ):
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

    _warn_if_missing_unique_source_match_id(inspector)


def _warn_if_missing_unique_source_match_id(inspector) -> None:
    """Chỉ cảnh báo (không chặn crawl) nếu không phát hiện được unique
    constraint/index trên matches.source_match_id — cột này PHẢI unique
    để tránh việc cùng 1 trận bị insert 2 lần trong trường hợp cơ chế
    self-heal (existing_match_lookup) vì lý do nào đó không tra được
    match_id cũ. Một số phiên bản driver/permissions có thể khiến bước
    inspect này không đọc được đầy đủ index, nên chỉ in cảnh báo, không
    raise lỗi."""

    try:
        indexes = inspector.get_indexes("matches", schema="public")
        has_unique_index = any(
            idx.get("unique") and list(idx.get("column_names", [])) == ["source_match_id"]
            for idx in indexes
        )

        unique_constraints = inspector.get_unique_constraints(
            "matches", schema="public"
        )
        has_unique_constraint = any(
            list(uc.get("column_names", [])) == ["source_match_id"]
            for uc in unique_constraints
        )

        if not (has_unique_index or has_unique_constraint):
            print(
                "[CẢNH BÁO] Không phát hiện unique constraint/index trên "
                "matches.source_match_id. Nếu đúng là chưa có, hãy tạo "
                "(CREATE UNIQUE INDEX ... ON matches(source_match_id)) để "
                "đảm bảo không có 2 dòng trùng khoá tự nhiên."
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[CẢNH BÁO] Không kiểm tra được index source_match_id: {exc}")


def fetch_existing_match_lookup(
    connection,
    matches_table: Table,
    season_slug: str,
) -> dict[tuple[int, int], int]:
    """Tra cứu match_id đã tồn tại trong DB theo cặp (home_team_id,
    away_team_id) — CHỈ trong đúng season_slug đang xử lý. Đây là bước
    self-heal cốt lõi: match_id trả về ở đây LUÔN được ưu tiên tái sử
    dụng thay vì tính hash mới, bất kể trước đây nó được tạo ra bằng
    công thức/định dạng source_match_id nào (kể cả công thức cũ có nhúng
    ngày thi đấu). Nhờ vậy, việc đổi công thức tính match_id không bao
    giờ làm trận đã tồn tại bị hiểu nhầm thành trận mới."""

    statement = select(
        matches_table.c.match_id,
        matches_table.c.home_team_id,
        matches_table.c.away_team_id,
    ).where(matches_table.c.season_slug == season_slug)

    rows_by_pair: dict[tuple[int, int], list[int]] = defaultdict(list)

    for row in connection.execute(statement).mappings():
        pair = (int(row["home_team_id"]), int(row["away_team_id"]))
        rows_by_pair[pair].append(int(row["match_id"]))

    duplicate_pairs = {
        pair: match_ids
        for pair, match_ids in rows_by_pair.items()
        if len(match_ids) > 1
    }

    if duplicate_pairs:
        details = "\n".join(
            f"  - home_team_id={pair[0]}, away_team_id={pair[1]}: "
            f"match_id={match_ids}"
            for pair, match_ids in duplicate_pairs.items()
        )
        raise RuntimeError(
            "Phát hiện NHIỀU dòng trong bảng matches cùng season_slug="
            f"{season_slug!r} có cùng cặp (home_team_id, away_team_id) — "
            "đây là dữ liệu trùng lặp còn sót lại (có thể từ lần chạy lỗi "
            "trước khi có cơ chế self-heal này). Script CHỦ ĐỘNG DỪNG LẠI "
            "thay vì tự đoán nên giữ dòng nào, để tránh làm mất dữ liệu "
            "predictions/match_goals đang tham chiếu tới match_id sai. "
            "Vui lòng kiểm tra và gộp/xoá thủ công các dòng trùng sau, "
            "giữ lại match_id nào đang có predictions/match_goals tham "
            "chiếu (hoặc match_id có is_finished=true):\n" + details
        )

    return {pair: match_ids[0] for pair, match_ids in rows_by_pair.items()}


def fetch_existing_rows(
    connection,
    matches_table: Table,
    match_ids: list[int],
    columns: list[str],
) -> dict[int, tuple[Any, ...]]:
    if not match_ids:
        return {}

    statement = select(
        matches_table.c.match_id,
        *[matches_table.c[column] for column in columns],
    ).where(matches_table.c.match_id.in_(match_ids))

    existing: dict[int, tuple[Any, ...]] = {}

    for row in connection.execute(statement).mappings():
        existing[int(row["match_id"])] = tuple(row[column] for column in columns)

    return existing


def result_state(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(column) for column in RESULT_STATE_COLUMNS)


def kickoff_state(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(column) for column in KICKOFF_DIAGNOSTIC_COLUMNS)


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
    engine,
    teams: list[dict[str, Any]],
    raw_matches: list[dict[str, Any]],
    team_name_to_id: dict[str, int],
) -> dict[str, Any]:
    metadata = MetaData()
    teams_table = Table("teams", metadata, autoload_with=engine)
    matches_table = Table("matches", metadata, autoload_with=engine)

    with engine.begin() as connection:
        # 1) Tra cứu match_id cũ theo cặp đội (self-heal) TRƯỚC khi tính
        #    toán dữ liệu trận — đây là bước quyết định để lịch thi đấu
        #    bị dời ngày/giờ luôn map đúng về 1 dòng duy nhất trong DB.
        existing_match_lookup = fetch_existing_match_lookup(
            connection, matches_table, SEASON_SLUG
        )
        print(
            f"Số cặp (đội nhà, đội khách) đã có trong DB (season "
            f"{SEASON_SLUG}): {len(existing_match_lookup)}"
        )

        matches, matchdays, id_stats = normalize_matches(
            raw_matches, team_name_to_id, existing_match_lookup
        )

        validate_dataset(teams, matches, matchdays)

        print(
            "Số trận tái sử dụng match_id cũ (self-heal):",
            id_stats["reused_match_id"],
        )
        print(
            "Số trận tạo match_id mới (chưa từng có trong DB):",
            id_stats["new_match_id"],
        )

        match_ids = [row["match_id"] for row in matches]

        # 2) Lấy trạng thái HIỆN TẠI trong DB (trước khi ghi đè) để biết
        #    (a) trận nào đổi kết quả -> cần chấm lại prediction, và
        #    (b) trận nào đổi lịch thi đấu (ngày/giờ) -> chỉ để LOG cho
        #    người vận hành yên tâm, không ảnh hưởng logic chấm điểm.
        existing_result_states = fetch_existing_rows(
            connection, matches_table, match_ids, RESULT_STATE_COLUMNS
        )
        existing_kickoff_states = fetch_existing_rows(
            connection, matches_table, match_ids, KICKOFF_DIAGNOSTIC_COLUMNS
        )

        changed_match_ids: list[int] = []
        kickoff_changed_rows: list[dict[str, Any]] = []

        for row in matches:
            match_id = row["match_id"]

            old_result = existing_result_states.get(match_id)
            new_result = result_state(row)

            if old_result is not None and old_result != new_result:
                changed_match_ids.append(match_id)
            elif old_result is None:
                # Trận hoàn toàn mới (chưa từng có trong DB) — không cần
                # rescoring (chưa thể có prediction cho trận chưa tồn
                # tại), nhưng vẫn tính là "mới" cho mục đích log ở trên.
                pass

            old_kickoff = existing_kickoff_states.get(match_id)
            new_kickoff = kickoff_state(row)

            if old_kickoff is not None and old_kickoff != new_kickoff:
                kickoff_changed_rows.append(
                    {
                        "match_id": match_id,
                        "matchup": f"{row['home_team_name']} vs {row['away_team_name']}",
                        "old_kickoff_utc": old_kickoff[
                            KICKOFF_DIAGNOSTIC_COLUMNS.index("kickoff_time_utc")
                        ],
                        "new_kickoff_utc": new_kickoff[
                            KICKOFF_DIAGNOSTIC_COLUMNS.index("kickoff_time_utc")
                        ],
                    }
                )

        if kickoff_changed_rows:
            print(
                f"\nPhát hiện {len(kickoff_changed_rows)} trận bị đổi lịch "
                "thi đấu (ngày/giờ) so với dữ liệu đang lưu — sẽ UPDATE "
                "đúng dòng cũ (KHÔNG tạo trận mới):"
            )
            for change in kickoff_changed_rows:
                print(
                    f"  - match_id={change['match_id']} "
                    f"({change['matchup']}): "
                    f"{change['old_kickoff_utc']} -> {change['new_kickoff_utc']}"
                )
        else:
            print("\nKhông có trận nào bị đổi lịch thi đấu so với lần crawl trước.")

        # Bỏ 2 field nội bộ (_home_goals/_away_goals) trước khi insert
        # vào bảng matches — chúng chỉ dùng để ghi bảng match_goals.
        clean_matches = [
            {k: v for k, v in row.items() if not k.startswith("_")}
            for row in matches
        ]

        if DRY_RUN:
            print(
                "\n[DRY RUN] CRAWL_DRY_RUN đang bật — KHÔNG ghi gì vào "
                "database. Dừng lại sau bước tính toán/so khớp."
            )
            return {
                "teams": len(teams),
                "matches": len(matches),
                "predictions": None,
                "changed_matches": len(changed_match_ids),
                "kickoff_changed_matches": len(kickoff_changed_rows),
                "rescored_predictions": 0,
                "reused_match_id": id_stats["reused_match_id"],
                "new_match_id": id_stats["new_match_id"],
                "matches_data": matches,
                "dry_run": True,
            }

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

        downgrade_guard = and_(
            matches_table.c.is_finished.is_(True),
            match_insert.excluded.is_finished.is_(False),
        )

        match_set_clause = {}

        for column in MATCH_COLUMNS:
            if column == "match_id":
                continue

            new_value = getattr(match_insert.excluded, column)

            if column in PROTECTED_RESULT_COLUMNS:
                match_set_clause[column] = case(
                    (downgrade_guard, matches_table.c[column]),
                    else_=new_value,
                )
            else:
                match_set_clause[column] = new_value

        # Arbiter vẫn là match_id (PK) — nhờ bước self-heal ở trên,
        # match_id ở đây LUÔN đúng là ID hiện có trong DB cho trận đó
        # (nếu đã tồn tại), nên ON CONFLICT sẽ khớp đúng dòng cần update
        # thay vì cố insert dòng mới rồi đụng unique constraint khác.
        match_upsert = match_insert.on_conflict_do_update(
            index_elements=[matches_table.c.match_id],
            set_=match_set_clause,
        )
        connection.execute(match_upsert)

        rescored_predictions = rescore_predictions(connection, changed_match_ids)

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
        "kickoff_changed_matches": len(kickoff_changed_rows),
        "rescored_predictions": rescored_predictions,
        "reused_match_id": id_stats["reused_match_id"],
        "new_match_id": id_stats["new_match_id"],
        "matches_data": matches,
        "dry_run": False,
    }


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

    if DRY_RUN:
        print(
            f"[DRY RUN] Sẽ refresh scorer cho {len(finished_match_ids)} trận "
            f"({len(goal_rows)} dòng bàn thắng) — KHÔNG ghi thật vào DB."
        )
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
    if DRY_RUN:
        print(">>> CHẾ ĐỘ DRY RUN — sẽ KHÔNG ghi gì vào database <<<")

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

    database_url = get_database_url()
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 20},
    )

    try:
        ensure_database_schema(engine)
        ensure_match_goals_table(engine)

        result = sync_database(engine, teams, raw_matches, team_name_to_id)

        print("\n" + "=" * 72)
        print("SYNC FIXTURE/SCORE THÀNH CÔNG" + (" (DRY RUN)" if DRY_RUN else ""))
        print("=" * 72)
        print("Số đội trong database:", result["teams"])
        print("Số trận trong database:", result["matches"])
        print("Số prediction hiện có:", result["predictions"])
        print("Số trận có dữ liệu kết quả thay đổi:", result["changed_matches"])
        print("Số trận bị đổi lịch thi đấu:", result["kickoff_changed_matches"])
        print("Số prediction được chấm lại:", result["rescored_predictions"])
        print("Số trận tái sử dụng match_id cũ:", result["reused_match_id"])
        print("Số trận tạo match_id mới:", result["new_match_id"])

        matches = result["matches_data"]
        finished_matches = [row for row in matches if row["is_finished"]]
        finished_match_ids = [row["match_id"] for row in finished_matches]
        goal_rows = build_goal_rows(finished_matches)

        write_match_goals(engine, goal_rows, finished_match_ids)

        if not DRY_RUN:
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
