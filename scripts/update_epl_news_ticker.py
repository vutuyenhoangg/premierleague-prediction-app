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
from google.genai import types

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ============================================================
# CONFIG
# ============================================================

LOGGER = logging.getLogger(
    "epl_news_ticker"
)

VN_TZ = ZoneInfo(
    "Asia/Ho_Chi_Minh"
)

MODEL_NAME = os.getenv(
    "GEMINI_NEWS_MODEL",
    "gemini-3.6-flash"
).strip()

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


class TickerValidationError(ValueError):
    pass


# ============================================================
# ENVIRONMENT
# ============================================================

def require_environment() -> tuple[str, str]:
    gemini_api_key = os.getenv(
        "GEMINI_API_KEY",
        ""
    ).strip()

    database_url = os.getenv(
        "DATABASE_URL",
        ""
    ).strip()

    missing_variables = []

    if not gemini_api_key:
        missing_variables.append(
            "GEMINI_API_KEY"
        )

    if not database_url:
        missing_variables.append(
            "DATABASE_URL"
        )

    if missing_variables:
        raise RuntimeError(
            "Thiếu biến môi trường: "
            + ", ".join(
                missing_variables
            )
        )

    return (
        gemini_api_key,
        database_url,
    )


# ============================================================
# DATABASE
# ============================================================

def build_engine(
    database_url: str
) -> Engine:

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


def normalize_text(
    value: Any
) -> str:

    return re.sub(
        r"\s+",
        " ",
        str(value or "")
    ).strip()


