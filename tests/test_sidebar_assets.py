from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sidebar_does_not_clear_home_assistant_origin_cache() -> None:
    main = (ROOT / "codex_agent/src/codex_agent/main.py").read_text(encoding="utf-8")
    index = (ROOT / "codex_agent/src/codex_agent/static/index.html").read_text(encoding="utf-8")

    assert "Clear-Site-Data" not in main
    assert "window.caches" not in index
    assert "caches.delete" not in index


def test_sidebar_has_ingress_base_and_model_fallbacks() -> None:
    index = (ROOT / "codex_agent/src/codex_agent/static/index.html").read_text(encoding="utf-8")
    app = (ROOT / "codex_agent/src/codex_agent/static/app.js").read_text(encoding="utf-8")

    assert '<base href="${safePath}">' in index
    assert "__APP_STYLES__" in index
    assert "__APP_SCRIPT__" in index
    assert "static/app.js?v=" not in index
    assert "static/styles.css?v=" not in index
    assert "__MODEL_OPTIONS__" in index
    assert "FALLBACK_MODEL_OPTIONS" in app
    assert "document.baseURI" in app


def test_sidebar_presents_sessions_instead_of_recent_runs() -> None:
    index = (ROOT / "codex_agent/src/codex_agent/static/index.html").read_text(encoding="utf-8")
    app = (ROOT / "codex_agent/src/codex_agent/static/app.js").read_text(encoding="utf-8")

    assert "Recent runs" not in index
    assert 'id="sessionsList"' in index
    assert 'class="asset-compat" hidden aria-hidden="true"' in index
    assert 'id="runsList" class="runs-list legacy-runs-list"' in index
    assert index.index('id="sessionsList"') < index.index('class="asset-compat"')
    assert 'id="sessionSelect"' in index
    assert "renderSessionsList" in app
    assert "ensureCompatibilityNodes" in app
    assert "refreshSessionRuns" not in app


def test_sidebar_keyboard_and_preferences_wiring() -> None:
    app = (ROOT / "codex_agent/src/codex_agent/static/app.js").read_text(encoding="utf-8")

    assert "function handlePromptKeydown" in app
    assert "function insertTextareaNewline" in app
    assert 'event.key !== "Enter"' in app
    assert "event.ctrlKey || event.metaKey" in app
    assert "insertTextareaNewline(event.currentTarget)" in app
    assert "form.requestSubmit()" in app
    assert '"api/preferences"' in app
    assert "preferences.persisted" in app
    assert "{ persist: true, userChanged: true }" in app


def test_sidebar_has_attachment_upload_wiring() -> None:
    index = (ROOT / "codex_agent/src/codex_agent/static/index.html").read_text(encoding="utf-8")
    app = (ROOT / "codex_agent/src/codex_agent/static/app.js").read_text(encoding="utf-8")
    styles = (ROOT / "codex_agent/src/codex_agent/static/styles.css").read_text(encoding="utf-8")

    assert 'id="attachButton"' in index
    assert 'id="fileInput" type="file" multiple hidden' in index
    assert 'id="attachmentTray"' in index
    assert "function uploadFiles" in app
    assert "api/attachments" in app
    assert "attachment_ids" in app
    assert "Wait for file conversion to finish" in app
    assert ".attachment-chip" in styles


def test_markitdown_is_shipped_without_alpine_onnxruntime_dependency() -> None:
    dockerfile = (ROOT / "codex_agent/Dockerfile").read_text(encoding="utf-8")
    requirements = (ROOT / "codex_agent/requirements.txt").read_text(encoding="utf-8")
    shim = (ROOT / "codex_agent/src/magika.py").read_text(encoding="utf-8")

    assert "--no-deps \"markitdown==${MARKITDOWN_VERSION}\"" in dockerfile
    assert "markitdown[" not in requirements
    assert "onnxruntime" not in requirements
    assert 'label="unknown"' in shim


def test_home_assistant_mcp_is_shipped_inside_addon() -> None:
    dockerfile = (ROOT / "codex_agent/Dockerfile").read_text(encoding="utf-8")
    wrapper = (ROOT / "codex_agent/ha-mcp-stdio.sh").read_text(encoding="utf-8")

    assert "ARG HA_MCP_VERSION=7.8.1" in dockerfile
    assert "env -u UV_EXTRA_INDEX_URL -u PIP_EXTRA_INDEX_URL" in dockerfile
    assert "uv tool install --python 3.13 \"ha-mcp==${HA_MCP_VERSION}\"" in dockerfile
    assert "COPY ha-mcp-stdio.sh /usr/local/bin/ha-mcp-stdio" in dockerfile
    assert 'HOMEASSISTANT_URL="${HOMEASSISTANT_URL:-http://supervisor/core}"' in wrapper
    assert 'HOMEASSISTANT_TOKEN="${SUPERVISOR_TOKEN}"' in wrapper
    assert 'READ_ONLY_MODE="${READ_ONLY_MODE:-true}"' in wrapper
    assert 'READ_ONLY_MODE="${READ_ONLY_MODE:-false}"' in wrapper
