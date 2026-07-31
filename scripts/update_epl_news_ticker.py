from __future__ import annotations

import json
import logging
import os
import re

from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

from google import genai
from google.genai import errors
from google.genai import types
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ============================================================
# CONFIG
# ============================================================

LOGGER = logging.getLogger("epl_news_ticker")

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Cố định đúng model theo yêu cầu.
# Script không đọc GEMINI_NEWS_MODEL để tránh workflow cũ ghi đè.
MODEL_NAME = "gemini-2.5-flash"

MIN_ITEMS = 12
MAX_ITEMS = 15

MIN_ITEM_LENGTH = 130
MAX_ITEM_LENGTH = 260

MAX_CONTENT_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 8192

CURRENT_ITEM_SIMILARITY_LIMIT = 0.84
PREVIOUS_ITEM_SIMILARITY_LIMIT = 0.97

ALLOWED_CATEGORIES = {
    "injury",
    "suspension",
    "team_news",
    "fixture",
    "manager",
    "transfer",
    "other",
}

ALLOWED_INFORMATION_STATUSES = {
    "confirmed",
    "reported",
    "monitoring",
}

UNCERTAIN_MARKERS = (
    "được cho là",
    "theo truyền thông anh",
    "đang được theo dõi",
    "chưa được xác nhận",
    "chưa có xác nhận",
    "có thể",
    "nhiều khả năng",
)

URL_PATTERN = re.compile(
    r"https?://|www\.",
    flags=re.IGNORECASE,
)

MARKDOWN_PATTERN = re.compile(
    r"```|^\s*[*#>]",
    flags=re.MULTILINE,
)

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)


class TickerValidationError(ValueError):
    """Gemini đã trả lời nhưng nội dung chưa đạt yêu cầu."""


# ============================================================
# ENVIRONMENT
# ============================================================


def require_environment() -> tuple[str, str]:
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()

    missing_variables: list[str] = []

    if not gemini_api_key:
        missing_variables.append("GEMINI_API_KEY")

    if not database_url:
        missing_variables.append("DATABASE_URL")

    if missing_variables:
        raise RuntimeError(
            "Thiếu biến môi trường: " + ", ".join(missing_variables)
        )

    return gemini_api_key, normalize_database_url(database_url)


def normalize_database_url(database_url: str) -> str:
    """Chuẩn hóa URL cũ của Heroku/Supabase nếu bắt đầu bằng postgres://."""

    if database_url.startswith("postgres://"):
        return "postgresql://" + database_url[len("postgres://") :]

    return database_url


# ============================================================
# DATABASE
# ============================================================


def build_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=1,
        max_overflow=1,
        pool_timeout=20,
        connect_args={
            "connect_timeout": 15,
            "options": (
                "-c statement_timeout=60000 "
                "-c lock_timeout=10000"
            ),
        },
    )


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_previous_items(engine: Engine) -> list[str]:
    query = text(
        """
        SELECT items
        FROM public.epl_news_ticker
        WHERE id = 1
        LIMIT 1
        """
    )

    with engine.connect() as connection:
        row = connection.execute(query).mappings().fetchone()

    if row is None:
        return []

    raw_items = row.get("items")

    if isinstance(raw_items, str):
        try:
            raw_items = json.loads(raw_items)
        except json.JSONDecodeError:
            LOGGER.warning(
                "Không đọc được JSON bản tin trước. Tiếp tục với danh sách rỗng."
            )
            return []

    if not isinstance(raw_items, list):
        return []

    previous_items: list[str] = []

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue

        item_text = normalize_text(raw_item.get("text"))

        if item_text:
            previous_items.append(item_text)

    return previous_items[:MAX_ITEMS]


# ============================================================
# PROMPT
# ============================================================


