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
