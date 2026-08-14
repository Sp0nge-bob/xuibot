"""
Полный offline smoke на текущем Python (цель — 3.14).

Проверяет: compileall, импорт всех модулей, SQLite init/CRUD, QR, happ crypt3,
pricing/plans, keyboards/messages, FastAPI routes, dispatcher routers,
fulfillment helpers, webhook helpers — без Telegram polling и без панели 3x-ui.

Запуск:
  python scripts/dev/smoke_python314.py
"""
from __future__ import annotations

import asyncio
import compileall
import importlib
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Изолированная БД до импорта connection/settings-зависимых модулей
_TMP = Path(tempfile.mkdtemp(prefix="vpnbot314_"))
_DB = _TMP / "smoke.db"
os.environ["DB_PATH"] = str(_DB)
# Не трогаем реальный .env для токенов — settings уже загрузит .env если есть

FAILED: list[str] = []
PASSED: list[str] = []


def ok(name: str) -> None:
    PASSED.append(name)
    print(f"  OK  {name}")


def fail(name: str, exc: BaseException | None = None) -> None:
    FAILED.append(name)
    detail = f": {exc}" if exc else ""
    print(f"  FAIL  {name}{detail}")
    if exc:
        traceback.print_exc()


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check_python_version() -> None:
    section("Python")
    v = sys.version_info
    print(f"  {sys.version}")
    if v < (3, 11):
        fail("python>=3.11", RuntimeError(sys.version))
    elif v >= (3, 15):
        fail("python<3.15", RuntimeError(sys.version))
    else:
        ok(f"python {v.major}.{v.minor}.{v.micro}")


def check_compileall() -> None:
    section("compileall")
    for pkg in ("bot", "config", "db", "services", "ui"):
        path = ROOT / pkg
        if not path.is_dir():
            fail(f"compile {pkg}", FileNotFoundError(path))
            continue
        # quiet=1, force recompile for this interpreter
        good = compileall.compile_dir(str(path), quiet=1, force=True)
        if good:
            ok(f"compile {pkg}/")
        else:
            fail(f"compile {pkg}/")
    for mod in ("app.py", "run_bot.py", "run_all.py"):
        p = ROOT / mod
        if p.is_file():
            good = compileall.compile_file(str(p), quiet=1, force=True)
            if good:
                ok(f"compile {mod}")
            else:
                fail(f"compile {mod}")


