# Goszakup GraphQL ETL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать Docker-проект на Python 3.10+ для GraphQL-загрузки данных OWS v3 в PostgreSQL и анализа в Streamlit.

**Architecture:** Один кодовый образ используется сервисами ETL и Streamlit; PostgreSQL хранит нормализованные измерения и факты. GraphQL-запросы отделены от курсорного клиента и mapper-функций, а аналитические SQL-запросы отделены от UI для модульного тестирования.

**Tech Stack:** Python 3.10+, SQLAlchemy 2, psycopg2-binary, requests, python-dotenv, Streamlit, pandas, pytest, PostgreSQL 16, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-13-goszakup-etl-design.md`

## Global Constraints

- Только GraphQL OWS v3; токен передаётся как `Authorization: Bearer <TOKEN>`.
- Целевой период: 2024–2026; целевые организации — ровно 27 БИН из пользовательского списка.
- API ID являются первичными ключами; повторная загрузка использует PostgreSQL UPSERT.
- Секреты читаются только из окружения/`.env`, а `.env` не попадает в Git или Docker image.
- Пользовательский ввод не конкатенируется в SQL; mock-агент не выполняет SQL.
- Краткие комментарии и эксплуатационная документация пишутся на русском языке.

## Review Focus

- GraphQL сообщает `hasNextPage=true`, но не меняет `lastId`: пагинатор обязан завершиться контролируемой ошибкой.
- API возвращает БИН как число или строку с потерянным ведущим нулём: не дополнять догадкой, считать невалидным и логировать.
- Даты приходят с `Z`, timezone offset или без timezone: нормализовать к timezone-aware UTC и корректно вычислять год.
- Денежные поля приходят строками с запятой или пробелами: безопасно преобразовать в `Decimal`, не использовать `float`.
- Средняя/медианная аналитика получает пустую выборку либо нулевые цены: вернуть пустой DataFrame без деления на ноль.

---

### Task 1: Конфигурация и доменные константы

**Files:**
- Create: `config.py`
- Create: `tests/test_config.py`
- Create: `requirements.txt`
- Create: `.env`
- Create: `.env.example`
- Create: `.gitignore`

**Interfaces:**
- Produces: `Settings.from_env() -> Settings`, `TARGET_BINS: tuple[str, ...]`, `ALLOWED_YEARS: frozenset[int]`.

- [ ] **Step 1: Write failing tests** for 27 exact BINs, missing token behavior outside config construction, URL/timeouts/batch defaults, and environment overrides.
- [ ] **Step 2: Run `pytest tests/test_config.py -v`** and confirm import/test failure.
- [ ] **Step 3: Implement immutable settings and environment loading** with `load_dotenv()`, without logging secrets.
- [ ] **Step 4: Run `pytest tests/test_config.py -v`** and confirm PASS.
- [ ] **Step 5: Commit** `test/config files` if the workspace is later initialized as Git.

### Task 2: PostgreSQL schema and UPSERT

**Files:**
- Create: `database.py`
- Create: `tests/test_database.py`
- Create: `tests/test_database_integration.py`
- Create: `pytest.ini`

**Interfaces:**
- Consumes: `Settings.database_url`.
- Produces: ORM classes `Subject`, `Plan`, `Lot`, `Contract`; `get_engine(url) -> Engine`; `init_db(engine) -> None`; `upsert_records(session, model, records, batch_size) -> int`.

- [ ] **Step 1: Write failing metadata tests** asserting table names, API primary keys, FK targets, numeric/date types, unique BIN and required indexes.
- [ ] **Step 2: Run `pytest tests/test_database.py -v`** and confirm failure.
- [ ] **Step 3: Implement SQLAlchemy 2 models and engine/session helpers.**
- [ ] **Step 4: Write failing PostgreSQL integration test**: insert row, update same API ID, assert one row and updated values.
- [ ] **Step 5: Implement batched `postgresql.insert(...).on_conflict_do_update()`**, excluding primary key and `created_at` from the update set.
- [ ] **Step 6: Run unit tests and optional integration test**; unit suite must PASS and integration test must PASS when `TEST_DATABASE_URL` exists, otherwise SKIP.

### Task 3: Data-quality normalization and mapping

**Files:**
- Create: `etl.py`
- Create: `tests/test_etl_quality.py`
- Create: `tests/test_etl_mapping.py`

**Interfaces:**
- Consumes: ORM payload shapes and target constants.
- Produces: `clean_text(value) -> str | None`, `normalize_unit(value) -> str | None`, `parse_decimal(value) -> Decimal | None`, `parse_datetime(value) -> datetime | None`, `map_subject/item`, `map_plan/item`, `map_lot/item`, `map_contract/item`.

- [ ] **Step 1: Write failing text/unit tests** for Unicode NFKC, whitespace, control characters, meaningful punctuation, garbage markers and case normalization.
- [ ] **Step 2: Run quality tests** and confirm expected failures.
- [ ] **Step 3: Implement the minimal normalization functions.**
- [ ] **Step 4: Write failing numeric/date tests** for decimal comma/spaces, invalid inputs, `Z`, offsets and naive datetimes normalized to UTC.
- [ ] **Step 5: Implement parsers and rerun quality tests** to PASS.
- [ ] **Step 6: Write failing mapper tests** for snake/camel aliases, exact BIN validation, target filters, years, and missing required values.
- [ ] **Step 7: Implement mapper functions returning `None` for rejected facts with a reason logged by the caller.**
- [ ] **Step 8: Run `pytest tests/test_etl_quality.py tests/test_etl_mapping.py -v`** and confirm PASS.

### Task 4: GraphQL client and cursor pagination

**Files:**
- Modify: `etl.py`
- Create: `queries/subjects.graphql`
- Create: `queries/plans.graphql`
- Create: `queries/lots.graphql`
- Create: `queries/contracts.graphql`
- Create: `tests/test_graphql_client.py`

**Interfaces:**
- Produces: `GraphQLClient.execute(query, variables) -> dict`; `GraphQLClient.paginate(query, root_field, variables=None) -> Iterator[list[dict]]`; `load_query(name) -> str`.

- [ ] **Step 1: Write failing client tests** for bearer header, timeout, GraphQL `errors`, 429/5xx retries and non-retryable 4xx.
- [ ] **Step 2: Run client tests** and confirm failure.
- [ ] **Step 3: Implement `requests.Session` client** using a retry-enabled HTTP adapter and token-safe exceptions.
- [ ] **Step 4: Write failing pagination tests** for one page, multiple pages, preserved filters, empty page and missing/repeated cursor protection.
- [ ] **Step 5: Implement cursor paginator** using `extensions.pageInfo`.
- [ ] **Step 6: Add provisional GraphQL documents** with comments documenting that field names require validation against the authenticated schema.
- [ ] **Step 7: Run `pytest tests/test_graphql_client.py -v`** and confirm PASS.

### Task 5: ETL orchestration

**Files:**
- Modify: `etl.py`
- Create: `tests/test_etl_pipeline.py`

**Interfaces:**
- Consumes: `GraphQLClient`, mappers, `upsert_records`, `TARGET_BINS`.
- Produces: `run_pipeline(settings: Settings) -> PipelineStats`; CLI `python etl.py`.

- [ ] **Step 1: Write failing pipeline tests** asserting subjects load before facts, rejected rows do not abort a page, UPSERT batches are called, stats are accurate, and missing token exits clearly.
- [ ] **Step 2: Run pipeline tests** and confirm failure.
- [ ] **Step 3: Implement per-entity extract-transform-load functions and aggregate statistics.**
- [ ] **Step 4: Implement CLI logging and nonzero exit on fatal failure**, never printing the token.
- [ ] **Step 5: Run `pytest tests/test_etl_pipeline.py -v` and full `pytest -v`**; confirm PASS/SKIP only.

### Task 6: Analytics queries and mock agent

**Files:**
- Create: `analytics.py`
- Create: `tests/test_analytics.py`

**Interfaces:**
- Produces: `find_price_anomalies(engine, selected_bin, year, enstru_code=None) -> DataFrame`; `assess_price_fairness(engine, selected_bin, year, kato_code) -> DataFrame`; `analyze_volume_changes(engine, selected_bin) -> DataFrame`; `run_ai_agent(user_query, selected_bin) -> AgentResponse`.

- [ ] **Step 1: Write failing tests** that inspect compiled bound parameters and exercise empty/zero datasets with a lightweight fake result boundary.
- [ ] **Step 2: Run analytics tests** and confirm failure.
- [ ] **Step 3: Implement parameterized SQL** for >30% deviation, peer average/median by KATO+ЕНСТРУ, and 2024–2026 quantity pivots with >=50% jumps.
- [ ] **Step 4: Implement deterministic mock-agent response** returning SQL text, params and non-execution warning.
- [ ] **Step 5: Run `pytest tests/test_analytics.py -v`** and confirm PASS.

### Task 7: Streamlit interface

**Files:**
- Create: `app.py`
- Create: `tests/test_app_helpers.py`

**Interfaces:**
- Consumes: settings, analytics functions, target BINs.
- Produces: Streamlit page with sidebar filters, quick-analysis controls, tables and stateful chat.

- [ ] **Step 1: Write failing pure-helper tests** for chat history initialization and safe result formatting.
- [ ] **Step 2: Run helper tests** and confirm failure.
- [ ] **Step 3: Implement page configuration, cached engine, sidebar, three analysis sections and user-facing empty/error states.**
- [ ] **Step 4: Implement `st.chat_input`/`st.chat_message` history and mock-agent output.**
- [ ] **Step 5: Run helper tests and `python -m py_compile app.py`**; confirm PASS.

### Task 8: Docker packaging and documentation

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`
- Create: `README.md`
- Create: `tests/test_project_files.py`

