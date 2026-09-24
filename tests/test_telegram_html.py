"""Админский HTML не должен ронять parse_mode=HTML.

Импорт файла напрямую: `from bot.telegram_html` тянет bot/__init__.py
(polling, все роутеры) — это не юнит.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_telegram_html():
    path = Path(__file__).resolve().parents[1] / "bot" / "telegram_html.py"
    spec = importlib.util.spec_from_file_location("telegram_html_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_html = _load_telegram_html()
validate_telegram_html = _html.validate_telegram_html
safe_html_fragment = _html.safe_html_fragment


def test_validate_ok():
    assert validate_telegram_html("<b>ok</b>") is None


def test_validate_unclosed():
    err = validate_telegram_html("<b>ok")
    assert err is not None
    assert "Не закрыты" in err


def test_validate_extra_close():
    err = validate_telegram_html("ok</b>")
    assert err is not None
    assert "Лишний закрывающий" in err


def test_validate_forbidden_tag():
    err = validate_telegram_html("<script>x</script>")
    assert err is not None
    assert "script" in err.lower() or "Недопустимый" in err


def test_validate_nested_b_i():
    assert validate_telegram_html("<b><i>x</i></b>") is None


def test_safe_html_escape_invalid():
    raw = "<b>ok"
    assert safe_html_fragment(raw) == "&lt;b&gt;ok"
    assert safe_html_fragment("<b>ok</b>") == "<b>ok</b>"
