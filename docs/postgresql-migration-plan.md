[← Документация](README.md) · [Архитектура](architecture.md) · [Системные требования](requirements.md) · [Redis — план](redis-migration-plan.md) · [Деплой](deployment.md)

---

# План перехода бота на PostgreSQL (опционально)

Поэтапный план на случай, когда SQLite перестанет быть достаточным. **Сейчас код не меняем** — документ для будущей реализации.

**Главная цель:** сохранить простой деплой на SQLite для малых инсталляций и дать переключатель на PostgreSQL для крупного прода (конкурентная запись, multi-instance, нормальные бэкапы).

---

## Два разных PostgreSQL в экосистеме

У проекта **две независимые** базы данных:

| Система | Что хранит | Сейчас | При росте |
|---------|------------|--------|-----------|
| **VPN-бот** (`db/`) | пользователи, заказы, подписки (метаданные), тикеты, промо, ноды в БД | SQLite `data/bot.db` | опционально PostgreSQL (этот план) |
| **3x-ui** (панель) | клиенты VPN, трафик, инбаунды на панели | обычно SQLite в панели | [3x-ui поддерживает PostgreSQL](https://github.com/MHSanaei/3x-ui) при больших объёмах |

Переход панели на PG и переход бота на PG **не связаны одним переключателем**, но на крупных инсталляциях часто делают **оба**: панель упирается в объём клиентов/трафика, бот — в конкурентные оплаты и несколько процессов.

```mermaid
flowchart TB
    subgraph bot_stack [VPN Bot VPS]
        TG[run_bot.py]
        WEB[app.py]
        BOTDB[(bot OLTP)]
        REDIS[(Redis FSM)]
        TG --> BOTDB
        WEB --> BOTDB
        TG --> REDIS
    end
    subgraph panel_stack [3x-ui серверы]
        P1[Primary panel]
        P2[Secondary panels]
        PANELDB[(panel DB)]
        P1 --> PANELDB
        P2 --> PANELDB
    end
    TG -->|API| P1
    WEB -->|fulfillment| P1
```

**Важно:** бот не заменяет БД панели — он хранит свой каталог подписок и заказы. При планировании PG для бота отдельно оценивайте, нужен ли PG уже на стороне 3x-ui (см. документацию и нагрузку панели).

---

## Когда SQLite ещё достаточно

Оставляйте SQLite по умолчанию, если выполняются **все** условия:

- один VPS (или один webhook + один telegram-процесс);
- до **~3000–5000 активных подписок** (см. [requirements.md](requirements.md));
- нет `database is locked` / таймаутов `busy_timeout` в логах;
- бэкап файлом `bot.db` устраивает по RPO/RTO.

По [requirements.md](requirements.md) при росте первым узким местом часто становится **панель 3x-ui**, а не `bot.db` (~1–5 MB на 1000 подписок). PostgreSQL для бота имеет смысл, когда упираетесь именно в **OLTP бота** или в **архитектуру** (несколько инстансов).

---

## Когда пора открывать этот план

Переходите к Phase 1+, если есть **хотя бы один** триггер:

| Триггер | Почему PG |
|---------|-----------|
| Регулярные `database is locked` / SQLite `busy` в `app.py` или `run_bot.py` | два процесса + пики webhook |
| План **2+ инстансов** `app.py` (горизонтальный webhook) | общая идемпотентность заказов и `webhook_dedup` |
| План **2+ polling** (редко; нужен Redis lock из [redis-migration-plan.md](redis-migration-plan.md)) | общее состояние в БД |
| Админ-отчёты / тяжёлые выборки мешают оплатам | PG лучше разделяет read/write |
| Требования DR: PITR, реплика, `pg_dump` по расписанию | файловый бэкап SQLite неудобен |
| Организационный стандарт «прод = Postgres» | единый ops-стек |

**Порог «мало / много»** для бота: не «все пользователи Telegram», а **активные подписки + частота оплат + число процессов**.

---

## Текущее состояние кода (аудит)

| Компонент | Файл | Заметки |
|-----------|------|---------|
| Подключение | [`db/connection.py`](../db/connection.py) | один `aiosqlite` connection + **глобальный `asyncio.Lock`** на каждый `get_db()` |
| Init схемы | [`db/database.py`](../db/database.py) | `CREATE TABLE`, миграции через `PRAGMA table_info` |
| Модули SQL | `db/*.py` (**14 файлов**) | сотни вызовов `get_db`, плейсхолдеры `?` |
| SQLite-only | многие модули | `AUTOINCREMENT`, `sqlite_master`, `aiosqlite.IntegrityError` |
| Межпроцессный init | [`db/init_lock.py`](../db/init_lock.py) | файловый `.init.lock` |
| Бэкап | [`services/backup.py`](../services/backup.py) | `sqlite3.backup()` → zip |
| Два процесса | `run_bot.py` + `app.py` | оба пишут в один файл (WAL + `busy_timeout=30000`) |
| Диагностика | [`services/admin_diagnostics.py`](../services/admin_diagnostics.py) | размер `bot.db`, без проверки PG |

Зависимостей PostgreSQL в репозитории **нет** (`asyncpg` / SQLAlchemy не подключены).

---

## Проблема `asyncio.Lock` в `get_db()` — можно ли исправить?

**Да.** Lock сейчас сериализует **все** корутины внутри процесса на одном соединении — это часто сильнее ограничивает throughput, чем сам SQLite.

### Почему lock появился

[`db/connection.py`](../db/connection.py) держит **одно** долгоживущее соединение. У `aiosqlite` **небезопасно** параллельно вызывать `execute()` из разных задач на одном connection — lock это страхует.

### Варианты исправления (от простого к сложному)

| Вариант | Суть | Плюсы | Минусы |
|---------|------|-------|--------|
| **A. Connection per request** | каждый `async with get_db()` открывает/закрывает соединение | убирает lock; WAL даёт параллельные читатели | overhead на connect; всё ещё SQLite writer |
| **B. Пул 2–5 соединений** | checkout connection из пула | баланс скорости и параллелизма | нужен аккуратный pool + лимит writer |
| **C. Read/write lock** | N читателей или 1 писатель | читатели не блокируют друг друга | нужно различать read/write в API |
| **D. PostgreSQL pool** | `asyncpg` / SQLAlchemy pool | нормальный конкурентный OLTP | часть Phase 1+ этого плана |

**Рекомендация:** вынести в **Phase 0** (можно сделать **до** PostgreSQL): вариант **A** или **B** только для SQLite — уменьшит блокировки без смены СУБД. Для PostgreSQL в Phase 1 сразу закладывать **пул** (вариант D).

### Черновик Phase 0 (SQLite concurrency)

1. Заменить singleton `_conn` на фабрику/пул в [`db/connection.py`](../db/connection.py).
2. Убрать глобальный `_lock` при переходе на connection-per-request или pool.
3. Сохранить `PRAGMA journal_mode=WAL`, `busy_timeout`, `foreign_keys`.
4. Прогнать: webhook burst, `scripts/dev/test_pending_flow.py`, admin-операции.
5. Мониторить логи на `database is locked` 24–48 ч на стейдже.

Ожидаемый эффект: лучше параллелизм **внутри** `run_bot.py` и `app.py`; между двумя процессами SQLite по-прежнему один writer — PG решает это полноценнее.

---

## Сводка фаз (бот)

| Фаза | Приоритет | Описание | Зависимости |
|------|-----------|----------|-------------|
| **0** | Средний | Убрать узкое место `asyncio.Lock` (SQLite pool / connection-per-request) | нет |
| **1** | Высокий | Абстракция `get_db()` + `DATABASE_URL` / `DB_BACKEND` | 0 желательно |
| **2** | Высокий | Единая схема + Alembic (sqlite + postgres dialect) | 1 |
| **3** | Высокий | Порт модулей `db/*.py` на абстракцию | 2 |
| **4** | Средний | Бэкап, deploy, диагностика для PG | 3 |
| **5** | Высокий | Скрипт миграции данных SQLite → PG + cutover | 3–4 |
| **6** | Низкий | CI: матрица тестов sqlite + postgres | 3 |

```mermaid
flowchart LR
    P0[Phase 0 SQLite pool] --> P1[Phase 1 abstraction]
    P1 --> P2[Phase 2 Alembic]
    P2 --> P3[Phase 3 port db modules]
    P3 --> P4[Phase 4 deploy backup]
    P3 --> P5[Phase 5 data migration]
    P3 --> P6[Phase 6 CI matrix]
```

**Принципы:**

1. `DATABASE_URL` пуст / не задан → SQLite (поведение как сейчас).
2. `DATABASE_URL=postgresql://...` → PostgreSQL, fail-fast ping при старте.
3. Один PR = одна фаза + чеклист регрессии.
4. Не держать две активные БД в runtime — только **один** source of truth на деплой.

---

## Phase 1 — Абстракция подключения

### Новые переменные `.env`

```env
# Пусто — SQLite (по умолчанию, как сейчас)
# DB_PATH=data/bot.db

# PostgreSQL (когда включён — DB_PATH игнорируется для OLTP)
# DATABASE_URL=postgresql://vpnbot:secret@127.0.0.1:5432/vpnbot
```

Опционально явный переключатель:

```env
DB_BACKEND=sqlite   # sqlite | postgres
```

### Файлы

| Файл | Изменение |
|------|-----------|
| [`config/settings.py`](../config/settings.py) | `DATABASE_URL`, `DB_BACKEND` |
| [`db/connection.py`](../db/connection.py) | фабрика: `aiosqlite` или `asyncpg` pool |
| [`db/database.py`](../db/database.py) | `init_connection()` / `close_connection()` для обоих backend |
| `db/types.py` (новый) | протокол/типы строк результата вместо жёсткого `aiosqlite.Row` |

### Рекомендуемый стек

**SQLAlchemy 2.0 async + Alembic** — один набор миграций, два dialect (`sqlite`, `postgresql`). Альтернатива «тонкая обёртка asyncpg + дублирующие SQL» — дешевле на старте, дороже в поддержке.

### Плейсхолдеры

Ввести helper `sql()` / `execute()` с нормализацией `?` → `$1` для PG или использовать только SQLAlchemy Core text() с bindparam.

---

## Phase 2 — Схема и миграции

### Отличия SQLite → PostgreSQL

| SQLite | PostgreSQL |
|--------|------------|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL` / `GENERATED BY DEFAULT AS IDENTITY` |
| `INTEGER` для bool (`0`/`1`) | `BOOLEAN` (или оставить int для совместимости на переходном этапе) |
| `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | `TIMESTAMPTZ DEFAULT now()` |
| `PRAGMA table_info` | `information_schema.columns` |
| `sqlite_master` | `pg_catalog` / Alembic revision |
| `INSERT OR REPLACE` | `INSERT ... ON CONFLICT DO UPDATE` |

### Миграции

1. Зафиксировать текущую схему SQLite как **Alembic revision baseline** (autogenerate с оговорками).
2. Перенести логику из `_init_db_impl()` ([`db/database.py`](../db/database.py)) в ревизии Alembic.
3. Удалить поштучные `PRAGMA table_info` миграции по мере переноса в Alembic.
4. [`db/init_lock.py`](../db/init_lock.py): для PG — advisory lock или таблица `schema_migrations` + транзакционный lock.

### Индексы

Сохранить существующие индексы из `_create_indexes()`; для PG проверить планы на `orders(status, created_at)`, `subscriptions(tg_id, is_active)`.

---

## Phase 3 — Порт модулей `db/`

Порядок (от критичных к вспомогательным):

1. [`db/webhook_dedup.py`](../db/webhook_dedup.py) — идемпотентность оплат (критично для webhook).
2. [`db/database.py`](../db/database.py) — users, orders, subscriptions.
3. [`db/xui_nodes.py`](../db/xui_nodes.py) — ноды.
4. [`db/tickets.py`](../db/tickets.py) — тикеты (есть `sqlite_master`).
5. [`db/bot_settings.py`](../db/bot_settings.py), [`db/payment_methods.py`](../db/payment_methods.py).
6. [`db/promo_codes.py`](../db/promo_codes.py), [`db/promo_pending.py`](../db/promo_pending.py), [`db/referrals.py`](../db/referrals.py).
7. [`db/trial_grants.py`](../db/trial_grants.py), [`db/faq.py`](../db/faq.py), [`db/plan_prices.py`](../db/plan_prices.py).

На каждый модуль:

- [ ] убрать прямой импорт `aiosqlite`
- [ ] заменить `IntegrityError` на общий wrapper
- [ ] `lastrowid` → `RETURNING id` на PG (или unified helper)
- [ ] тест на sqlite **и** postgres (Phase 6)

---

## Phase 4 — Бэкап, деплой, диагностика

### Бэкап ([`services/backup.py`](../services/backup.py))

| Backend | Метод |
|---------|--------|
| SQLite | как сейчас: `sqlite3.backup` → zip |
| PostgreSQL | `pg_dump -Fc` или SQL dump → zip + `manifest.json` |

Восстановление: документировать `pg_restore` / `psql` отдельно от SQLite `bot.db`.

### Deploy ([`deploy/vpn-bot-ctl.sh`](../deploy/vpn-bot-ctl.sh))

По аналогии с [`deploy/lib/redis.sh`](../deploy/lib/redis.sh):

- `deploy/lib/postgres.sh` — опциональная установка `postgresql`, создание user/DB
- пункт меню или флаг в reconcile: «поднять PostgreSQL для бота»
- `After=postgresql.service` в unit-файлах при `DATABASE_URL`

### Диагностика ([`services/admin_diagnostics.py`](../services/admin_diagnostics.py))

В раздел «Хранилище»:

- backend: `sqlite` / `postgres`
- для PG: ping, latency, размер БД (`pg_database_size`), active connections

---

## Phase 5 — Миграция данных (cutover)

### Подготовка

1. Стейдж с копией прод `bot.db`.
2. Поднять пустой PostgreSQL, прогнать Alembic `upgrade head`.
3. Скрипт `scripts/migrate_sqlite_to_postgres.py` (написать при Phase 5):
   - построчный/export-import по таблицам в порядке FK;
   - сверка `COUNT(*)` по каждой таблице;
   - сверка контрольных сумм (например `SUM(amount)` по paid orders).

### Cutover (минимальный downtime)

1. `systemctl stop vpn-bot-web vpn-bot-telegram`
2. Финальный `sqlite3.backup` / копия `bot.db`
3. Прогон мигратора на свежем файле
4. Выставить `DATABASE_URL` в `.env`, убрать/закомментировать зависимость от `DB_PATH`
5. `alembic upgrade head` (если нужно)
6. `systemctl start vpn-bot-telegram vpn-bot-web`
7. Smoke: `/health`, тестовая оплата TEST_MODE, `/admin` → диагностика

### Откат

1. Stop services
2. Убрать `DATABASE_URL`, вернуть `DB_PATH`
3. Восстановить `bot.db` из бэкапа шага 2
4. Start services

Держать SQLite-бэкап **не менее 7 дней** после cutover.

---

## Phase 6 — Тестирование

| Уровень | Что |
|---------|-----|
| Unit | helpers SQL, `build_recommendations`-стиль для db utils |
| Integration | `docker compose` с `postgres:16` + sqlite file |
| Dev scripts | `test_pending_flow.py`, `test_admin_diagnostics.py` на обоих backend |
| Manual | оплата, продление, тикет, промо, full sync нод, бэкап |

CI (опционально): matrix job `DB_BACKEND=sqlite|postgres`.

---

## Связь с 3x-ui и PostgreSQL

| Вопрос | Ответ |
|--------|-------|
| Нужно ли боту PG, если панель уже на PG? | **Не обязательно.** Это разные БД и разные процессы. |
| Нужно ли панели PG, если бот на SQLite? | **Да, может.** Панель может упираться в тысячи клиентов раньше бота. |
| Делать оба перехода одновременно? | Удобно для ops, но **увеличивает риск** — лучше раздельные окна обслуживания и откат. |
| Что проверять на панели | Документация 3x-ui: настройка `database` в конфиге панели, бэкап PG панели отдельно от `bot.db`. |

---

## Оценка трудозатрат (грубо)

| Фаза | Оценка |
|------|--------|
| 0 — SQLite pool | 1–2 дня |
| 1 — абстракция | 2–4 дня |
| 2 — Alembic + схема | 3–5 дней |
| 3 — порт 14 модулей | 1–2 недели |
| 4 — backup/deploy/diagnostics | 2–3 дня |
| 5 — migrator + cutover runbook | 3–5 дней |
| 6 — CI matrix | 2–3 дня |

**Итого:** порядка **3–4 недель** календарно при последовательных PR.

---

## Чеклист «пора начинать Phase 1»

- [ ] Зафиксированы метрики: размер `bot.db`, частота lock-ошибок, RPS webhook
- [ ] Решён вопрос multi-instance webhook (да/нет)
- [ ] Phase 0 (pool) протестирован или сознательно отложен
- [ ] Выбран стек: SQLAlchemy + Alembic vs asyncpg raw
- [ ] Есть стейдж с копией прод-данных
- [ ] Согласовано окно cutover и откат

---

## Ссылки в репозитории

| Документ | Тема |
|----------|------|
| [architecture.md](architecture.md) | два процесса, SQLite сегодня |
| [requirements.md](requirements.md) | VPS по числу подписок |
| [redis-migration-plan.md](redis-migration-plan.md) | FSM и multi-instance lock |
| [configuration.md](configuration.md) | переменные `.env` (дополнить при реализации) |

---

*Документ создан для отложенной реализации. При старте работ обновить статус фаз и ссылку в [README.md](README.md).*