def build_prompt(
    run_time_vietnam: datetime,
    previous_items: list[str],
    validation_feedback: list[str] | None = None,
) -> str:
    if previous_items:
        previous_items_text = "\n".join(
            f"- {item}" for item in previous_items
        )
    else:
        previous_items_text = "Chưa có bản tin trước."

    feedback_text = ""

    if validation_feedback:
        feedback_text = (
            "\n\nCÁC LỖI CẦN SỬA\n"
            "Lần trả lời trước không hợp lệ. "
            "Hãy tạo lại toàn bộ JSON và sửa các lỗi sau:\n"
            + "\n".join(f"- {error}" for error in validation_feedback)
        )

    return f"""
Bạn là biên tập viên ticker cho một ứng dụng dự đoán Premier League.

THỜI ĐIỂM CẬP NHẬT

- Thời điểm hệ thống bắt đầu thu thập tin tại Việt Nam: {run_time_vietnam.isoformat()}

MỤC TIÊU

Bắt buộc sử dụng Google Search trước khi viết.

Hãy tìm kiếm, đối chiếu và tổng hợp từ {MIN_ITEMS} đến {MAX_ITEMS} tin tức nổi bật, mới nhất liên quan trực tiếp đến Premier League tại thời điểm tìm kiếm.

Mục tiêu quan trọng nhất là nội dung phải mới, đáng chú ý, đáng tin cậy và hữu ích cho người theo dõi Premier League, đặc biệt là người chơi dự đoán kết quả trận đấu.

CÁCH XÁC ĐỊNH TIN MỚI

- So sánh ngày và giờ công bố hoặc cập nhật giữa các nguồn.
- Ưu tiên thông tin vừa được công bố hoặc vừa có diễn biến mới.
- Ưu tiên các tin trong vòng 24 giờ gần nhất.
- Nếu chưa đủ {MIN_ITEMS} tin nổi bật trong 24 giờ gần nhất, có thể mở rộng phạm vi tìm kiếm đến 72 giờ nhưng phải xếp các diễn biến mới nhất lên trước.
- Không lấy bài viết cũ rồi mô tả như một diễn biến mới.
- Nếu nhiều bài cùng nói về một sự kiện, chỉ chọn thông tin mới nhất, đầy đủ nhất và đáng tin cậy nhất.
- Không chọn tin chỉ vì bài viết mới đăng lại nhưng nội dung thực tế đã cũ.
- Không dùng các tin nhỏ, ít giá trị chỉ để làm đủ số lượng.

PHẠM VI NỘI DUNG

Ưu tiên theo thứ tự:

1. Chấn thương, thể trạng và khả năng ra sân của cầu thủ.
2. Thông tin lực lượng trước trận.
3. Treo giò, án phạt và thay đổi danh sách thi đấu.
4. Xác nhận mới từ huấn luyện viên hoặc câu lạc bộ.
5. Thay đổi lịch thi đấu, giờ thi đấu hoặc sân đấu.
6. Thay đổi huấn luyện viên hoặc tình hình nội bộ ảnh hưởng trực tiếp đến đội bóng.
7. Chuyển nhượng đã được xác nhận hoặc được nhiều nguồn uy tín tại Anh cùng đưa tin.
8. Các diễn biến đáng chú ý khác liên quan trực tiếp đến Premier League.

YÊU CẦU TÌM KIẾM

- Chỉ chọn tin liên quan trực tiếp đến Premier League hoặc các câu lạc bộ đang thi đấu tại Premier League.
- Ưu tiên nguồn chính thức của Premier League, câu lạc bộ và huấn luyện viên.
- Ưu tiên các hãng truyền thông thể thao uy tín tại Anh và quốc tế.
- Không sử dụng bài đăng mạng xã hội chưa được xác minh làm nguồn duy nhất.
- Không bịa phát biểu, chấn thương, thời gian, con số hoặc trạng thái thương vụ.
- Không đưa tin về giải đấu khác nếu không có liên hệ trực tiếp đến một câu lạc bộ Premier League.
- Nếu thông tin chưa được xác nhận, phải thể hiện rõ trạng thái chưa chắc chắn.
- Không đưa tỷ lệ cược, nội dung cá cược hoặc quảng bá nhà cái.

PHONG CÁCH TICKER

Mỗi tin phải là một câu tiếng Việt hoàn chỉnh theo phong cách bản tin thể thao truyền hình.

Mỗi câu phải có đủ:

- Chủ thể rõ ràng.
- Diễn biến hoặc thông tin chính.
- Bối cảnh, trạng thái xác nhận hoặc tác động đến đội bóng hay trận đấu.

Không viết kiểu headline cụt như:

- Arsenal nhận tin dữ.
- Chelsea chốt bom tấn.
- Liverpool gặp biến lớn.

Hãy viết thành câu đầy đủ, tự nhiên và dễ đọc khi chạy ngang trên màn hình.

QUY TẮC BIÊN TẬP

- Viết hoàn toàn bằng tiếng Việt tự nhiên.
- Mỗi tin dài từ {MIN_ITEM_LENGTH} đến {MAX_ITEM_LENGTH} ký tự, tính cả dấu cách.
- Không dùng emoji, hashtag, markdown hoặc URL.
- Không thêm tiêu đề riêng cho từng tin.
- Không ghi URL hoặc tên nguồn trong câu ticker.
- Không giật tít hoặc suy đoán quá mức.
- Không mở đầu rườm rà bằng các cụm như “Theo thông tin mới nhất”.
- Nếu tin chưa được xác nhận, dùng các cụm như “được cho là”, “theo truyền thông Anh”, “đang được theo dõi”, “có thể” hoặc “chưa được xác nhận”.
- Không biến tin đồn thành thông tin chính thức.
- Không viết hai tin khác nhau về cùng một sự kiện.
- Không để một câu lạc bộ chiếm phần lớn bản tin.
- Tin chuyển nhượng chưa hoàn tất không được chiếm quá ba tin.
- Ưu tiên tin có ảnh hưởng trực tiếp đến lực lượng, phong độ hoặc kết quả trận đấu.

BẢN TIN HIỆN ĐANG HIỂN THỊ

{previous_items_text}

Hãy dùng danh sách trên để nhận biết những sự kiện đã được đề cập.

Ưu tiên diễn biến mới hơn bản tin hiện tại. Một sự kiện cũ chỉ được đưa lại khi vẫn là tin lớn tại thời điểm hiện tại hoặc đã có cập nhật đáng kể, chẳng hạn kết quả kiểm tra chấn thương, xác nhận của huấn luyện viên, cầu thủ trở lại tập luyện, thương vụ hoàn tất hoặc lịch đấu thay đổi.

ĐẦU RA

Trả về duy nhất một JSON hợp lệ.

Không đặt JSON trong dấu ```.

Không viết giải thích, lời dẫn hoặc kết luận ngoài JSON.

Cấu trúc bắt buộc:

{{
  "items": [
    {{
      "text": "Nội dung ticker hoàn chỉnh",
      "category": "injury | suspension | team_news | fixture | manager | transfer | other",
      "information_status": "confirmed | reported | monitoring"
    }}
  ]
}}

Ý nghĩa information_status:

- confirmed: Đã được Premier League, câu lạc bộ, huấn luyện viên hoặc nguồn chính thức xác nhận.
- reported: Được truyền thông uy tín đưa tin nhưng chưa có xác nhận chính thức.
- monitoring: Tình trạng đang được theo dõi, chưa có kết luận cuối cùng.

Trước khi trả kết quả, tự kiểm tra:

- Có từ {MIN_ITEMS} đến {MAX_ITEMS} tin.
- Các tin là những diễn biến mới và nổi bật nhất tại thời điểm tìm kiếm.
- Mỗi tin dài từ {MIN_ITEM_LENGTH} đến {MAX_ITEM_LENGTH} ký tự.
- Không có hai tin trùng ý.
- Không có tin nào thiếu chủ thể.
- Không có URL, markdown hoặc emoji.
- Tất cả tin đều liên quan trực tiếp đến Premier League.
- Không biến thông tin chưa xác nhận thành sự thật.
{feedback_text}
""".strip()


