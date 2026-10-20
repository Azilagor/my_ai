"""Streamlit-аналитика госзакупок."""
from __future__ import annotations
import os
import re
import json
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import pandas as pd
from analytics_sql import ANOMALIES_SQL, FAIR_PRICE_SQL, VOLUME_SQL
from auth import require_login

load_dotenv()
TARGET_BINS = ["000740001307", "020240002363", "020440003656", "030440003698", "050740004819", "051040005150", "100140011059", "120940001946", "140340016539", "150540000186", "171041003124", "210240019348", "210240033968", "210941010761", "230740013340", "231040023028", "780140000023", "900640000128", "940740000911", "940940000384", "960440000220", "970940001378", "971040001050", "980440001034", "981140001551", "990340005977", "990740002243"]

@st.cache_resource
def db_engine():
    url = os.getenv("DATABASE_URL")
    return create_engine(url, pool_pre_ping=True) if url else None

@st.cache_data(ttl=300)
def subject_options():
    rows = query("SELECT bin, COALESCE(name_ru, 'Без названия') AS name_ru FROM dim_subjects WHERE bin <> '' ORDER BY name_ru, bin", {})
    target = set(TARGET_BINS)
    rows = [row for row in (rows or []) if row["bin"] in target]
    return rows or [{"bin": value, "name_ru": value} for value in TARGET_BINS]

@st.cache_data(ttl=300)
def kato_options():
    path = Path("data/enriched/references/ref_kato.jsonl")
    if not path.exists():
        return [{"code": "710000000", "name": "Астана"}]
    result = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            code = str(item.get("code") or "")
            if code:
                result.append({"code": code, "name": item.get("full_name_ru") or item.get("name_ru") or code})
    unique = {item["code"]: item for item in result}
    return sorted(unique.values(), key=lambda item: item["name"])

def run_ai_agent(user_query: str, selected_bin: str) -> str:
    return f"-- mock SQL для БИН {selected_bin}\nSELECT * FROM fact_lots WHERE customer_bin = '{selected_bin}' -- вопрос: {user_query}"

def query(sql: str, params: dict):
    engine = db_engine()
    if not engine: return []
    with engine.connect() as conn:
        return conn.execute(text(sql), params).mappings().all()

def show_result(rows):
    if not rows:
        st.info("По выбранным параметрам данных не найдено.")
        return
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

def _excel_bytes(frame: pd.DataFrame) -> bytes:
    import io
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="data")
    return buffer.getvalue()

