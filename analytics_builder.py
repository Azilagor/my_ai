"""Построение плоских аналитических витрин из выгрузки OWS v3."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


YEARS = (2024, 2025, 2026)
GARBAGE = {"", "-", "--", "---", "!", "!!", "!!!", "н/д", "нет данных", "null", "none"}


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).replace("№", "__NUMBER_SIGN__")
    text = unicodedata.normalize("NFKC", raw).replace("__NUMBER_SIGN__", "№")
    text = "".join(char if char.isprintable() else " " for char in text)
    text = re.sub(r"\s+", " ", text).strip()
    marker = re.sub(r"[!?.\-_]+", " ", text)
    marker = re.sub(r"\s+", " ", marker).strip().casefold()
    if text.casefold() in GARBAGE or marker in GARBAGE:
        return None
    text = re.sub(r"\s*-{2,}\s*", " - ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text.casefold() not in GARBAGE else None


def to_decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def build_lot_rows(
    lots: Iterable[Mapping[str, Any]],
    plans: Mapping[int, Mapping[str, Any]],
    announcements: Mapping[int, Mapping[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
    announcements = announcements or {}
    for lot in lots:
        amount = to_decimal(lot.get("amount"))
        count = to_decimal(lot.get("count"))
        unit_price = amount / count if count else Decimal("0")
        nested_plans = lot.get("Plans") or []
        plan_pairs = (
            [(item.get("id"), item) for item in nested_plans]
            if nested_plans
            else [(point_id, plans.get(int(point_id)) if point_id is not None else None)
                  for point_id in (lot.get("pointList") or [None])]
        )
        kato_values = lot.get("plnPointKatoList") or [None]
        for point_id, plan in plan_pairs:
            plan_kato = (plan or {}).get("PlansKato") or []
            kato_code = kato_values[0]
            if not kato_code and plan_kato:
                kato_code = plan_kato[0].get("refKatoCode")
            announcement = announcements.get(int(lot["trdBuyId"])) if lot.get("trdBuyId") else None
            if not kato_code and announcement:
                announcement_kato = announcement.get("kato") or []
                kato_code = announcement_kato[0] if announcement_kato else None
            yield {
                "lot_id": lot.get("id"),
                "lot_number": lot.get("lotNumber"),
                "plan_id": point_id,
                "customer_bin": lot.get("customerBin"),
                "year": lot.get("exportYear"),
                "ref_enstru_code": plan.get("refEnstruCode") if plan else None,
                "ref_enstru_id": plan.get("refEnstruId") if plan else None,
                "unit_code": plan.get("refUnitsCode") if plan else None,
                "kato_code": kato_code,
                "count": count,
                "amount": amount,
                "unit_price": unit_price,
                "plan_price": to_decimal(plan.get("price")) if plan else Decimal("0"),
                "dumping": lot.get("dumping"),
                "lot_status_id": lot.get("refLotStatusId"),
                "trade_method_id": lot.get("refBuyTradeMethodsId") or lot.get("refTradeMethodsId"),
                "announcement_id": lot.get("trdBuyId"),
                "announcement_number": lot.get("trdBuyNumberAnno"),
                "name_ru": clean_text(lot.get("nameRu")),
                "description_ru": clean_text(lot.get("descriptionRu")),
            }


def build_volume_rows(plans: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[int, dict[str, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": Decimal("0"), "amount": Decimal("0")})
    )
    for plan in plans:
        year = int(plan.get("plnPointYear") or 0)
        if year not in YEARS:
            continue
        key = (str(plan.get("subjectBiin") or ""), str(plan.get("refEnstruCode") or ""))
        grouped[key][year]["count"] += to_decimal(plan.get("count"))
        grouped[key][year]["amount"] += to_decimal(plan.get("amount"))

    result = []
    for (bin_value, enstru), values in sorted(grouped.items()):
        row: dict[str, Any] = {"subject_biin": bin_value, "ref_enstru_code": enstru}
        for year in YEARS:
            row[f"count_{year}"] = values[year]["count"]
            row[f"amount_{year}"] = values[year]["amount"]
        for previous, current in ((2024, 2025), (2025, 2026)):
            base = row[f"count_{previous}"]
            row[f"change_{current}_pct"] = (
                ((row[f"count_{current}"] - base) / base * 100).quantize(Decimal("0.01"))
                if base
                else None
            )
        result.append(row)
    return result


def _serializable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def write_rows(name: str, rows: Iterable[Mapping[str, Any]], output_dir: Path) -> int:
    data = [dict(row) for row in rows]
    output_dir.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in data for key in row})
    with (output_dir / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
        for row in data:
            handle.write(json.dumps(row, ensure_ascii=False, default=_serializable) + "\n")
    with (output_dir / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in data:
            writer.writerow({key: _serializable(value) for key, value in row.items()})
    return len(data)


def main() -> int:
    source = Path("data/export")
    output = Path("data/analytics")
    plans_list = list(read_jsonl(source / "plans.jsonl"))
    related_path = Path("data/enriched/related_plans.jsonl")
    if related_path.exists():
        plans_list.extend(read_jsonl(related_path))
    plans = {int(row["id"]): row for row in plans_list}
    lots_by_id = {int(row["id"]): row for row in read_jsonl(source / "lots.jsonl")}
    enriched_lots = Path("data/enriched/lots_with_plans.jsonl")
    if enriched_lots.exists():
        lots_by_id.update({int(row["id"]): row for row in read_jsonl(enriched_lots)})
    lots = lots_by_id.values()
    announcements = {
        int(row["id"]): row for row in read_jsonl(Path("data/enriched/announcements.jsonl"))
    }
    lot_count = write_rows(
        "lot_price_analysis", build_lot_rows(lots, plans, announcements), output
    )
    volume_count = write_rows("volume_by_year", build_volume_rows(plans_list), output)

    contract_rows = (
        {
            "contract_id": row.get("id"),
            "contract_number": row.get("contractNumber"),
            "year": row.get("finYear"),
            "customer_bin": row.get("customerBin"),
            "supplier_biin": row.get("supplierBiin"),
            "contract_sum_wnds": row.get("contractSumWnds"),
            "contract_status_id": row.get("refContractStatusId"),
            "subject_type_id": row.get("refSubjectTypeId"),
            "trade_method_id": row.get("faktTradeMethodsId"),
            "sign_date": row.get("signDate"),
            "announcement_id": row.get("trdBuyId"),
            "description_ru": clean_text(row.get("descriptionRu")),
        }
        for row in read_jsonl(source / "contracts.jsonl")
    )
    contract_count = write_rows("contract_analysis", contract_rows, output)
    summary = {
        "lot_price_analysis": lot_count,
        "volume_by_year": volume_count,
        "contract_analysis": contract_count,
    }
    (output / "manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
