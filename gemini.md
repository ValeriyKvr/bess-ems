# BESS ↔ EMS Simulator

## Що це
Симулятор взаємодії батареї (BESS) та системи керування енергією (EMS) на ринку
електроенергії України. Повне ТЗ — у `SPEC.md`. ЗАВЖДИ читай відповідний розділ
SPEC.md перед реалізацією; SPEC.md — джерело істини для формул, схем даних, API.

## Ключові принципи (не порушувати)
- BESS і EMS — окремі процеси, спілкуються ТІЛЬКИ через MQTT (SPEC §4.2–4.3).
- Єдиний симуляційний час (`SimulationClock`) належить EMS. Ніде не використовуй
  `datetime.now()` для бізнес-логіки — тільки `clock.now()`.
- Конвенція знака: power_kw < 0 — розряд, > 0 — заряд (SPEC §4.3).
- Жодних магічних чисел: усі параметри — через settings/БД/.env.
- Детермінованість: seed → однаковий результат.

## Стек
- Python 3.12, uv, FastAPI, SQLAlchemy 2 async, asyncpg, paho-mqtt, pandas,
  lightgbm, torch (CPU), pulp, apscheduler, pydantic v2
- Web: React 18 + TypeScript + Vite + Tailwind + Zustand + ECharts + Framer Motion, pnpm
- Infra: docker compose (postgres+timescaledb, mosquitto, ems, bess-sim, web)

## Структура
Див. SPEC §12. Не створюй файли поза цією структурою без причини.

## Команди
- `docker compose up --build` — вся система
- `cd ems && uv run pytest` / `cd bess-sim && uv run pytest`
- `cd web && pnpm dev` / `pnpm test` / `pnpm lint`
- `uv run ruff check . && uv run ruff format .`

## Стиль
- Код і коментарі — англійською. UI-тексти — українською (через i18n JSON).
- Docstrings для публічних функцій. Типізація обов'язкова (mypy нестрого).
- Тести для: фізики батареї, MILP, market simulator, features для ML.
- Не додавай залежності, яких немає в SPEC §12, без пояснення чому.

## Перед завершенням будь-якого завдання
1. Запусти лінтер і тести.
2. Перевір, що `docker compose up` не зламався (якщо чіпав інфраструктуру).
3. Онови `docs/` якщо змінив API, схему БД або протокол MQTT.
4. Стисло напиши, що зроблено і що НЕ зроблено з критеріїв етапу.