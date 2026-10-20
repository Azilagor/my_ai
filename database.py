"""Модели PostgreSQL и безопасный UPSERT для витрин госзакупок."""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping, Type

from dotenv import load_dotenv
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

load_dotenv()

class Base(DeclarativeBase):
    pass

class DimSubject(Base):
    __tablename__ = "dim_subjects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bin: Mapped[str] = mapped_column(String(12), unique=True, index=True, nullable=False)
    name_ru: Mapped[str | None] = mapped_column(Text)
    name_kz: Mapped[str | None] = mapped_column(Text)
    customer: Mapped[int | None] = mapped_column(Integer)
    supplier: Mapped[int | None] = mapped_column(Integer)
    type_supplier: Mapped[int | None] = mapped_column(Integer)
    index_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    last_update_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    plans: Mapped[list["FactPlan"]] = relationship(back_populates="subject")

class FactPlan(Base):
    __tablename__ = "fact_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_biin: Mapped[str] = mapped_column(ForeignKey("dim_subjects.bin", ondelete="RESTRICT"), index=True)
    ref_enstru_code: Mapped[str | None] = mapped_column(String(64), index=True)
    ref_units_code: Mapped[str | None] = mapped_column(String(32))
    count: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    name_ru: Mapped[str | None] = mapped_column(Text)
    pln_point_year: Mapped[int | None] = mapped_column(Integer, index=True)
    date_create: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    subject: Mapped[DimSubject] = relationship(back_populates="plans")

class FactLot(Base):
    __tablename__ = "fact_lots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_bin: Mapped[str] = mapped_column(ForeignKey("dim_subjects.bin", ondelete="RESTRICT"), index=True)
    lot_number: Mapped[str | None] = mapped_column(String(128))
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    count: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    ref_enstru_code: Mapped[str | None] = mapped_column(String(64), index=True)
    name_ru: Mapped[str | None] = mapped_column(Text)
    description_ru: Mapped[str | None] = mapped_column(Text)
    kato_code: Mapped[str | None] = mapped_column(String(32), index=True)
    dumping: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    ref_lot_status_id: Mapped[int | None] = mapped_column(Integer)
    trade_method_id: Mapped[int | None] = mapped_column(Integer)
    publish_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True)
    export_year: Mapped[int | None] = mapped_column(Integer, index=True)

class FactContract(Base):
    __tablename__ = "fact_contracts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_number: Mapped[str | None] = mapped_column(String(128))
    contract_sum_wnds: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    supplier_biin: Mapped[str | None] = mapped_column(ForeignKey("dim_subjects.bin", ondelete="RESTRICT"), index=True)
    customer_bin: Mapped[str | None] = mapped_column(ForeignKey("dim_subjects.bin", ondelete="RESTRICT"), index=True)
    sign_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True)
    fin_year: Mapped[int | None] = mapped_column(Integer, index=True)
    ref_contract_status_id: Mapped[int | None] = mapped_column(Integer)
    ref_currency_code: Mapped[str | None] = mapped_column(String(16))
    description_ru: Mapped[str | None] = mapped_column(Text)

def get_engine(url: str | None = None):
    database_url = url or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL не задан в .env")
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=1800)

def init_db(engine) -> None:
    Base.metadata.create_all(engine)

def _parse_date(value: Any) -> datetime | None:
    if not value: return None
    if isinstance(value, datetime): return value
    text = str(value).replace("T", " ").split(".")[0]
    try: return datetime.fromisoformat(text)
    except ValueError: return None

