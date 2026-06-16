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

    assert (
        '<base href="${safePath}"><link rel="stylesheet" href="static/styles.css?v=${version}">'
        in index
    )
    assert 'src="static/app.js?v=${window.CODEX_AGENT_VERSION}"' in index
    assert "__MODEL_OPTIONS__" in index
    assert "FALLBACK_MODEL_OPTIONS" in app
    assert "document.baseURI" in app
