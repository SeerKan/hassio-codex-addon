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
    preferences = {}
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
                    "preferences": preferences,
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
                run = json.loads(body)
                runs.append(run)
                if not run["approved"]:
                    preferences.update({
                        key: run[key] for key in ("mode", "model", "reasoning_effort")
                    })
                    preferences["persisted"] = True
                self.respond({"detail": "Test stops before running Codex"}, status=401)
            elif path == "api/preferences":
                preferences.update(json.loads(body))
                preferences["persisted"] = True
                self.respond({"preferences": preferences})
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


def install_fake_speech_recognition(page):
    page.add_init_script("""(() => {
      class FakeRecognition {
        constructor() { window.mockSpeech = this; }
        start() { if (!window.fakeSpeechNoStart) this.onstart?.(); }
        stop() { this.onend?.(); }
        abort() { this.onend?.(); }
        emit(results, resultIndex = 0) {
          this.onresult?.({results: results.map(([transcript, isFinal]) => ({
            0: {transcript}, isFinal
          })), resultIndex});
        }
        fail(error) { this.onerror?.({error}); this.onend?.(); }
      }
      window.SpeechRecognition = FakeRecognition;
      window.webkitSpeechRecognition = FakeRecognition;
    })()""")
    page.reload()


def test_dictation_appends_final_words_to_editable_draft_without_sending(sidebar):
    page, _, runs, _ = sidebar
    install_fake_speech_recognition(page)
    page.get_by_label("Dictation language").select_option("ro-RO")
    page.locator("#prompt").fill("Please")
    page.get_by_role("button", name="Dictate").click()
    assert page.evaluate("window.mockSpeech.lang") == "ro-RO"
    expect(page.get_by_role("button", name="Stop")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_label("Dictation language")).to_be_disabled()
    page.evaluate("window.mockSpeech.emit([['aprinde lumina', false]])")
    expect(page.locator("#dictationStatus")).to_contain_text("aprinde lumina")
    expect(page.locator("#prompt")).to_have_value("Please")
    page.evaluate("window.mockSpeech.emit([['aprinde lumina', true]])")
    page.evaluate("window.mockSpeech.emit([['aprinde lumina', true], ['în bucătărie', true]], 0)")
    expect(page.locator("#prompt")).to_have_value("Please aprinde lumina în bucătărie")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.locator("#dictationStatus")).to_contain_text("Stop dictation")
    assert runs == []
    page.get_by_role("button", name="Stop").click()
    expect(page.locator("#prompt")).to_have_value("Please aprinde lumina în bucătărie")
    page.reload()
    expect(page.locator("#prompt")).to_have_value("Please aprinde lumina în bucătărie")
    expect(page.get_by_label("Dictation language")).to_have_value("ro-RO")
    with page.expect_response("**/api/runs"):
        page.get_by_role("button", name="Send", exact=True).click()
    assert runs[-1]["prompt"] == "Please aprinde lumina în bucătărie"


def test_dictation_replaces_selected_draft_text(sidebar):
    page, _, _, _ = sidebar
    install_fake_speech_recognition(page)
    page.locator("#prompt").fill("Please old command now")
    page.locator("#prompt").evaluate(
        "element => { element.selectionStart = 7; element.selectionEnd = 18; }"
    )
    page.get_by_role("button", name="Dictate").click()
    page.evaluate("window.mockSpeech.emit([['turn on the lights', true]])")
    expect(page.locator("#prompt")).to_have_value("Please turn on the lights now")
    page.get_by_role("button", name="Stop").click()
    expect(page.get_by_label("Dictation language")).to_be_enabled()


