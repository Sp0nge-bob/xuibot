# Подготовка обновления — выполнение запрещено до допуска

**Статус: HOLD. Ветка подготовлена для push/review; production release не одобрен.**
Патчноут: [SECURITY_2026-11-01.md](SECURITY_2026-11-01.md).

## 1. Ревью и будущий push

Ветка: security-fixes/2026-11-01. В ней только проверенный локальный код, тесты,
шаблоны настроек и документация. Локальные audit/evidence/БД/.env не публикуются.
Команда ниже приведена для оператора; агент её не выполнял:

```bash
git status --short
git log --oneline main..security-fixes/2026-11-01
git diff --check main..security-fixes/2026-11-01
git push --set-upstream origin security-fixes/2026-11-01
```

Публиковать ветку для review; не сливать main, не создавать production tag и не
запускать обновлятор по умолчанию main/latest до закрытия блокеров. Перед push
проверить актуальное отношение к remote: в этой подготовке fetch не выполнялся.
Если remote изменился, согласовать совместимость и повторить тесты; force push не нужен.

## 2. Обязательные условия production

1. Закрыть указанные в патчноуте кодовые блокеры и полный mocked financial
   matrix: duplicate/out-of-order/wrong amount/currency/order, crash/restart,
   ошибка панели до/после эффекта, возврат, retry и два продления без потери дней.
2. Проверить общий SQLite контракт в обоих порядках запуска, account linking,
   expiry/ban/refund precedence, старые аккаунты и старые/новые версии writers.
3. Выполнить свежие dependency/static scans и воспроизводимую сборку на
   поддерживаемой Linux/Python платформе. Сейчас lock/advisory gate не закрыт.
4. Подтвердить Happ/iOS/Xray/DNS TCP+UDP/A→Б и браузерные сценарии на изолированных
   узлах и фиктивных данных. Пропущенные проверки не считать успешными.
5. Получить отдельное разрешение пользователя на production и фактический
   согласованный набор commit SHA всех трёх сервисов. Не выбирать latest вслепую.

## 3. Конфигурация, резервирование и порядок

- Не менять UUID, sub_id, существующие ссылки, даты подписок, настройки реальных
  нод, Nginx/DNS/firewall или секреты автоматически. Сначала inventory с отдельным
  разрешением; реальные .env и unit names в этом репозитории не фиксируются.
- До запуска нового бота/сайта проверить совпадение Fernet-настроек и чтение
  каждого ciphertext на согласованной защищённой копии. При derivation от
  SECRET_KEY значения должны совпадать; при отдельном ENCRYPTION_KEY согласуется
  этот ключ. OLD_SECRET_KEY — только явно запланированный переход. Публичные
  ciphertext требуют отдельной offline-ротации, а не вечного fallback.
- Создать разрешённый согласованный SQLite backup через online backup API либо
  проверенную остановку writers; не копировать один активный .db при WAL.
  Отдельно сохранить защищённые конфигурации и артефакты. Проверить восстановление,
  integrity_check, foreign_key_check, идентификаторы, даты, историю платежей.
- Предлагаемый порядок после всех допусков: middleware и format/client smoke;
  сайт и auth/payment mock smoke; бот и Telegram/queue/link smoke. Сначала
  подтвердить криптографическую совместимость пары. Будущий ledger потребует
  согласованного обновления всех writers, а не смешивания несовместимых версий.
- Существующие auto-update меню могут выполнять pip/migrations/restart. Их нельзя
  использовать как замену этому допуску. Не обновлять все зависимости попутно.
- В текущей порции только бот может создать недостающую email_blacklist через
  IF NOT EXISTS. Данные и ограничения не пересоздаются. Сайт при старте выполняет
  существующие миграции, поэтому backup/restore drill нужен даже без новой схемы.

## 4. Проверки после разрешённого обновления

Health/startup; login/logout/session expiry/OTP/mobile admin; Telegram commands,
FSM/linking; mock/provider-approved sandbox payment без live charge; выдача и
продление тестовой подписки; JSON/base64 GET/HEAD и subscription/HWID headers;
Happ/iOS/Xray DNS/failover; целостность БД и отсутствие новых потерянных/двойных
начислений; защищённые логи без bearer/credentials; timeouts/CPU/memory/locks в staging.

Фактический unit и user/system scope systemd оператор сначала сверяет с текущей
установкой. Команды restart не выполнялись и конкретные production units не угаданы.

## 5. Откат

На auth/format regression, неоплаченный доступ, потерю оплаченной услуги,
расхождение panel/DB, повторное начисление или деградацию остановить rollout.
Сохранить evidence, с разрешением остановить затронутые writers и восстановить
предыдущий проверенный artifact SHA с безопасной конфигурацией. Не откатывать
секреты к публичным значениям. Additive blacklist оставить вместе с ban records.
Не восстанавливать старую БД поверх новых платежей без отдельного разрешения и
сверки intervening events: это может потерять новые данные. Повторить integrity,
financial reconciliation, health и client smoke до возобновления writers.

Обновление, backup, миграции и restart в production этой подготовкой не выполнялись.
