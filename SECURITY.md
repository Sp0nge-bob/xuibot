# Безопасность

## Секреты

Никогда не коммитьте в репозиторий:

- `.env` — токены Telegram, Platega, 3x-ui
- `data/` — SQLite-база с пользователями и заказами
- логи с телами webhook и персональными данными
- `terminals/` — локальные дампы терминала IDE (могут содержать URL панели и ID)

В git допустим только [`.env.example`](.env.example) с плейсхолдерами. В коде — только примерные ID (`123456789`), не реальные Telegram ID админов.

## Очистка истории git

Если `.env` или `data/bot.db` уже попали в удалённый репозиторий:

```bash
pip install git-filter-repo
git filter-repo --path .env --invert-paths
git filter-repo --path data/bot.db --invert-paths
git push origin main --force
```

После force push — **обязательно** ротируйте все ключи, даже если история очищена.

## Если секрет попал в git

1. Немедленно **ротируйте** скомпрометированные ключи:
   - `BOT_TOKEN` — @BotFather → Revoke / новый токен
   - `PLATEGA_SECRET` — личный кабинет Platega
   - `XUI_TOKEN` / пароль панели — 3x-ui
2. Убедитесь, что `.env` не отслеживается: `git rm --cached .env`
3. Если секрет уже был в удалённом репозитории — очистите историю (`git filter-repo` или BFG) и снова ротируйте ключи

## Продакшен

- `TEST_MODE=false`
- `ALLOW_DEBUG_ADMIN=false`
- `PUBLIC_WEBHOOK_URL` — только HTTPS
- Раздел «Отладка» в `/admin` отключён

## Сообщить о проблеме

Создайте приватный issue в репозитории или свяжитесь с владельцем проекта напрямую. Не публикуйте токены и дампы `.env` в открытых issue.