def _row(model: Type[Base], source: Mapping[str, Any]) -> dict[str, Any]:
    maps = {
        DimSubject: {"id":"pid", "bin":"bin", "name_ru":"nameRu", "name_kz":"nameKz", "customer":"customer", "supplier":"supplier", "type_supplier":"typeSupplier", "index_date":"indexDate", "last_update_date":"lastUpdateDate"},
        FactPlan: {"id":"id", "subject_biin":"subjectBiin", "ref_enstru_code":"refEnstruCode", "ref_units_code":"refUnitsCode", "count":"count", "price":"price", "amount":"amount", "name_ru":"nameRu", "pln_point_year":"plnPointYear", "date_create":"dateCreate", "timestamp":"timestamp"},
        FactLot: {"id":"id", "customer_bin":"customerBin", "lot_number":"lotNumber", "amount":"amount", "count":"count", "name_ru":"nameRu", "description_ru":"descriptionRu", "ref_enstru_code":"refEnstruCode", "dumping":"dumping", "ref_lot_status_id":"refLotStatusId", "trade_method_id":"refBuyTradeMethodsId", "export_year":"exportYear"},
        FactContract: {"id":"id", "contract_number":"contractNumber", "contract_sum_wnds":"contractSumWnds", "supplier_biin":"supplierBiin", "customer_bin":"customerBin", "sign_date":"signDate", "fin_year":"finYear", "ref_contract_status_id":"refContractStatusId", "ref_currency_code":"refCurrencyCode", "description_ru":"descriptionRu"},
    }
    result = {field: source.get(key) for field, key in maps[model].items() if key in source}
    for key in ("index_date", "last_update_date", "date_create", "timestamp", "sign_date"):
        if key in result: result[key] = _parse_date(result[key])
    if model is FactLot and not result.get("export_year"):
        result["export_year"] = _parse_date(source.get("publishDate")) .year if _parse_date(source.get("publishDate")) else None
    if model is FactLot and result.get("amount") is not None and result.get("count"):
        result["price"] = Decimal(str(result["amount"])) / Decimal(str(result["count"]))
    # SQLAlchemy multi-row INSERT требует одинаковый набор ключей во всех строках.
    # Явно добавляем NULL для отсутствующих полей API.
    result = {column.name: result.get(column.name) for column in model.__table__.columns}
    # Пустой BIN — это отсутствие значения, а не реальный внешний ключ.
    for key in ("subject_biin", "customer_bin", "supplier_biin"):
        if key in result and result[key] == "":
            result[key] = None
    return result

def upsert_records(session: Session, model: Type[Base], records: Iterable[Mapping[str, Any]], chunk_size: int = 1000) -> int:
    rows = [_row(model, item) for item in records]
    rows = [item for item in rows if item.get("id") is not None]
    total = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start:start + chunk_size]
        stmt = insert(model).values(chunk)
        update = {column.name: getattr(stmt.excluded, column.name) for column in model.__table__.columns if not column.primary_key}
        session.execute(stmt.on_conflict_do_update(index_elements=[model.__table__.primary_key.columns.values()[0].name], set_=update))
        total += len(chunk)
    session.commit()
    return total

def load_jsonl(engine, source_dir: str = "data/export") -> dict[str, int]:
    import json
    from pathlib import Path
    classes = (("subjects", DimSubject), ("plans", FactPlan), ("lots", FactLot), ("contracts", FactContract))
    counts = {}
    with Session(engine) as session:
        # Сначала dimension: факты ссылаются на BIN внешними ключами.
        subject_path = Path(source_dir) / "subjects.jsonl"
        if subject_path.exists():
            with subject_path.open(encoding="utf-8") as handle:
                counts["subjects"] = upsert_records(session, DimSubject, (json.loads(line) for line in handle if line.strip()))

        # Контрагент может быть вне списка целевых BIN, но FK должен оставаться валидным.
        import hashlib
        bins = set()
        for name in ("plans", "lots", "contracts"):
            path = Path(source_dir) / f"{name}.jsonl"
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        item = json.loads(line)
                        bins.update(filter(None, (item.get("subjectBiin"), item.get("customerBin"), item.get("supplierBiin"))))
        existing = {row[0] for row in session.query(DimSubject.bin).all()}
        # _row для DimSubject использует API-имя первичного ключа `pid`.
        stubs = [{"pid": -(int(hashlib.sha1(value.encode()).hexdigest()[:8], 16) % 2_000_000_000), "bin": value, "nameRu": None} for value in bins - existing]
        if stubs:
            # Отдельный commit гарантирует, что FK видит все dimension-строки.
            upsert_records(session, DimSubject, stubs)

        for name, model in classes:
            if model is DimSubject:
                continue
            path = Path(source_dir) / f"{name}.jsonl"
            if not path.exists(): continue
            with path.open(encoding="utf-8") as handle:
                counts[name] = upsert_records(session, model, (json.loads(line) for line in handle if line.strip()))
    return counts
