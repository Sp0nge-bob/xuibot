"""FAQ-статьи для клиентов (заголовок, текст, фото)."""
from __future__ import annotations

from typing import Any, Optional


from db.connection import get_db

BUILTIN_ACTIVATION_KEY = "activation"
BUILTIN_ACTIVATION_TITLE = "Как активировать подписку"


async def _migrate_faq_schema(db) -> None:
    async with db.execute("PRAGMA table_info(faq_articles)") as cur:
        cols = {row[1] for row in await cur.fetchall()}
    if "builtin_key" not in cols:
        await db.execute("ALTER TABLE faq_articles ADD COLUMN builtin_key TEXT")
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_faq_articles_builtin_key "
        "ON faq_articles(builtin_key) WHERE builtin_key IS NOT NULL"
    )


async def ensure_builtin_faq_articles() -> None:
    """Встроенные статьи FAQ (создаются один раз при первом запуске)."""
    from services.fulfillment_text import activation_setup_body

    async with get_db() as db:
        async with db.execute(
            "SELECT id FROM faq_articles WHERE builtin_key = ?",
            (BUILTIN_ACTIVATION_KEY,),
        ) as cur:
            if await cur.fetchone():
                return

        async with db.execute("SELECT COALESCE(MIN(sort_order), 0) FROM faq_articles") as cur:
            min_sort = int((await cur.fetchone())[0] or 0)

        await db.execute(
            """INSERT INTO faq_articles
               (title, body, sort_order, is_published, builtin_key, updated_at)
               VALUES (?, ?, ?, 1, ?, CURRENT_TIMESTAMP)""",
            (
                BUILTIN_ACTIVATION_TITLE,
                activation_setup_body(),
                min_sort - 1,
                BUILTIN_ACTIVATION_KEY,
            ),
        )
        await db.commit()


def is_activation_faq_article(article: dict[str, Any] | None) -> bool:
    return bool(article) and article.get("builtin_key") == BUILTIN_ACTIVATION_KEY


async def init_faq_tables() -> None:
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS faq_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_published INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS faq_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(article_id) REFERENCES faq_articles(id) ON DELETE CASCADE
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_faq_photos_article "
            "ON faq_photos(article_id, sort_order)"
        )
        await _migrate_faq_schema(db)
        await db.commit()
    await ensure_builtin_faq_articles()


async def _next_sort_order() -> int:
    async with get_db() as db:
        async with db.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM faq_articles") as cur:
            row = await cur.fetchone()
            return int(row[0] if row else 0)


async def list_articles(*, published_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM faq_articles"
    if published_only:
        sql += " WHERE is_published = 1"
    sql += " ORDER BY sort_order ASC, id ASC"
    async with get_db() as db:
        async with db.execute(sql) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_article(article_id: int) -> Optional[dict[str, Any]]:
    async with get_db() as db:
        async with db.execute("SELECT * FROM faq_articles WHERE id = ?", (article_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def create_article(*, title: str, body: str, is_published: bool = True) -> int:
    sort_order = await _next_sort_order()
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO faq_articles (title, body, sort_order, is_published, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (title.strip(), body, sort_order, int(is_published)),
        )
        await db.commit()
        return cursor.lastrowid


async def update_article(article_id: int, **fields: Any) -> bool:
    allowed = {"title", "body", "sort_order", "is_published"}
    parts: list[str] = []
    values: list[Any] = []
    for key, val in fields.items():
        if key not in allowed:
            continue
        if key == "is_published":
            val = int(bool(val))
        parts.append(f"{key} = ?")
        values.append(val)
    if not parts:
        return False
    parts.append("updated_at = CURRENT_TIMESTAMP")
    values.append(article_id)
    async with get_db() as db:
        cursor = await db.execute(
            f"UPDATE faq_articles SET {', '.join(parts)} WHERE id = ?",
            values,
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_article(article_id: int) -> bool:
    async with get_db() as db:
        await db.execute("DELETE FROM faq_photos WHERE article_id = ?", (article_id,))
        cursor = await db.execute("DELETE FROM faq_articles WHERE id = ?", (article_id,))
        await db.commit()
        return cursor.rowcount > 0


async def list_photos(article_id: int) -> list[dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM faq_photos WHERE article_id = ? ORDER BY sort_order ASC, id ASC",
            (article_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def add_photo(article_id: int, file_id: str) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM faq_photos WHERE article_id = ?",
            (article_id,),
        ) as cur:
            sort_order = int((await cur.fetchone())[0])
        cursor = await db.execute(
            """INSERT INTO faq_photos (article_id, file_id, sort_order)
               VALUES (?, ?, ?)""",
            (article_id, file_id, sort_order),
        )
        await db.commit()
        return cursor.lastrowid


async def delete_photo(photo_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute("DELETE FROM faq_photos WHERE id = ?", (photo_id,))
        await db.commit()
        return cursor.rowcount > 0


async def count_published() -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM faq_articles WHERE is_published = 1"
        ) as cur:
            return int((await cur.fetchone())[0])