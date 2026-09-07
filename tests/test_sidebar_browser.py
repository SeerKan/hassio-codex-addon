"""Mobile composer regressions. Install browsers with playwright install chromium webkit."""

import json
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "codex_agent/src/codex_agent/static"
PHOTO = ROOT / "codex_agent/icon.png"
INGRESS_PATH = "/api/hassio_ingress/test/"


@pytest.fixture(scope="module", params=["chromium", "webkit"])
def browser(request):
    with sync_playwright() as playwright:
        instance = getattr(playwright, request.param).launch()
        yield instance
        instance.close()


@pytest.fixture
def sidebar(browser):
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    uploads = []
    runs = []
    behavior = {"upload": "ok"}
    html = (STATIC / "index.html").read_text()
    html = html.replace("__APP_VERSION__", "test").replace("__MODEL_OPTIONS__", "")
    html = html.replace("__APP_STYLES__", (STATIC / "styles.css").read_text())
    html = html.replace("__APP_SCRIPT__", (STATIC / "app.js").read_text())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, data, *, status=200, content_type="application/json"):
            body = data.encode() if isinstance(data, str) else json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.removeprefix(INGRESS_PATH)
            if not path:
                self.respond(html, content_type="text/html")
            elif path == "api/status":
                self.respond({
                    "user": {"id": "mobile-test", "username": "test"},
                    "auth": {"configured": True}, "settings": {}, "home_assistant": {},
                    "sessions": [], "runs": [],
                })
            else:
                self.respond({})

        def do_POST(self):
            path = self.path.removeprefix(INGRESS_PATH)
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if path == "api/attachments":
                message = BytesParser(policy=policy.default).parsebytes(
                    f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + body
                )
                part = next(message.iter_parts())
                uploaded = {
                    "filename": part.get_filename(), "bytes": part.get_payload(decode=True),
                }
                uploads.append(uploaded)
                if behavior["upload"] == "html":
                    self.respond("<html>Login required</html>", content_type="text/html")
                elif behavior["upload"] == "error":
                    self.respond({"detail": "Attachment is too large"}, status=413)
                elif behavior["upload"] == "offline":
                    self.close_connection = True
                else:
                    self.respond({"attachment": {
                        "id": f"image-{len(uploads)}", "filename": uploaded["filename"],
                        "kind": "image", "size_bytes": len(uploaded["bytes"]),
                    }})
            elif path == "api/runs":
                runs.append(json.loads(body))
                self.respond({"detail": "Test stops before running Codex"}, status=401)
            else:
                self.respond({})

        def do_DELETE(self):
            self.respond({})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    page.goto(f"http://127.0.0.1:{server.server_port}{INGRESS_PATH}")
    expect(page.locator("#haVersion")).to_contain_text("Add-on test")
    yield page, uploads, runs, behavior
    assert page_errors == []
    context.close()
    server.shutdown()
    server.server_close()
    thread.join()


def test_astra_fallback_selection_survives_reload_and_is_sent(sidebar):
    page, _, runs, _ = sidebar
    model_select = page.get_by_role("combobox", name="Codex model")
    expect(model_select).to_have_value("gpt-5.6-terra")
    model_select.select_option(label="GPT-6 Astra")
    page.reload()
    expect(model_select).to_have_value("gpt-6-astra")
    page.locator("#prompt").fill("Inspect the dashboard")
    with page.expect_response("**/api/runs"):
        page.get_by_role("button", name="Send", exact=True).click()
    assert runs[-1]["model"] == "gpt-6-astra"


def pick_photo(page):
    # Exercise the actual tap target; setting input files alone misses picker wiring bugs.
    with page.expect_file_chooser() as chooser:
        page.get_by_label("Attach files").tap()
    chooser.value.set_files(PHOTO)


def test_native_picker_repeated_upload_reload_and_send(sidebar):
    page, uploads, runs, _ = sidebar
    page.locator("#prompt").fill("Inspect this picture")
    pick_photo(page)
    expect(page.locator(".attachment-ready")).to_have_count(1)
    assert uploads[0]["bytes"] == PHOTO.read_bytes()
    assert uploads[0]["filename"] == PHOTO.name
    assert page.url.endswith(INGRESS_PATH)
    # Cancellation must not remove the attachment or prevent opening the picker again.
    with page.expect_file_chooser() as chooser:
        page.get_by_label("Attach files").tap()
    chooser.value.set_files([])
    pick_photo(page)
    expect(page.locator(".attachment-ready")).to_have_count(2)
    page.get_by_label("Remove icon.png").first.click()
    page.reload()
    expect(page.locator(".attachment-ready")).to_have_count(1)
    expect(page.locator("#prompt")).to_have_value("Inspect this picture")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.locator("#runState")).to_have_text("Request failed")
    assert runs[0]["attachment_ids"] == ["image-2"]