# ============================================================
# GEMINI
# ============================================================


def generate_with_google_search(client: genai.Client, prompt: str):
    google_search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    config = types.GenerateContentConfig(
        tools=[google_search_tool],
        temperature=0.2,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    return client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=config,
    )


def response_used_google_search(response: Any) -> bool:
    candidates = getattr(response, "candidates", None) or []

    for candidate in candidates:
        grounding_metadata = getattr(
            candidate,
            "grounding_metadata",
            None,
        )

        if grounding_metadata is None:
            continue

        web_search_queries = getattr(
            grounding_metadata,
            "web_search_queries",
            None,
        )

        grounding_chunks = getattr(
            grounding_metadata,
            "grounding_chunks",
            None,
        )

        if web_search_queries or grounding_chunks:
            return True

    return False


# ============================================================
# PARSE JSON
# ============================================================


def extract_json_payload(response_text: str) -> dict[str, Any]:
    cleaned_text = str(response_text or "").strip()

    cleaned_text = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned_text,
        flags=re.IGNORECASE,
    )

    cleaned_text = re.sub(
        r"\s*```$",
        "",
        cleaned_text,
    )

    first_brace = cleaned_text.find("{")
    last_brace = cleaned_text.rfind("}")

    if first_brace < 0 or last_brace <= first_brace:
        raise TickerValidationError(
            "Không tìm thấy JSON object trong phản hồi."
        )

    json_text = cleaned_text[first_brace : last_brace + 1]

    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as error:
        raise TickerValidationError(
            f"JSON không hợp lệ: {error}"
        ) from error

    if not isinstance(payload, dict):
        raise TickerValidationError(
            "Kết quả gốc phải là một JSON object."
        )

    return payload