def chat_answer(user_query: str, selected_bin: str, year: int):
    lowered = user_query.casefold()
    year_match = re.search(r"20(?:24|25|26)", lowered)
    requested_year = int(year_match.group()) if year_match else year
    kato_match = re.search(r"\b\d{9}\b", lowered)
    requested_kato = kato_match.group() if kato_match else None

    if "кaто" in lowered or "като" in lowered:
        sql = """
            SELECT kato_code, COUNT(*) AS lots, SUM(amount) AS total_amount
            FROM fact_lots WHERE customer_bin = :bin AND export_year = :year
            GROUP BY kato_code ORDER BY lots DESC LIMIT 100
        """
        if requested_kato:
            sql = """
                SELECT id, lot_number, name_ru, amount, count, kato_code, export_year
                FROM fact_lots WHERE customer_bin = :bin AND kato_code = :kato AND export_year = :year
                ORDER BY amount DESC NULLS LAST LIMIT 100
            """
        return ("Анализ по КАТО", query(sql, {"bin": selected_bin, "kato": requested_kato, "year": requested_year}))

    if ("договор" in lowered or "контракт" in lowered):
        return ("Договоры", query("""
            SELECT id, contract_number, contract_sum_wnds, supplier_biin, sign_date
            FROM fact_contracts WHERE customer_bin = :bin AND fin_year = :year
            ORDER BY contract_sum_wnds DESC NULLS LAST LIMIT 100
        """, {"bin": selected_bin, "year": requested_year}))

    if "поставщик" in lowered or "поставщики" in lowered:
        return ("Частые поставщики", query("""
            SELECT supplier_biin, COUNT(*) AS contracts, SUM(contract_sum_wnds) AS total_amount
            FROM fact_contracts WHERE customer_bin = :bin AND fin_year = :year AND supplier_biin IS NOT NULL
            GROUP BY supplier_biin ORDER BY contracts DESC LIMIT 100
        """, {"bin": selected_bin, "year": requested_year}))

    if "демпинг" in lowered:
        return ("Лоты с максимальным демпингом", query("""
            SELECT id, lot_number, name_ru, dumping, amount, kato_code, export_year
            FROM fact_lots WHERE customer_bin = :bin AND export_year = :year AND dumping IS NOT NULL
            ORDER BY dumping DESC LIMIT 100
        """, {"bin": selected_bin, "year": requested_year}))

    if "аномал" in lowered or ("отклон" in lowered and "цен" in lowered):
        return ("Ценовые аномалии", query(ANOMALIES_SQL, {"bin": selected_bin, "year": requested_year}))

    if "объем" in lowered or "объём" in lowered or "вырос" in lowered or "скач" in lowered:
        return ("Объемы по годам", query(VOLUME_SQL, {"bin": selected_bin}))

    if "сам" in lowered and ("дорог" in lowered or "цен" in lowered):
        return ("Самые дорогие закупки", query("""
            SELECT id, lot_number, name_ru, amount, count, kato_code, export_year
            FROM fact_lots WHERE customer_bin = :bin AND export_year = :year
            ORDER BY amount DESC NULLS LAST LIMIT 100
        """, {"bin": selected_bin, "year": requested_year}))

    if any(word in lowered for word in ("закуп", "лот", "покуп")):
        return ("Закупки и лоты", query("""
            SELECT id, lot_number, name_ru, amount, count, kato_code, export_year
            FROM fact_lots WHERE customer_bin = :bin AND export_year = :year
            ORDER BY amount DESC NULLS LAST LIMIT 100
        """, {"bin": selected_bin, "year": requested_year}))
    return None

st.set_page_config(page_title="Госзакупки РК", layout="wide")
require_login()
st.title("Аналитика государственных закупок")
if st.sidebar.button("Выйти"):
    st.session_state.authenticated = False
    st.rerun()
subjects = subject_options()
search_bin = st.sidebar.text_input("Поиск по БИН", max_chars=12, placeholder="Например, 0204")
if search_bin:
    subjects = [item for item in subjects if search_bin in str(item["bin"])]
if not subjects:
    st.sidebar.warning("Организация с таким БИН не найдена")
    subjects = [{"bin": TARGET_BINS[0], "name_ru": "Не найдено"}]
selected_label = st.sidebar.selectbox(
    "Организация",
    subjects,
    format_func=lambda item: f"{item['name_ru']} ({item['bin']})",
)
selected_bin = selected_label["bin"]
selected_year = st.sidebar.selectbox("Год", [2024, 2025, 2026], index=1)
katos = kato_options()
kato_search = st.sidebar.text_input("Поиск по КАТО", placeholder="Код или название")
if kato_search:
    needle = kato_search.casefold()
    katos = [item for item in katos if needle in item["code"] or needle in item["name"].casefold()]
if not katos:
    st.sidebar.warning("КАТО не найден")
    katos = [{"code": "710000000", "name": "Астана"}]
selected_kato_item = st.sidebar.selectbox(
    "Территория КАТО",
    katos,
    format_func=lambda item: f"{item['name']} ({item['code']})",
)
selected_kato = selected_kato_item["code"]