**Interfaces:**
- Produces: services `db`, `app`, profile/manual service `etl`; commands documented for first run and daily run.

- [ ] **Step 1: Write failing project-file tests** for non-root image user, Python 3.10+, health checks, persistent DB volume, no token literal, `.env` exclusions and expected service commands.
- [ ] **Step 2: Run project-file tests** and confirm failure.
- [ ] **Step 3: Implement Dockerfile and Compose**, using PostgreSQL 16 and dependency conditions.
- [ ] **Step 4: Write Russian README** with configuration, startup, ETL, tests, scheduling example and post-token GraphQL adaptation checklist.
- [ ] **Step 5: Run project-file tests and `docker compose config`**; confirm PASS.

### Task 9: Final verification

**Files:**
- Modify only files required by discovered verification failures.

**Interfaces:**
- Produces: verified release candidate.

- [ ] **Step 1: Run `pytest -v`** and record exact PASS/SKIP counts.
- [ ] **Step 2: Run `python -m compileall -q .`** and confirm zero exit.
- [ ] **Step 3: Run `docker compose config --quiet`** and confirm zero exit.
- [ ] **Step 4: Build images with `docker compose build`** if Docker daemon/network are available; otherwise report the environmental limitation explicitly.
- [ ] **Step 5: Inspect `.env`, logs and tracked project files for embedded credentials.**
- [ ] **Step 6: Review delivered behavior against every section of the approved specification and report any provisional GraphQL fields clearly.**