# ============================================================
# VALIDATE
# ============================================================


def text_similarity(first_text: str, second_text: str) -> float:
    return SequenceMatcher(
        None,
        first_text.casefold(),
        second_text.casefold(),
    ).ratio()


def validate_ticker_items(
    payload: dict[str, Any],
    previous_items: list[str],
) -> list[dict[str, Any]]:
    raw_items = payload.get("items")

    if not isinstance(raw_items, list):
        raise TickerValidationError("items phải là một array.")

    validation_errors: list[str] = []

    if not MIN_ITEMS <= len(raw_items) <= MAX_ITEMS:
        validation_errors.append(
            f"Bản tin phải có từ {MIN_ITEMS} đến {MAX_ITEMS} tin."
        )

    normalized_items: list[dict[str, Any]] = []

    for index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            validation_errors.append(
                f"Tin {index} không phải JSON object."
            )
            continue

        ticker_text = normalize_text(raw_item.get("text"))
        category = normalize_text(raw_item.get("category")).casefold()
        information_status = normalize_text(
            raw_item.get("information_status")
        ).casefold()

        ticker_length = len(ticker_text)

        if not ticker_text:
            validation_errors.append(
                f"Tin {index} không có nội dung."
            )

        if not MIN_ITEM_LENGTH <= ticker_length <= MAX_ITEM_LENGTH:
            validation_errors.append(
                f"Tin {index} dài {ticker_length} ký tự, "
                f"yêu cầu từ {MIN_ITEM_LENGTH} đến {MAX_ITEM_LENGTH}."
            )

        if URL_PATTERN.search(ticker_text):
            validation_errors.append(f"Tin {index} chứa URL.")

        if MARKDOWN_PATTERN.search(ticker_text):
            validation_errors.append(f"Tin {index} chứa markdown.")

        if EMOJI_PATTERN.search(ticker_text):
            validation_errors.append(f"Tin {index} chứa emoji.")

        if category not in ALLOWED_CATEGORIES:
            validation_errors.append(
                f"Tin {index} có category không hợp lệ: {category or '(trống)'}."
            )

        if information_status not in ALLOWED_INFORMATION_STATUSES:
            validation_errors.append(
                "Tin "
                f"{index} có information_status không hợp lệ: "
                f"{information_status or '(trống)'}."
            )

        if information_status in {"reported", "monitoring"}:
            lowered_text = ticker_text.casefold()

            if not any(
                marker in lowered_text for marker in UNCERTAIN_MARKERS
            ):
                validation_errors.append(
                    f"Tin {index} chưa được xác nhận nhưng thiếu "
                    "cách diễn đạt thận trọng."
                )

        normalized_items.append(
            {
                "priority": index,
                "text": ticker_text,
                "category": category,
                "information_status": information_status,
            }
        )

    for first_index, first_item in enumerate(normalized_items):
        for second_index in range(
            first_index + 1,
            len(normalized_items),
        ):
            second_item = normalized_items[second_index]

            similarity_score = text_similarity(
                first_item["text"],
                second_item["text"],
            )

            if similarity_score >= CURRENT_ITEM_SIMILARITY_LIMIT:
                validation_errors.append(
                    f"Tin {first_index + 1} và tin {second_index + 1} "
                    "quá giống nhau."
                )

    for item_index, item in enumerate(normalized_items, start=1):
        for previous_text in previous_items:
            similarity_score = text_similarity(
                item["text"],
                previous_text,
            )

            if similarity_score >= PREVIOUS_ITEM_SIMILARITY_LIMIT:
                validation_errors.append(
                    f"Tin {item_index} gần như lặp nguyên văn "
                    "bản tin trước."
                )
                break

    unconfirmed_transfers = sum(
        1
        for item in normalized_items
        if item["category"] == "transfer"
        and item["information_status"] != "confirmed"
    )

    if unconfirmed_transfers > 3:
        validation_errors.append(
            "Có quá ba tin chuyển nhượng chưa được xác nhận."
        )

    if validation_errors:
        raise TickerValidationError("\n".join(validation_errors))

    return normalized_items


def validation_error_lines(error: Exception) -> list[str]:
    return [
        line.strip()
        for line in str(error).splitlines()
        if line.strip()
    ][:20]


# ============================================================
# PUBLISH
# ============================================================


