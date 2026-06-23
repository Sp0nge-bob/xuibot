# Безопасность

## Секреты

Никогда не коммитьте в репозиторий:

- `.env` — токены Telegram, Platega, 3x-ui
- `data/` — SQLite-база с пользователями и заказами
- логи с телами webhook и персональными данными
- `terminals/` — локальные дампы терминала IDE (могут содержать URL панели и ID)
- `report/`, `CHAT_CONTEXT.md` — отчёты и контекст сессий с реальными URL и токенами

В git допустим только [`.env.example`](.env.example) с плейсхолдерами. В коде — только примерные ID (`123456789`), не реальные Telegram ID админов.

## Очистка истории git

Если секреты уже попали в удалённый репозиторий, одного `git rm` недостаточно — данные остаются в старых коммитах.

### Быстрая очистка (только `.env` / `data/bot.db`)

```bash
pip install git-filter-repo
git filter-repo --path .env --invert-paths --force
git filter-repo --path data/bot.db --invert-paths --force
git remote add origin https://github.com/OWNER/REPO.git
git push origin main --force
```

### Полная очистка (рекомендуется при утечке)

1. Удалить из всей истории чувствительные пути:
   - `report/`, `CHAT_CONTEXT.md`, `docs/sync-service-context.md`, `test_bot.py`
   - `vpn_platega_bot.egg-info/`, `__pycache__/`, `*.pyc`
2. Заменить в оставшихся коммитах реальные значения на плейсхолдеры (`git filter-repo --replace-text`).
3. Анонимизировать email авторов коммитов (`--email-callback`), если в истории есть личные адреса.
4. Проверить, что по всей истории нет известных утечек (реальные Telegram ID, токены бота, секретные пути панели, домены проекта, личные email). Используйте `git grep` по своему списку скомпрометированных значений — вывод должен быть пустым.

5. `git push origin main --force`
6. На VPS: `git fetch origin && git reset --hard origin/main`

После force push — **обязательно** ротируйте все ключи, даже если история очищена.

## Если секрет попал в git

1. Немедленно **ротируйте** скомпрометированные ключи:
   - `BOT_TOKEN` — @BotFather → Revoke / новый токен
   - `PLATEGA_SECRET` — личный кабинет Platega
   - `XUI_TOKEN` / пароль панели — 3x-ui
2. Убедитесь, что `.env` не отслеживается: `git rm --cached .env`
3. Если секрет уже был в удалённом репозитории — выполните полную очистку истории (см. выше) и снова ротируйте ключи

## Продакшен

- `TEST_MODE=false`
- `ALLOW_DEBUG_ADMIN=false`
- `PUBLIC_WEBHOOK_URL` — только HTTPS
- Раздел «Отладка» в `/admin` отключён

## Сообщить о проблеме

Создайте приватный issue в репозитории или свяжитесь с владельцем проекта напрямую. Не публикуйте токены и дампы `.env` в открытых issue.