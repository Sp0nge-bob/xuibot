"""Offline regressions for the 2026-10-31 findings (synthetic credentials only)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from services import crypto


@pytest.fixture
def crypto_config(monkeypatch):
    cfg = SimpleNamespace(SECRET_KEY="", ENCRYPTION_KEY="", OLD_SECRET_KEY="")
    monkeypatch.setattr(crypto, "settings", cfg)
    monkeypatch.setattr(crypto, "_cached_fernet", None)
    monkeypatch.setattr(crypto, "_cached_candidates", None)
    return cfg


@pytest.mark.parametrize("secret", ["", *crypto.KNOWN_FALLBACK_SECRETS])
def test_bot007_no_public_active_encryption_key(crypto_config, secret):
    crypto_config.SECRET_KEY = secret
    with pytest.raises(ValueError, match="SECRET_KEY"):
        crypto.encrypt_secret("synthetic-node-password")


def test_bot007_invalid_explicit_key_never_falls_back(crypto_config):
    crypto_config.SECRET_KEY = "synthetic-nondefault-secret"
    crypto_config.ENCRYPTION_KEY = "invalid-synthetic-key"
    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        crypto.encrypt_secret("synthetic-node-password")


def test_bot007_explicit_key_and_configured_rotation(crypto_config):
    crypto_config.ENCRYPTION_KEY = Fernet.generate_key().decode()
    crypto_config.OLD_SECRET_KEY = "synthetic-previous-secret"
    value = crypto.encrypt_secret("synthetic-node-password")
    assert crypto.decrypt_secret(value) == "synthetic-node-password"
    previous = crypto._make_hkdf_fernet(crypto_config.OLD_SECRET_KEY)
    old = "enc:v1:" + previous.encrypt(b"synthetic-previous-password").decode()
    assert crypto.decrypt_secret(old) == "synthetic-previous-password"
    assert crypto.needs_reencryption(old)
    assert not crypto.needs_reencryption(value)


@pytest.mark.parametrize("derive", [crypto._make_hkdf_fernet, crypto._make_sha256_fernet])
def test_bot007_current_derived_ciphertexts_remain_readable(crypto_config, derive):
    crypto_config.SECRET_KEY = "synthetic-current-nondefault-key"
    token = "enc:v1:" + derive(crypto_config.SECRET_KEY).encrypt(b"legacy-password").decode()
    assert crypto.decrypt_secret(token) == "legacy-password"


def test_bot007_public_legacy_key_requires_explicit_migration_opt_in(crypto_config):
    crypto_config.ENCRYPTION_KEY = Fernet.generate_key().decode()
    old_key = crypto.KNOWN_FALLBACK_SECRETS[0]
    token = "enc:v1:" + crypto._make_hkdf_fernet(old_key).encrypt(b"legacy-password").decode()
    assert crypto.decrypt_secret(token) == ""
    crypto_config.OLD_SECRET_KEY = old_key
    crypto._cached_candidates = None
    assert crypto.decrypt_secret(token) == "legacy-password"


@pytest.mark.asyncio
async def test_cross001_bot_order_source_overrides_website_default(monkeypatch):
    from contextlib import asynccontextmanager
    import aiosqlite
    from db import database

    async with aiosqlite.connect(":memory:") as connection:
        await connection.execute("""CREATE TABLE orders (
            id INTEGER PRIMARY KEY, tg_id INTEGER, plan_id TEXT, plan_name TEXT,
            amount INTEGER, platega_tx_id TEXT, payment_method TEXT, order_type TEXT,
            promo_code TEXT, original_amount INTEGER, discount_amount INTEGER,
            payment_redirect TEXT, subscription_id INTEGER, sub_display_name TEXT,
            status TEXT, source TEXT DEFAULT 'web')""")

        @asynccontextmanager
        async def isolated_db():
            yield connection

        monkeypatch.setattr(database, "get_db", isolated_db)
        order_id = await database.create_order(7, "test-plan", "Test", 100, "synthetic-tx")
        async with connection.execute("SELECT source, status FROM orders WHERE id = ?", (order_id,)) as cursor:
            assert await cursor.fetchone() == ("bot", "pending")