def publish_ticker(
    engine: Engine,
    generated_at: datetime,
    items: list[dict[str, Any]],
) -> None:
    published_at_utc = datetime.now(timezone.utc)

    items_json = json.dumps(
        items,
        ensure_ascii=False,
    )

    ticker_text = "   ◆   ".join(item["text"] for item in items)

    query = text(
        """
        INSERT INTO public.epl_news_ticker (
            id,
            generated_at,
            previous_items,
            items,
            ticker_text,
            model_name,
            updated_at
        )
        VALUES (
            1,
            :generated_at,
            '[]'::jsonb,
            CAST(:items_json AS jsonb),
            :ticker_text,
            :model_name,
            :updated_at
        )
        ON CONFLICT (id)
        DO UPDATE SET
            previous_items = public.epl_news_ticker.items,
            generated_at = EXCLUDED.generated_at,
            items = EXCLUDED.items,
            ticker_text = EXCLUDED.ticker_text,
            model_name = EXCLUDED.model_name,
            updated_at = EXCLUDED.updated_at
        """
    )

    params = {
        "generated_at": generated_at.astimezone(timezone.utc),
        "items_json": items_json,
        "ticker_text": ticker_text,
        "model_name": MODEL_NAME,
        "updated_at": published_at_utc,
    }

    with engine.begin() as connection:
        connection.execute(query, params)


# ============================================================
# ERROR HELPERS
# ============================================================


def get_api_error_code(error: errors.APIError) -> str:
    code = getattr(error, "code", None)
    return str(code) if code is not None else "unknown"


def get_api_error_message(error: errors.APIError) -> str:
    message = getattr(error, "message", None)

    if message:
        return normalize_text(message)

    return normalize_text(str(error))


# ============================================================
# MAIN
# ============================================================


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    gemini_api_key, database_url = require_environment()

    run_time_vietnam = datetime.now(VN_TZ)

    LOGGER.info(
        "Generating EPL ticker at %s",
        run_time_vietnam.isoformat(),
    )

    LOGGER.info(
        "Using Gemini model: %s",
        MODEL_NAME,
    )

    engine = build_engine(database_url)
    client = genai.Client(api_key=gemini_api_key)

    try:
        previous_items = load_previous_items(engine)

        LOGGER.info(
            "Loaded %s previous ticker items.",
            len(previous_items),
        )

        final_items: list[dict[str, Any]] | None = None
        validation_feedback: list[str] | None = None
        last_validation_error: Exception | None = None

        for attempt in range(1, MAX_CONTENT_ATTEMPTS + 1):
            LOGGER.info(
                "Gemini content attempt %s/%s",
                attempt,
                MAX_CONTENT_ATTEMPTS,
            )

            prompt = build_prompt(
                run_time_vietnam=run_time_vietnam,
                previous_items=previous_items,
                validation_feedback=validation_feedback,
            )

            try:
                response = generate_with_google_search(
                    client,
                    prompt,
                )

                if not response_used_google_search(response):
                    raise TickerValidationError(
                        "Phản hồi không có dữ liệu Google Search grounding."
                    )

                response_text = getattr(response, "text", "") or ""

                if not response_text.strip():
                    raise TickerValidationError(
                        "Gemini không trả về nội dung văn bản."
                    )

                payload = extract_json_payload(response_text)

                final_items = validate_ticker_items(
                    payload,
                    previous_items,
                )

                break

            except errors.APIError as error:
                api_code = get_api_error_code(error)
                api_message = get_api_error_message(error)

                raise RuntimeError(
                    "Gemini API request thất bại. "
                    f"HTTP {api_code}: {api_message}. "
                    "Ticker cũ được giữ nguyên."
                ) from error

            except TickerValidationError as error:
                last_validation_error = error
                validation_feedback = validation_error_lines(error)

                LOGGER.warning(
                    "Content validation attempt %s failed: %s",
                    attempt,
                    " | ".join(validation_feedback),
                )

            except Exception as error:
                raise RuntimeError(
                    "Ticker generation gặp lỗi không mong đợi. "
                    "Ticker cũ được giữ nguyên. "
                    f"Chi tiết: {error}"
                ) from error

        if final_items is None:
            raise RuntimeError(
                "Không tạo được bản tin hợp lệ sau "
                f"{MAX_CONTENT_ATTEMPTS} lần. "
                "Ticker cũ được giữ nguyên. "
                f"Lỗi cuối: {last_validation_error}"
            )

        publish_ticker(
            engine=engine,
            generated_at=run_time_vietnam,
            items=final_items,
        )

        LOGGER.info(
            "Published ticker with %s items.",
            len(final_items),
        )

        return 0

    finally:
        engine.dispose()

        close_client = getattr(client, "close", None)

        if callable(close_client):
            close_client()


if __name__ == "__main__":
    raise SystemExit(main())
