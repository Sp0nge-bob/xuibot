"""Алиасы Happ crypto не сбрасываются в none."""
from __future__ import annotations

import pytest

from config.happ_crypto import normalize_happ_crypto_mode


@pytest.mark.parametrize("raw", ["crypt3", "rsa", "local", "crypt3_local"])
def test_normalize_crypt3_aliases(raw):
    assert normalize_happ_crypto_mode(raw) == "crypt3_local"


@pytest.mark.parametrize("raw", ["crypt4", "crypt4_local", "crypt4-local"])
def test_normalize_crypt4_alias_to_crypt3(raw):
    assert normalize_happ_crypto_mode(raw) == "crypt3_local"


@pytest.mark.parametrize("raw", ["crypt5", "api", "crypt5_api"])
def test_normalize_crypt5_aliases(raw):
    assert normalize_happ_crypto_mode(raw) == "crypt5_api"


@pytest.mark.parametrize("raw", ["none", "garbage", None, ""])
def test_normalize_none_and_junk(raw):
    assert normalize_happ_crypto_mode(raw) == "none"
