# Госзакупки РК: OWS v3 GraphQL ETL

Production-ready заготовка ETL и аналитического интерфейса для данных Государственных закупок РК. Система получает данные через OWS v3 GraphQL/REST, очищает и обогащает их справочниками, сохраняет в PostgreSQL через инкрементальный UPSERT и показывает аналитику в Streamlit.

## Что можно делать

- выгружать организации, планы, лоты, договоры и объявления за 2024–2026 годы;
- фильтровать данные по БИН организации, году, КАТО и наименованию территории;
- искать ценовые аномалии с отклонением от средней цены более 30%;
- сравнивать объемы закупок и суммы по годам;
- анализировать договоры, поставщиков, демпинг и самые дорогие лоты;
- выгружать результаты в CSV и Excel;
- задавать текстовые вопросы по закупкам, лотам, договорам, поставщикам и КАТО;
- использовать единый внутренний аккаунт с логином и паролем.

## Структура проекта

- `exporter.py` — GraphQL-пагинация и первичная выгрузка OWS;
- `enrich.py` — объявления, связанные планы и справочники;
- `analytics_builder.py` — очистка и аналитические JSONL/CSV-витрины;
- `database.py` — модели PostgreSQL и UPSERT;
- `etl.py` — загрузка выгрузок в PostgreSQL;
- `app.py` — Streamlit UI, KPI, вкладки, чат и экспорт;
- `auth.py` — авторизация одного пользователя;
- `docker-compose.yml` — PostgreSQL, ETL и Streamlit.

## Локальный запуск без Docker

1. Скопируйте `.env.example` в `.env` и заполните `OWS_API_TOKEN` (или оставьте совместимый ключ `Token`) и `DATABASE_URL`.
2. Установите зависимости: `.venv/bin/pip install -r requirements.txt`.
3. Получите выгрузку OWS v3 в JSONL/CSV:

   `.venv/bin/python exporter.py --output-dir data/export`

4. Добавьте объявления, связанные планы и справочники:

   `.venv/bin/python enrich.py --skip-announcements`

5. Постройте аналитические файлы:

   `.venv/bin/python analytics_builder.py`

6. Создайте таблицы и выполните инкрементальный UPSERT в PostgreSQL:

   `.venv/bin/python etl.py --source-dir data/export`

7. Запустите интерфейс:

   `.venv/bin/streamlit run app.py`

Повторный запуск безопасен: ключи API используются как первичные ключи, загрузка выполняется через PostgreSQL `ON CONFLICT DO UPDATE`.

## Запуск Docker Compose

Docker Compose сам установит Python-зависимости внутри образа; локальные Python-пакеты не нужны.

Для быстрой проверки без API можно использовать небольшой набор `data/sample/export/` — инструкция находится в `data/sample/README.md`.

1. В `.env` задайте `OWS_API_TOKEN` (или совместимый `Token`) и при необходимости измените `POSTGRES_PASSWORD`.
2. Убедитесь, что подготовленные файлы находятся в `data/export`.
3. Запустите:

   `docker compose up --build`

Интерфейс будет доступен на [http://localhost:18501](http://localhost:18501), PostgreSQL — на `localhost:55432`.
Сервис `etl` один раз создаст таблицы и выполнит UPSERT, после чего стартует Streamlit. Для повторной загрузки достаточно выполнить `docker compose run --rm etl`.

### Авторизация

Создайте PBKDF2-хеш пароля:

`python scripts/make_password_hash.py`

Запишите результат в `.env`:

`APP_USERNAME=admin`

`APP_PASSWORD_HASH=pbkdf2_sha256$...`

После этого перезапустите Streamlit: `docker compose up -d --build streamlit`.

## Результаты

- `data/export/` — исходные subjects/plans/lots/contracts;
- `data/enriched/` — объявления и справочники OWS;
- `data/analytics/` — JSONL/CSV-витрины для анализа;
- `database.py` — модели `dim_subjects`, `fact_plans`, `fact_lots`, `fact_contracts`;
- `analytics_sql.py` и `app.py` — быстрые аналитические запросы и Streamlit UI.
