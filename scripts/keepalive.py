"""
Giữ app Streamlit Community Cloud luôn ở trạng thái thức.

Streamlit Cloud chỉ tính là "có traffic" khi có một WebSocket session thật sự
được mở từ trình duyệt. Một HTTP GET trả về 200 nhưng chỉ là khung HTML tĩnh,
tiến trình Python phía sau vẫn không chạy. Vì vậy script này dùng Chromium
headless để mở app như một người dùng thật.

Biến môi trường:
    APP_URL         Bắt buộc. URL app, ví dụ https://xxx.streamlit.app
                    Có thể khai báo nhiều URL, phân tách bằng dấu phẩy.
    HOLD_SECONDS    Tùy chọn. Số giây giữ session sau khi app render xong.
                    Mặc định 20.
    SHOT_DIR        Tùy chọn. Thư mục lưu ảnh chụp màn hình khi lỗi.
"""

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# Nút hiển thị trên trang ngủ của Streamlit Community Cloud.
WAKE_BUTTON_PATTERN = "get this app back up"

# Container chính của app, chỉ xuất hiện khi tiến trình Python đã chạy.
APP_READY_SELECTOR = '[data-testid="stAppViewContainer"]'

# Cold start của Streamlit Cloud có thể mất vài phút vì phải pip install lại.
APP_READY_TIMEOUT_MS = 240_000

WAKE_BUTTON_TIMEOUT_MS = 10_000
NAVIGATION_TIMEOUT_MS = 90_000


def read_app_urls() -> list[str]:
    raw_value = os.environ.get("APP_URL", "").strip()

    if not raw_value:
        raise SystemExit(
            "Thiếu biến môi trường APP_URL. "
            "Hãy khai báo secret STREAMLIT_APP_URL trong repo."
        )

    urls = [
        url.strip()
        for url in raw_value.split(",")
        if url.strip()
    ]

    return urls


def build_visit_url(app_url: str) -> str:
    """
    Thêm sẵn embed=true để app không phải tự rerun một lượt.

    app_cloud.py có enforce_embed_url() gọi st.rerun() khi URL chưa có tham số
    này. Truyền sẵn giúp phiên đánh thức tốn ít tài nguyên hơn.
    """
    if "embed=" in app_url:
        return app_url

    separator = "&" if "?" in app_url else "?"

    return f"{app_url}{separator}embed=true"


def save_failure_screenshot(page, app_url: str) -> None:
    shot_dir = os.environ.get("SHOT_DIR", "").strip()

    if not shot_dir:
        return

    try:
        output_dir = Path(shot_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = (
            app_url
            .replace("https://", "")
            .replace("http://", "")
            .replace("/", "_")
            .replace(":", "_")
            .replace("?", "_")
            .replace("&", "_")
            .replace("=", "_")
        )

        page.screenshot(
            path=str(output_dir / f"{safe_name}.png"),
            full_page=True
        )

    except Exception:
        # Ảnh chụp chỉ để debug, không được phép làm hỏng job.
        pass


def wake_single_app(browser, app_url: str, hold_seconds: int) -> str:
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
            "streamlit-keepalive"
        )
    )

    page = context.new_page()
    page.set_default_timeout(NAVIGATION_TIMEOUT_MS)

    try:
        page.goto(
            build_visit_url(app_url),
            wait_until="domcontentloaded",
            timeout=NAVIGATION_TIMEOUT_MS
        )

        status = "already_awake"

        # Nếu app đang ngủ, Streamlit hiện trang hibernate kèm nút đánh thức.
        wake_button = page.get_by_text(
            WAKE_BUTTON_PATTERN,
            exact=False
        ).first

        try:
            wake_button.wait_for(
                state="visible",
                timeout=WAKE_BUTTON_TIMEOUT_MS
            )
            wake_button.click()

            status = "was_sleeping"

        except PlaywrightTimeoutError:
            # Không có nút nghĩa là app vẫn đang chạy. Đây là trường hợp mong muốn.
            pass

        # Chờ tiến trình Python thật sự render ra giao diện.
        page.wait_for_selector(
            APP_READY_SELECTOR,
            timeout=APP_READY_TIMEOUT_MS
        )

        # Giữ WebSocket mở thêm một lúc để Streamlit Cloud ghi nhận traffic.
        page.wait_for_timeout(hold_seconds * 1_000)

        return status

    except (PlaywrightTimeoutError, PlaywrightError) as error:
        save_failure_screenshot(page, app_url)

        return f"failed: {type(error).__name__}"

    finally:
        context.close()


def main() -> int:
    app_urls = read_app_urls()

    hold_seconds = int(
        os.environ.get("HOLD_SECONDS", "20")
    )

    results: dict[str, str] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        try:
            for app_url in app_urls:
                started_at = time.monotonic()

                status = wake_single_app(
                    browser,
                    app_url,
                    hold_seconds
                )

                elapsed_seconds = time.monotonic() - started_at
                results[app_url] = status

                print(
                    f"[{status:<24}] {app_url} "
                    f"({elapsed_seconds:.1f}s)",
                    flush=True
                )

        finally:
            browser.close()

    failed_urls = [
        url
        for url, status in results.items()
        if status.startswith("failed")
    ]

    if failed_urls:
        print(
            f"\n{len(failed_urls)}/{len(results)} app không đánh thức được.",
            file=sys.stderr
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
