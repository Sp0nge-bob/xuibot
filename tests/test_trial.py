"""Пробные клиенты: email tgfree{tg_id}."""
from __future__ import annotations

from config.trial import is_trial_email, trial_client_email


def test_trial_client_email():
    assert trial_client_email(42) == "tgfree42"


def test_is_trial_email_true():
    assert is_trial_email("tgfree1") is True


def test_is_trial_email_regular():
    assert is_trial_email("user@node") is False
    assert is_trial_email("tg123") is False


def test_is_trial_email_empty():
    assert is_trial_email(None) is False
    assert is_trial_email("") is False