def _iter_modules(package_dir: Path, package: str) -> list[str]:
    names: list[str] = []
    for path in sorted(package_dir.rglob("*.py")):
        if path.name == "__pycache__":
            continue
        rel = path.relative_to(package_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if rel.name == "__init__.py":
            if rel.parent == Path("."):
                names.append(package)
            else:
                names.append(package + "." + ".".join(rel.parent.parts))
        else:
            mod = package + "." + ".".join(rel.with_suffix("").parts)
            names.append(mod)
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def check_imports() -> None:
    section("imports (packages)")
    for pkg in ("bot", "config", "db", "services", "ui"):
        mods = _iter_modules(ROOT / pkg, pkg)
        errors = 0
        for name in mods:
            try:
                importlib.import_module(name)
            except Exception as e:
                errors += 1
                fail(f"import {name}", e)
        if errors == 0:
            ok(f"import all {pkg}.* ({len(mods)} modules)")


def check_third_party() -> None:
    section("third-party")
    pkgs = [
        "aiogram",
        "fastapi",
        "uvicorn",
        "pydantic",
        "pydantic_settings",
        "httpx",
        "cryptography",
        "qrcode",
        "PIL",
        "aiosqlite",
        "apscheduler",
        "loguru",
        "redis",
        "dotenv",
        "py3xui",
    ]
    for name in pkgs:
        try:
            m = importlib.import_module(name)
            ver = getattr(m, "__version__", "?")
            ok(f"{name} ({ver})")
        except Exception as e:
            fail(name, e)
    try:
        import psutil  # optional in requirements, used by process_stats

        ok(f"psutil ({psutil.__version__})")
    except Exception as e:
        fail("psutil", e)


async def check_db_and_domain() -> None:
    section("database + domain logic")
    from db.database import init_db
    from db import database as db
    from db import promo_codes as promo_db
    from config.plans import PLANS, get_plan
    from services.pricing import get_plan_quote, calc_discount
    from services.fulfillment import make_qr_photo
    from services.happ_crypto import encrypt_happ_subscription_link, get_happ_crypto_mode
    from services.fulfillment_text import (
        sub_link_standalone_message,
        panel_sync_notice_text,
    )
    from services.bot_restart import _RESTART_SUCCESS_RC
    from bot import messages
    from bot.states import UserStates, AdminStates
    from ui.theme import screen, money

    try:
        await init_db()
        ok("init_db")
    except Exception as e:
        fail("init_db", e)
        return

    try:
        # basic subscription path
        email = await db.allocate_client_email(900_001)
        assert email.startswith("tg"), email
        ok(f"allocate_client_email → {email}")
    except Exception as e:
        fail("allocate_client_email", e)

    plan = None
    try:
        plan = get_plan(PLANS[0]["id"])
        assert plan and plan["days"] > 0
        ok(f"get_plan {plan['id']}")
    except Exception as e:
        fail("get_plan", e)

    if plan:
        try:
            quote = await get_plan_quote(plan["id"], tg_id=900_001)
            assert quote is not None and quote.final_price >= 0
            d = calc_discount(1000, "percent", 10)
            assert d == 100
            ok(f"get_plan_quote → {quote.final_price}, calc_discount={d}")
        except Exception as e:
            fail("pricing quote", e)

    try:
        photo = make_qr_photo("https://example.com/sub/test", "smoke.png")
        assert photo is not None
        ok("make_qr_photo")
    except Exception as e:
        fail("make_qr_photo", e)

    try:
        mode = await get_happ_crypto_mode()
        plain = "https://example.com/api/v4/sub/smoketest123"
        encrypted = await encrypt_happ_subscription_link(plain)
        assert encrypted
        ok(f"happ_crypto mode={mode} len={len(encrypted)}")
    except Exception as e:
        fail("happ_crypto", e)

    try:
        assert panel_sync_notice_text(3)
        assert sub_link_standalone_message("happ://crypt3/" + "A" * 100) is not None
        ok("fulfillment_text helpers")
    except Exception as e:
        fail("fulfillment_text", e)

    try:
        assert 0 in _RESTART_SUCCESS_RC
        ok(f"bot_restart success codes {_RESTART_SUCCESS_RC}")
    except Exception as e:
        fail("bot_restart codes", e)

    try:
        from bot.keyboards import main_menu_kb

        kb = main_menu_kb()
        assert kb is not None
        ok("keyboards.main_menu_kb")
    except Exception as e:
        fail("keyboards", e)

    try:
        text = messages.promo_enter_text()
        assert "Промокод" in text or "промо" in text.lower()
        ok("messages.promo_enter_text")
    except Exception as e:
        fail("messages", e)

    try:
        assert UserStates.waiting_promo_code
        assert AdminStates
        ok("FSM states")
    except Exception as e:
        fail("FSM states", e)

    try:
        s = screen("Title", "body")
        assert "Title" in s
        assert money(100)
        ok("ui.theme")
    except Exception as e:
        fail("ui.theme", e)

    # promo CRUD smoke
    try:
        promo = await promo_db.create_promo_code(
            code="SMOKE314",
            discount_type="percent",
            discount_value=10,
            max_uses=5,
            per_user_limit=1,
            valid_days=30,
            promo_type="discount",
        )
        loaded = await promo_db.get_promo_by_code("SMOKE314")
        assert loaded and loaded["id"] == promo["id"]
        ok(f"promo create/get id={promo['id']}")
    except Exception as e:
        fail("promo CRUD", e)

    # subscription lifecycle (DB only — без панели)
    try:
        import uuid as uuid_mod

        email2 = await db.allocate_client_email(900_002)
        sub_id = await db.create_subscription(
            900_002,
            None,
            inbound_id=1,
            client_email=email2,
            client_uuid=str(uuid_mod.uuid4()),
            sub_id="smoke314sub",
            days=30,
            traffic_gb=0,
            display_name="Smoke 314",
        )
        new_end = await db.extend_subscription_record(sub_id, 7)
        await db.add_grant_bonus_days(sub_id, 3)
        sub = await db.get_subscription_by_id(sub_id)
        assert sub and sub["is_active"]
        assert new_end
        ok(f"subscription create/extend/bonus id={sub_id} end={sub['end_date'][:10]}")
    except Exception as e:
        fail("subscription lifecycle", e)

    try:
        from services.process_stats import BotLoadSnapshot, _fmt_cpu

        assert "0" in _fmt_cpu(0.0) or "менее" in _fmt_cpu(0.0)
        ok("process_stats helpers")
    except Exception as e:
        fail("process_stats", e)


def check_fastapi_and_dispatcher() -> None:
    section("FastAPI + aiogram dispatcher")
    try:
        # Import app module carefully: it calls warn_unsafe and install hooks
        import app as app_module

        assert app_module.app is not None
        routes = [getattr(r, "path", None) for r in app_module.app.routes]
        paths = [p for p in routes if p]
        ok(f"FastAPI app routes={len(paths)}")
        # webhook route should exist
        if any("platega" in (p or "").lower() or "webhook" in (p or "").lower() or "health" in (p or "").lower() for p in paths):
            ok(f"routes include health/webhook: {paths}")
        else:
            ok(f"routes sample: {paths[:8]}")

        # health payload без lifespan (без HTTP к Primary)
        payload_ok = app_module._health_payload(primary_ok=True)
        payload_bad = app_module._health_payload(primary_ok=False)
        assert payload_ok["status"] == "ok"
        assert payload_bad["status"] == "unavailable"
        assert "fulfillment" in payload_ok and "webhook" in payload_ok
        ok(f"health payload ok/unavailable keys={sorted(payload_ok)}")
    except Exception as e:
        fail("FastAPI app", e)

    try:
        from bot import dp

        # routers already included at import
        assert dp is not None
        observers = getattr(dp, "observers", None) or {}
        ok(f"aiogram Dispatcher (observers={len(observers) if hasattr(observers, '__len__') else '?'})")
    except Exception as e:
        fail("Dispatcher", e)

    try:
        import run_bot  # noqa: F401
        import run_all  # noqa: F401

        ok("entrypoints run_bot/run_all importable")
    except Exception as e:
        fail("entrypoints", e)


async def check_async_services() -> None:
    section("async services (no network)")
    try:
        from services.webhook_guard import webhook_rate_limited

        limited = webhook_rate_limited("127.0.0.1")
        assert limited is False or limited is True
        ok(f"webhook_rate_limited → {limited}")
    except Exception as e:
        fail("webhook_guard", e)

    try:
        from services.platega import normalize_platega_status

        st = normalize_platega_status("CONFIRMED")
        ok(f"normalize_platega_status → {st}")
    except Exception as e:
        fail("platega.normalize", e)

    try:
        from services.secondary_node_notice import get_secondary_node_notice

        notice = await get_secondary_node_notice()
        ok(f"secondary_node_notice → {notice!r}")
    except Exception as e:
        fail("secondary_node_notice", e)

    try:
        from services.fulfillment_queue import enqueue_webhook_job

        # just ensure callable exists
        assert callable(enqueue_webhook_job)
        ok("fulfillment_queue API")
    except Exception as e:
        fail("fulfillment_queue", e)

    try:
        from services.promo_redeem import redeem_promo_code
        from services.grant_promo import grant_promo_choice_text

        assert callable(redeem_promo_code)
        assert callable(grant_promo_choice_text)
        ok("promo redeem/grant APIs")
    except Exception as e:
        fail("promo APIs", e)


async def check_settings() -> None:
    section("settings")
    try:
        from config.settings import settings

        assert settings.BOT_TOKEN  # from .env
        assert settings.XUI_HOST
        ok(f"settings loaded brand={settings.BOT_BRAND!r}")
        ok(f"requires env OK (token len={len(settings.BOT_TOKEN)})")
    except Exception as e:
        fail("settings", e)


def main() -> int:
    print(f"ROOT={ROOT}")
    print(f"DB_PATH={_DB}")
    check_python_version()
    check_compileall()
    check_third_party()
    check_imports()

    async def _run() -> None:
        await check_settings()
        await check_db_and_domain()
        await check_async_services()
        # FastAPI last — heavier imports
        check_fastapi_and_dispatcher()

    asyncio.run(_run())

    section("summary")
    print(f"  passed: {len(PASSED)}")
    print(f"  failed: {len(FAILED)}")
    if FAILED:
        print("  failures:")
        for name in FAILED:
            print(f"    - {name}")
        code = 1
    else:
        print("  ALL GREEN on", sys.version.split()[0])
        code = 0
    # app.py ставит uvicorn/logging hooks — иначе процесс может не завершиться
    try:
        from db.connection import close_connection

        asyncio.run(close_connection())
    except Exception:
        pass
    return code


if __name__ == "__main__":
    code = main()
    # жёсткий выход: atexit/hooks от webhook-логирования
    os._exit(code)