def load_previous_items(
    engine: Engine
) -> list[str]:

    query = text(
        """
        SELECT items
        FROM epl_news_ticker
        WHERE id = 1
        LIMIT 1
        """
    )

    with engine.connect() as connection:
        row = connection.execute(
            query
        ).mappings().fetchone()

    if row is None:
        return []

    raw_items = row.get("items")

    if isinstance(raw_items, str):
        try:
            raw_items = json.loads(
                raw_items
            )
        except json.JSONDecodeError:
            return []

    if not isinstance(raw_items, list):
        return []

    previous_items = []

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue

        item_text = normalize_text(
            raw_item.get("text")
        )

        if item_text:
            previous_items.append(
                item_text
            )

    return previous_items[:10]


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
            f"- {item}"
            for item in previous_items
        )
    else:
        previous_items_text = (
            "Chưa có bản tin trước."
        )

    feedback_text = ""

    if validation_feedback:
        feedback_text = (
            "\n\nCÁC LỖI CẦN SỬA\n"
            "Lần trả lời trước không hợp lệ. "
            "Hãy tạo lại toàn bộ JSON và sửa các lỗi sau:\n"
            + "\n".join(
                f"- {error}"
                for error in validation_feedback
            )
        )

    return f"""
Bạn là biên tập viên ticker cho ứng dụng dự đoán Premier League.

THỜI ĐIỂM CẬP NHẬT

- Thời điểm chạy hệ thống tại Việt Nam: {run_time_vietnam.isoformat()}

MỤC TIÊU

Bắt buộc sử dụng Google Search trước khi viết.

Hãy tìm kiếm, kiểm tra và tổng hợp từ 8 đến 10 tin tức nổi bật, mới nhất liên quan trực tiếp đến Premier League tại thời điểm hiện tại.

Mục tiêu quan trọng nhất là nội dung phải mới, đáng chú ý và có giá trị đối với người theo dõi Premier League.

CÁCH XÁC ĐỊNH TIN MỚI

- So sánh ngày và giờ công bố hoặc cập nhật của các nguồn.
- Ưu tiên thông tin vừa được công bố hoặc vừa có diễn biến mới.
- Ưu tiên các tin trong vòng 24 giờ gần nhất.
- Có thể mở rộng phạm vi tìm kiếm nếu trong 24 giờ chưa có đủ tin đáng chú ý.
- Không lấy bài viết cũ rồi mô tả như một diễn biến mới.
- Nếu nhiều bài cùng nói về một sự kiện, chỉ chọn thông tin mới nhất và đầy đủ nhất.
- Không chọn tin chỉ vì bài viết mới đăng lại nhưng nội dung thực tế đã cũ.
- Không cố tạo đủ số lượng bằng các tin nhỏ, thiếu giá trị hoặc không còn mới.

PHẠM VI NỘI DUNG

Ưu tiên theo thứ tự:

1. Chấn thương, thể trạng và khả năng ra sân của cầu thủ.
2. Thông tin lực lượng trước trận.
3. Treo giò, án phạt và thay đổi danh sách thi đấu.
4. Xác nhận mới từ huấn luyện viên hoặc câu lạc bộ.
5. Thay đổi lịch thi đấu, giờ thi đấu hoặc sân đấu.
6. Thay đổi huấn luyện viên hoặc tình hình nội bộ ảnh hưởng đến đội bóng.
7. Chuyển nhượng đã được xác nhận hoặc được nhiều nguồn uy tín tại Anh cùng đưa tin.
8. Các diễn biến đáng chú ý khác liên quan trực tiếp đến Premier League.

YÊU CẦU TÌM KIẾM

- Chỉ chọn tin liên quan trực tiếp đến Premier League hoặc các câu lạc bộ đang thi đấu tại Premier League.
- Ưu tiên nguồn chính thức của Premier League, câu lạc bộ và huấn luyện viên.
- Ưu tiên các hãng truyền thông thể thao uy tín.
- Không sử dụng bài đăng mạng xã hội chưa được xác minh làm nguồn duy nhất.
- Không bịa phát biểu, chấn thương, thời gian, con số hoặc trạng thái thương vụ.
- Không đưa tin về giải đấu khác nếu không có liên hệ trực tiếp đến một câu lạc bộ Premier League.
- Nếu thông tin chưa được xác nhận, phải thể hiện rõ trạng thái chưa chắc chắn.

PHONG CÁCH TICKER

Mỗi tin phải là một câu tiếng Việt hoàn chỉnh theo phong cách ticker của bản tin thể thao truyền hình.

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

- Viết hoàn toàn bằng tiếng Việt.
- Mỗi tin dài từ 130 đến 220 ký tự, tính cả dấu cách.
- Không dùng emoji, hashtag, markdown hoặc URL.
- Không thêm tiêu đề riêng cho từng tin.
- Không ghi URL hoặc tên nguồn trong câu ticker.
- Không giật tít hoặc suy đoán quá mức.
- Không mở đầu rườm rà bằng các cụm như “Theo thông tin mới nhất”.
- Nếu tin chưa được xác nhận, dùng các cụm như “được cho là”, “theo truyền thông Anh”, “đang được theo dõi” hoặc “chưa được xác nhận”.
- Không biến tin đồn thành thông tin chính thức.
- Không viết hai tin khác nhau về cùng một sự kiện.
- Không để một câu lạc bộ chiếm phần lớn bản tin.
- Tin chuyển nhượng chưa hoàn tất không được chiếm quá ba tin.
- Ưu tiên tin có ảnh hưởng trực tiếp đến lực lượng, phong độ hoặc kết quả trận đấu.

BẢN TIN HIỆN ĐANG HIỂN THỊ

{previous_items_text}

Hãy dùng danh sách trên để nhận biết những sự kiện đã cũ.

Ưu tiên diễn biến mới hơn bản tin hiện tại.

Một sự kiện cũ chỉ được đưa lại khi:

- Vẫn là một trong những tin quan trọng nhất tại thời điểm hiện tại; hoặc
- Đã có diễn biến mới như kết quả kiểm tra, xác nhận của huấn luyện viên, cầu thủ trở lại tập luyện, thương vụ hoàn tất hoặc lịch đấu thay đổi.

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

Trước khi trả kết quả, tự kiểm tra:

- Có từ 8 đến 10 tin.
- Các tin là những diễn biến mới và nổi bật nhất tại thời điểm tìm kiếm.
- Mỗi tin dài từ 130 đến 220 ký tự.
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

def generate_with_google_search(
    client: genai.Client,
    prompt: str
):

    google_search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    config = types.GenerateContentConfig(
        tools=[
            google_search_tool
        ],
        temperature=0.2,
        max_output_tokens=8192,
    )

    return client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=config,
    )


def response_used_google_search(
    response
) -> bool:

    candidates = (
        getattr(
            response,
            "candidates",
            None
        )
        or []
    )

    for candidate in candidates:
        grounding_metadata = getattr(
            candidate,
            "grounding_metadata",
            None
        )

        if grounding_metadata is not None:
            return True

    return False


# ============================================================
# PARSE JSON
# ============================================================

def extract_json_payload(
    response_text: str
) -> dict:

    cleaned_text = str(
        response_text or ""
    ).strip()

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

    first_brace = cleaned_text.find(
        "{"
    )

    last_brace = cleaned_text.rfind(
        "}"
    )

    if (
        first_brace < 0
        or last_brace <= first_brace
    ):
        raise TickerValidationError(
            "Không tìm thấy JSON object."
        )

    json_text = cleaned_text[
        first_brace:last_brace + 1
    ]

    try:
        payload = json.loads(
            json_text
        )

    except json.JSONDecodeError as error:
        raise TickerValidationError(
            f"JSON không hợp lệ: {error}"
        ) from error

    if not isinstance(payload, dict):
        raise TickerValidationError(
            "Kết quả gốc phải là JSON object."
        )

    return payload


# ============================================================
# VALIDATE
# ============================================================

def text_similarity(
    first_text: str,
    second_text: str
) -> float:

    return SequenceMatcher(
        None,
        first_text.casefold(),
        second_text.casefold(),
    ).ratio()


def validate_ticker_items(
    payload: dict
) -> list[dict]:

    raw_items = payload.get(
        "items"
    )

    if not isinstance(raw_items, list):
        raise TickerValidationError(
            "items phải là một array."
        )

    errors = []

    if not 8 <= len(raw_items) <= 10:
        errors.append(
            "Bản tin phải có từ 8 đến 10 tin."
        )

    normalized_items = []

    for index, raw_item in enumerate(
        raw_items,
        start=1
    ):
        if not isinstance(raw_item, dict):
            errors.append(
                f"Tin {index} không phải object."
            )
            continue

        ticker_text = normalize_text(
            raw_item.get("text")
        )

        category = normalize_text(
            raw_item.get("category")
        ).casefold()

        information_status = normalize_text(
            raw_item.get(
                "information_status"
            )
        ).casefold()

        ticker_length = len(
            ticker_text
        )

        if not 130 <= ticker_length <= 220:
            errors.append(
                f"Tin {index} dài "
                f"{ticker_length} ký tự, "
                "yêu cầu từ 130 đến 220."
            )

        if re.search(
            r"https?://|www\.",
            ticker_text,
            flags=re.IGNORECASE,
        ):
            errors.append(
                f"Tin {index} chứa URL."
            )

        if re.search(
            r"```|^\s*[*#>]",
            ticker_text,
            flags=re.MULTILINE,
        ):
            errors.append(
                f"Tin {index} chứa markdown."
            )

        if category not in ALLOWED_CATEGORIES:
            errors.append(
                f"Tin {index} có category "
                f"không hợp lệ: {category}."
            )

        if (
            information_status
            not in ALLOWED_INFORMATION_STATUSES
        ):
            errors.append(
                f"Tin {index} có "
                "information_status không hợp lệ."
            )

        normalized_items.append({
            "priority": index,
            "text": ticker_text,
            "category": category,
            "information_status": (
                information_status
            ),
        })

    for first_index, first_item in enumerate(
        normalized_items
    ):
        for second_index in range(
            first_index + 1,
            len(normalized_items)
        ):
            similarity_score = text_similarity(
                first_item["text"],
                normalized_items[
                    second_index
                ]["text"],
            )

            if similarity_score >= 0.84:
                errors.append(
                    f"Tin {first_index + 1} và "
                    f"tin {second_index + 1} "
                    "quá giống nhau."
                )

    unconfirmed_transfers = sum(
        1
        for item in normalized_items
        if (
            item["category"] == "transfer"
            and item[
                "information_status"
            ] != "confirmed"
        )
    )

    if unconfirmed_transfers > 3:
        errors.append(
            "Có quá ba tin chuyển nhượng "
            "chưa được xác nhận."
        )

    if errors:
        raise TickerValidationError(
            "\n".join(errors)
        )

    return normalized_items


def validation_error_lines(
    error: Exception
) -> list[str]:

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
    items: list[dict],
):

    items_json = json.dumps(
        items,
        ensure_ascii=False
    )

    ticker_text = "   ◆   ".join(
        item["text"]
        for item in items
    )

    query = text(
        """
        INSERT INTO epl_news_ticker (
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
            previous_items =
                epl_news_ticker.items,

            generated_at =
                EXCLUDED.generated_at,

            items =
                EXCLUDED.items,

            ticker_text =
                EXCLUDED.ticker_text,

            model_name =
                EXCLUDED.model_name,

            updated_at =
                EXCLUDED.updated_at
        """
    )

    params = {
        "generated_at": (
            generated_at.astimezone(
                timezone.utc
            )
        ),

        "items_json": items_json,

        "ticker_text": ticker_text,

        "model_name": MODEL_NAME,

        "updated_at": (
            generated_at.astimezone(
                timezone.utc
            )
        ),
    }

    with engine.begin() as connection:
        connection.execute(
            query,
            params,
        )


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(message)s"
        ),
    )

    (
        gemini_api_key,
        database_url,
    ) = require_environment()

    run_time_vietnam = datetime.now(
        VN_TZ
    )

    LOGGER.info(
        "Generating EPL ticker at %s",
        run_time_vietnam.isoformat()
    )

    engine = build_engine(
        database_url
    )

    client = genai.Client(
        api_key=gemini_api_key
    )

    try:
        previous_items = load_previous_items(
            engine
        )

        final_items = None
        validation_feedback = None
        last_error = None

        for attempt in range(1, 3):
            LOGGER.info(
                "Gemini attempt %s/2",
                attempt
            )

            prompt = build_prompt(
                run_time_vietnam=run_time_vietnam,
                previous_items=previous_items,
                validation_feedback=(
                    validation_feedback
                ),
            )

            try:
                response = (
                    generate_with_google_search(
                        client,
                        prompt,
                    )
                )

                if not response_used_google_search(
                    response
                ):
                    raise RuntimeError(
                        "Gemini không trả về "
                        "Google Search grounding metadata."
                    )

                payload = extract_json_payload(
                    getattr(
                        response,
                        "text",
                        "",
                    )
                )

                final_items = validate_ticker_items(
                    payload
                )

                break

            except Exception as error:
                last_error = error

                validation_feedback = (
                    validation_error_lines(
                        error
                    )
                )

                LOGGER.warning(
                    "Attempt %s failed: %s",
                    attempt,
                    " | ".join(
                        validation_feedback
                    ),
                )

        if final_items is None:
            raise RuntimeError(
                "Không tạo được bản tin hợp lệ "
                "sau hai lần. "
                "Ticker cũ được giữ nguyên. "
                f"Lỗi cuối: {last_error}"
            )

        publish_ticker(
            engine=engine,
            generated_at=run_time_vietnam,
            items=final_items,
        )

        LOGGER.info(
            "Published ticker with %s items.",
            len(final_items)
        )

        return 0

    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