@pytest.mark.parametrize("failure", ["html", "error", "offline"])
def test_failed_upload_can_be_removed_and_retried(sidebar, failure):
    page, _, _, behavior = sidebar
    behavior["upload"] = failure
    pick_photo(page)
    expect(page.locator(".attachment-error")).to_have_count(1)
    expect(page.locator(".attachment-ready")).to_have_count(0)
    page.get_by_label("Remove icon.png").click()
    behavior["upload"] = "ok"
    pick_photo(page)
    expect(page.locator(".attachment-ready")).to_have_count(1)


def test_reload_marks_interrupted_upload_and_allows_retry(sidebar):
    page, _, _, _ = sidebar
    page.evaluate("""() => {
      window.fetch = () => new Promise(() => {});
    }""")
    pick_photo(page)
    expect(page.locator(".attachment-uploading")).to_have_count(1)
    page.reload()
    expect(page.locator(".attachment-error")).to_contain_text("interrupted by a page reload")
    page.get_by_label("Remove icon.png").click()
    pick_photo(page)
    expect(page.locator(".attachment-ready")).to_have_count(1)


def test_file_read_timeout_does_not_leave_composer_blocked(sidebar):
    page, _, _, _ = sidebar
    page.evaluate("""() => {
      window.originalArrayBuffer = File.prototype.arrayBuffer;
      File.prototype.arrayBuffer = () => new Promise(() => {});
      const originalTimeout = window.originalTimeout = window.setTimeout;
      window.setTimeout = (callback, delay, ...args) =>
        originalTimeout(callback, delay === 120000 ? 30 : delay, ...args);
    }""")
    pick_photo(page)
    expect(page.locator(".attachment-error")).to_contain_text("timed out")
    page.get_by_label("Remove icon.png").click()
    page.evaluate("""() => {
      File.prototype.arrayBuffer = window.originalArrayBuffer;
      window.setTimeout = window.originalTimeout;
    }""")
    pick_photo(page)
    expect(page.locator(".attachment-ready")).to_have_count(1)


def test_draft_is_scoped_to_authenticated_user(sidebar):
    page, _, _, _ = sidebar
    page.evaluate("""draft => {
      sessionStorage.setItem('codex_composer:another-user', JSON.stringify(draft));
    }""", {"prompt": "Private draft", "attachments": [{"id": "private", "status": "ready"}]})
    page.reload()
    expect(page.locator("#prompt")).to_have_value("")
    expect(page.locator("#attachmentTray")).to_be_hidden()


def test_reload_preserves_every_file_waiting_in_upload_queue(sidebar):
    page, _, _, _ = sidebar
    page.evaluate("() => { window.fetch = () => new Promise(() => {}); }")
    with page.expect_file_chooser() as chooser:
        page.get_by_label("Attach files").tap()
    chooser.value.set_files([
        {"name": f"photo-{number}.png", "mimeType": "image/png", "buffer": PHOTO.read_bytes()}
        for number in range(3)
    ])
    expect(page.locator(".attachment-uploading")).to_have_count(3)
    page.reload()
    expect(page.locator(".attachment-error")).to_have_count(3)
    for number in range(3):
        expect(page.get_by_label(f"Remove photo-{number}.png")).to_be_visible()


def test_removed_inflight_upload_does_not_reappear(sidebar):
    page, _, _, _ = sidebar
    page.evaluate("""() => {
      const originalFetch = window.fetch;
      window.fetch = (url, options) => {
        if (options?.method === 'POST' && String(url).endsWith('/api/attachments')) {
          return new Promise(resolve => {
            window.finishUpload = () => {
              window.finishUpload = null;
              resolve(new Response(JSON.stringify({
                attachment: {id: 'removed-image', filename: 'icon.png', kind: 'image'}
              }), {headers: {'content-type': 'application/json'}}));
            };
          });
        }
        return originalFetch(url, options);
      };
    }""")
    pick_photo(page)
    expect(page.locator(".attachment-uploading")).to_have_count(1)
    page.get_by_label("Remove icon.png").click()
    page.wait_for_function("typeof window.finishUpload === 'function'")
    with page.expect_request("**/api/attachments/removed-image") as deletion:
        page.evaluate("window.finishUpload()")
    assert deletion.value.method == "DELETE"
    expect(page.locator("#attachmentTray")).to_be_hidden()
    pick_photo(page)
    page.wait_for_function("typeof window.finishUpload === 'function'")
    page.evaluate("window.finishUpload()")
    expect(page.locator(".attachment-ready")).to_have_count(1)
