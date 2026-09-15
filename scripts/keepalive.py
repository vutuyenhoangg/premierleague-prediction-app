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
# Streamlit đổi data-testid qua các phiên bản nên chấp nhận nhiều biến thể.
APP_READY_SELECTOR = ", ".join(
    [
        '[data-testid="stAppViewContainer"]',
        '[data-testid="stApp"]',
        '[data-testid="stMain"]',
        "section.main"
    ]
)

# Dấu hiệu app bị đặt ở chế độ riêng tư và đang đòi đăng nhập.
PRIVATE_APP_MARKERS = (
    "sign in to streamlit",
    "continue with google",
    "this app is private",
    "you do not have access",
    "request access"
)

# Cold start của Streamlit Cloud có thể mất vài phút vì phải pip install lại.
APP_READY_TIMEOUT_MS = 240_000

WAKE_BUTTON_TIMEOUT_MS = 10_000

# Khi app đang ngủ, Streamlit Cloud giữ kết nối trong lúc dựng lại container
# nên request đầu tiên có thể rất lâu. Timeout ở đây không còn là lỗi chí mạng:
# trang vẫn tiếp tục tải ngầm và được kiểm tra lại ở bước sau.
NAVIGATION_TIMEOUT_MS = 180_000


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


def page_has_real_content(page) -> bool:
    """
    Kiểm tra mềm khi selector chính không khớp trong thời gian cho phép.

    Streamlit đổi data-testid giữa các phiên bản, và trang có thể render xong
    ngay sau khi timeout hết hạn. Nếu body đã có nội dung thật và không phải
    trang ngủ hay trang đăng nhập của Streamlit Cloud thì coi như app đã thức.
    """
    try:
        body_text = page.inner_text("body", timeout=10_000)
    except Exception:
        return False

    normalized_text = " ".join(body_text.split())

    if len(normalized_text) < 60:
        return False

    lowered_text = normalized_text.casefold()

    if WAKE_BUTTON_PATTERN in lowered_text:
        return False

    if any(
        marker in lowered_text
        for marker in PRIVATE_APP_MARKERS
    ):
        return False

    return True


def wait_until_app_rendered(page, timeout_ms: int) -> str:
    """
    Trả về nhãn trạng thái, hoặc ném lỗi nếu app thật sự chưa render.
    """
    try:
        page.wait_for_selector(
            APP_READY_SELECTOR,
            timeout=timeout_ms
        )
        return "ready"

    except PlaywrightTimeoutError:
        # Cho trang thêm một nhịp rồi kiểm tra bằng nội dung thực tế.
        page.wait_for_timeout(10_000)

        if page_has_real_content(page):
            return "ready_by_content"

        raise


def describe_page(page) -> str:
    """
    In ra đủ thông tin để biết trình duyệt đang đứng ở đâu khi lỗi.

    Nhờ vậy log của GitHub Actions tự nói lên nguyên nhân, không cần
    tải artifact ảnh chụp về xem thủ công.
    """
    lines: list[str] = []

    try:
        lines.append(f"  url   : {page.url}")
    except Exception:
        lines.append("  url   : <không đọc được>")

    try:
        lines.append(f"  title : {page.title()}")
    except Exception:
        lines.append("  title : <không đọc được>")

    body_text = ""

    try:
        body_text = page.inner_text("body", timeout=5_000)
    except Exception:
        try:
            body_text = page.content()[:1_000]
        except Exception:
            body_text = ""

    normalized_text = " ".join(body_text.split())

    if normalized_text:
        lines.append(f"  text  : {normalized_text[:400]}")
    else:
        lines.append("  text  : <trang trống hoặc chưa render>")

    lowered_text = normalized_text.casefold()

    matched_markers = [
        marker
        for marker in PRIVATE_APP_MARKERS
        if marker in lowered_text
    ]

    if matched_markers:
        lines.append(
            "  chẩn đoán: app đang ở chế độ riêng tư và yêu cầu đăng nhập. "
            "Vào share.streamlit.io, mở Settings > Sharing của app "
            'và đặt thành "Public".'
        )

    return "\n".join(lines)


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
        try:
            page.goto(
                build_visit_url(app_url),
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS
            )

        except PlaywrightTimeoutError:
            # App đang cold start. Trang vẫn tải tiếp ở nền nên đi tiếp
            # thay vì bỏ cuộc ở đây.
            print(
                "  (điều hướng chậm, có thể app đang khởi động lại)",
                flush=True
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

            # Trang hibernate sẽ tự tải lại sau khi bấm.
            page.wait_for_timeout(5_000)

        except PlaywrightTimeoutError:
            # Không có nút nghĩa là app vẫn đang chạy. Đây là trường hợp mong muốn.
            pass

        # Chờ tiến trình Python thật sự render ra giao diện.
        render_status = wait_until_app_rendered(
            page,
            APP_READY_TIMEOUT_MS
        )

        if render_status == "ready_by_content":
            status = f"{status}+soft_check"

        # Giữ WebSocket mở thêm một lúc để Streamlit Cloud ghi nhận traffic.
        page.wait_for_timeout(hold_seconds * 1_000)

        return status

    except (PlaywrightTimeoutError, PlaywrightError) as error:
        print(
            f"\nLỗi khi xử lý {app_url}: {type(error).__name__}",
            flush=True
        )
        print(describe_page(page), flush=True)

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