kpi_rows = query("""
SELECT
 (SELECT COUNT(*) FROM fact_lots WHERE customer_bin = :bin AND export_year = :year) AS lots,
 (SELECT COALESCE(SUM(amount), 0) FROM fact_lots WHERE customer_bin = :bin AND export_year = :year) AS lot_amount,
 (SELECT COUNT(*) FROM fact_contracts WHERE customer_bin = :bin AND fin_year = :year) AS contracts,
 (SELECT COUNT(DISTINCT supplier_biin) FROM fact_contracts WHERE customer_bin = :bin AND fin_year = :year) AS suppliers
""", {"bin": selected_bin, "year": selected_year})
if kpi_rows:
    kpi = kpi_rows[0]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Лотов", f"{kpi['lots']:,}".replace(",", " "))
    k2.metric("Сумма лотов", f"{float(kpi['lot_amount'] or 0):,.0f} ₸".replace(",", " "))
    k3.metric("Договоров", f"{kpi['contracts']:,}".replace(",", " "))
    k4.metric("Поставщиков", f"{kpi['suppliers']:,}".replace(",", " "))

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Поиск аномалий"):
        show_result(query(ANOMALIES_SQL, {"bin": selected_bin, "year": selected_year}))
with col2:
    if st.button("Оценка справедливости"):
        show_result(query(FAIR_PRICE_SQL, {"kato": selected_kato, "year": selected_year}))
with col3:
    if st.button("Анализ объемов ТРУ"):
        show_result(query(VOLUME_SQL, {"bin": selected_bin}))

tab_overview, tab_lots, tab_contracts, tab_analytics = st.tabs(["Обзор", "Лоты", "Договоры", "Аналитика"])
with tab_overview:
    st.write("Используйте быстрые кнопки выше или задайте вопрос в чате ниже.")
with tab_lots:
    lot_rows = query("""
        SELECT id, lot_number, name_ru, amount, count, kato_code, dumping, export_year
        FROM fact_lots WHERE customer_bin = :bin AND export_year = :year
        ORDER BY amount DESC NULLS LAST LIMIT 500
    """, {"bin": selected_bin, "year": selected_year})
    show_result(lot_rows)
    if lot_rows:
        lot_df = pd.DataFrame(lot_rows)
        d1, d2 = st.columns(2)
        d1.download_button("Скачать лоты CSV", lot_df.to_csv(index=False).encode("utf-8-sig"), "lots.csv", "text/csv")
        d2.download_button("Скачать лоты Excel", _excel_bytes(lot_df), "lots.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
with tab_contracts:
    contract_rows = query("""
        SELECT id, contract_number, contract_sum_wnds, supplier_biin, sign_date, fin_year
        FROM fact_contracts WHERE customer_bin = :bin AND fin_year = :year
        ORDER BY contract_sum_wnds DESC NULLS LAST LIMIT 500
    """, {"bin": selected_bin, "year": selected_year})
    show_result(contract_rows)
    if contract_rows:
        contract_df = pd.DataFrame(contract_rows)
        d1, d2 = st.columns(2)
        d1.download_button("Скачать договоры CSV", contract_df.to_csv(index=False).encode("utf-8-sig"), "contracts.csv", "text/csv")
        d2.download_button("Скачать договоры Excel", _excel_bytes(contract_df), "contracts.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
with tab_analytics:
    show_result(query(VOLUME_SQL, {"bin": selected_bin}))

if "messages" not in st.session_state: st.session_state.messages = []
for message in st.session_state.messages:
    with st.chat_message(message["role"]): st.markdown(message["content"])
if prompt := st.chat_input("Задайте вопрос по закупкам"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    result = chat_answer(prompt, selected_bin, selected_year)
    if result is None:
        answer = "Не распознал запрос. Попробуйте: закупки, дорогие лоты, аномалии, объемы, поставщики, договоры, демпинг или КАТО."
        st.session_state.messages.append({"role": "assistant", "content": answer})
        with st.chat_message("assistant"): st.markdown(answer)
    else:
        title, rows = result
        st.session_state.messages.append({"role": "assistant", "content": f"{title}. Найдено записей: {len(rows)}"})
        with st.chat_message("assistant"):
            st.write(f"{title}. Найдено записей: {len(rows)}")
            show_result(rows)