def test_dictation_permission_error_is_visible_and_draft_survives(sidebar):
    page, _, runs, _ = sidebar
    install_fake_speech_recognition(page)
    page.locator("#prompt").fill("Existing draft")
    page.get_by_role("button", name="Dictate").click()
    page.evaluate("window.mockSpeech.fail('not-allowed')")
    expect(page.locator("#dictationStatus")).to_contain_text("Microphone access was denied")
    expect(page.get_by_role("button", name="Dictate")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#prompt")).to_have_value("Existing draft")
    assert runs == []


def test_dictation_unsupported_browser_offers_keyboard_fallback(sidebar):
    page, _, _, _ = sidebar
    page.add_init_script("""(() => {
      window.SpeechRecognition = undefined;
      window.webkitSpeechRecognition = undefined;
    })()""")
    page.reload()
    expect(page.get_by_role("button", name="Dictate")).to_be_disabled()
    expect(page.locator("#dictationStatus")).to_contain_text("keyboard's microphone")


def test_dictation_start_timeout_recovers_when_embedded_browser_stalls(sidebar):
    page, _, _, _ = sidebar
    install_fake_speech_recognition(page)
    page.evaluate("""() => {
      window.fakeSpeechNoStart = true;
      const original = window.setTimeout;
      window.setTimeout = (callback, delay, ...args) =>
        original(callback, delay === 10000 ? 30 : delay, ...args);
    }""")
    page.get_by_role("button", name="Dictate").click()
    expect(page.locator("#dictationStatus")).to_contain_text("microphone did not start")
    expect(page.get_by_role("button", name="Dictate")).to_be_enabled()


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


def test_latest_model_and_intensity_persist_on_server_and_are_sent(sidebar):
    page, _, runs, _ = sidebar
    model = page.get_by_role('combobox', name='Codex model')
    intensity = page.get_by_role('combobox', name='Thinking intensity')
    expect(intensity).to_have_value('medium')
    model.select_option('gpt-6.1-sol')
    with page.expect_response('**/api/preferences'):
        intensity.select_option('ultra')
    # Clear browser choices to prove that per-user server preferences restore them.
    page.evaluate('() => { sessionStorage.clear(); localStorage.clear(); }')
    page.reload()
    expect(model).to_have_value('gpt-6.1-sol')
    expect(intensity).to_have_value('ultra')
    page.locator('#prompt').fill('Inspect the dashboard')
    with page.expect_response('**/api/runs'):
        page.get_by_role('button', name='Send', exact=True).click()
    assert runs[-1]['model'] == 'gpt-6.1-sol'
    assert runs[-1]['reasoning_effort'] == 'ultra'
    model.select_option('gpt-6-luna')
    expect(intensity).to_have_value('medium')
    expect(intensity.locator('option[value=ultra]')).to_have_count(0)
    intensity.select_option('max')
    expect(intensity).to_have_value('max')
    model.select_option('gpt-5.5')
    expect(intensity).to_have_value('medium')
    expect(intensity.locator('option[value=max]')).to_have_count(0)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')


def test_approval_retry_preserves_original_model_and_intensity(sidebar):
    page, _, _, _ = sidebar
    requests = []

    def respond(route):
        body = route.request.post_data_json
        requests.append(body)
        if not body['approved']:
            route.fulfill(status=409, json={'detail': {'assessment': {
                'warning': 'Review changes', 'reasons': ['Test approval'],
            }}})
        else:
            route.fulfill(status=401, json={'detail': 'Test stops before running Codex'})

    page.route('**/api/runs', respond)
    page.get_by_role('combobox', name='Codex model').select_option('gpt-6.1-sol')
    page.get_by_role('combobox', name='Thinking intensity').select_option('high')
    page.locator('#prompt').fill('Change the dashboard')
    page.get_by_role('button', name='Send', exact=True).click()
    expect(page.get_by_role('button', name='Approve and send')).to_be_visible()
    page.get_by_role('combobox', name='Thinking intensity').select_option('low')
    page.get_by_role('button', name='Approve and send').click()
    expect(page.locator('#runState')).to_have_text('Request failed')
    assert len(requests) == 2
    assert requests[1]['approved'] is True
    assert requests[1]['model'] == 'gpt-6.1-sol'
    assert requests[1]['reasoning_effort'] == 'high'


def test_new_user_does_not_inherit_another_users_intensity(sidebar):
    page, _, _, _ = sidebar
    page.evaluate("""() => {
      localStorage.setItem('codex_reasoning_effort:another-user', 'ultra');
      localStorage.setItem('codex_reasoning_effort', 'ultra');
    }""")
    page.reload()
    expect(page.get_by_role('combobox', name='Thinking intensity')).to_have_value('medium')


def test_delayed_preference_save_cannot_overwrite_newer_selection_or_send(sidebar):
    page, _, runs, _ = sidebar
    page.evaluate("""() => {
      const originalFetch = window.fetch;
      window.preferenceRequestCount = 0;
      window.fetch = (url, options) => {
        if (options?.method === 'POST' && String(url).endsWith('/api/preferences')) {
          window.preferenceRequestCount += 1;
          if (window.preferenceRequestCount === 1) {
            return new Promise((resolve, reject) => {
              window.finishPreference = () => originalFetch(url, options).then(resolve, reject);
            });
          }
        }
        return originalFetch(url, options);
      };
    }""")
    model = page.get_by_role('combobox', name='Codex model')
    intensity = page.get_by_role('combobox', name='Thinking intensity')
    model.select_option('gpt-6.1-sol')
    page.wait_for_function("typeof window.finishPreference === 'function'")
    intensity.select_option('high')
    page.locator('#prompt').fill('Inspect entities')
    page.get_by_role('button', name='Send', exact=True).click()
    intensity.select_option('low')
    assert page.evaluate('window.preferenceRequestCount') == 1
    assert runs == []
    with page.expect_response(lambda response: (
        response.url.endswith('/api/preferences')
        and response.request.post_data_json.get('reasoning_effort') == 'low'
    )):
        page.evaluate('window.finishPreference()')
    assert runs[-1]['reasoning_effort'] == 'high'
    page.evaluate('() => { sessionStorage.clear(); localStorage.clear(); }')
    page.reload()
    expect(model).to_have_value('gpt-6.1-sol')
    expect(intensity).to_have_value('low')
