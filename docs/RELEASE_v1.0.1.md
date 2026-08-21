# VPN Shop Bot v1.0.1

Небольшой UX-релиз вокруг **deploy CLI** — приятнее управлять ботом на VPS, без git и лишних шагов.

**Стек без изменений:** Platega + 3x-ui · Python 3.11–3.14 · aiogram 3 · FastAPI · SQLite · Redis FSM

---

## Что нового

### Charm / gum стиль меню
Интерактивный `vpn-bot-ctl.sh` перерисован в духе современных CLI (Charm/gum):

- мягкая «карточка» шапки с каталогом и версией;
- пункты с `›`, подсказки справа;
- секции: установка · обновление · службы · опасная зона;
- цвета ANSI; `NO_COLOR=1` отключает;
- на locale без UTF-8 — **ASCII-рамки** (без кракозябр).

### Обновление в два канала
| Меню | CLI | Что ставится |
|------|-----|----------------|
| **2** Stable ★ | `update` | последний **GitHub Release** |
| **3** Edge | `update --edge` | последний коммит `main` |

Локальный `.git` **не нужен**. Сохраняются `.env`, `data/`, `.venv/`.

### Live-логи с выходом по `q`
Пункт **6** · Логи:

- последние 50 строк + follow;
- подсветка ERROR / WARNING / SUCCESS / DEBUG;
- **`q`** — назад в меню (также Ctrl+C);
- корректное восстановление TTY.

### Bootstrap одной командой
Если ctl ещё старый или каталога нет:

```bash
curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/bootstrap.sh \
  | sudo bash -s -- /opt/vpn-bot
```

---

## Быстрый старт

```bash
# код
curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/bootstrap.sh \
  | sudo bash -s -- /opt/vpn-bot

# .env при первом запуске
sudo nano /opt/vpn-bot/.env

# меню
sudo bash /opt/vpn-bot/deploy/vpn-bot-ctl.sh
# 1 — окружение (+ Redis)
# 2 — обновиться до этого релиза (stable)
```

Уже на v1.0.0:

```bash
cd /opt/vpn-bot
sudo bash deploy/vpn-bot-ctl.sh update          # → v1.0.1
# или меню → пункт 2
```

---

## Меню ctl (кратко)

```
1  Установить / починить
2  Релиз (stable)     ← рекомендуется для прода
3  Коммит (edge)
4  Перезапустить
5  Статус
6  Логи               ← q назад
7  Остановить
8  Удалить службы
0  Выход
```

---

## Полный продукт (напоминание)

Магазин VPN «под ключ»: тарифы, Platega, промокоды, trial, рефералы, FAQ, тикеты, Happ-ссылки, multi-node 3x-ui, hub-админка, диагностика, lockdown, автобэкап.

Подробности продукта: [RELEASE_v1.0.0.md](RELEASE_v1.0.0.md) · документация: [README.md](README.md)

---

## Безопасность

Не коммитьте `.env`. См. [SECURITY.md](../SECURITY.md).
