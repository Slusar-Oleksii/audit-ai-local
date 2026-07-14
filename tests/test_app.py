from pathlib import Path

import tomllib


def test_streamlit_is_bound_to_loopback():
    config_path = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["server"]["address"] == "127.0.0.1"
    assert config["server"]["enableXsrfProtection"] is True


def test_app_smoke(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUDIT_DATA_DIR", str(tmp_path / "app-data"))
    from audit_ai.config import get_settings

    get_settings.cache_clear()
    from streamlit.testing.v1 import AppTest

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=10)
    app.run()
    assert not app.exception
    assert any("Новий аудит" in item.value for item in app.markdown)

    app.text_input[0].set_value("UI тест")
    app.button[0].click().run()
    assert not app.exception
    assert len(app.file_uploader) == 1
    assert len(app.radio) == 1
    assert len(app.text_area) == 1
