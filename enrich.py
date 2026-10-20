"""Дополнительная выгрузка объявлений и справочников OWS v3."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urljoin

import requests

from exporter import (
    GraphQLClient,
    Settings,
    TARGET_BINS,
    YEARS,
    export_records,
    iter_graphql_pages,
    load_query,
)


LOGGER = logging.getLogger("ows_enrich")
REFERENCE_ENDPOINTS = (
    "ref_lots_status",
    "ref_trade_methods",
    "ref_units",
    "ref_pln_point_status",
    "ref_subject_type",
    "ref_buy_status",
    "ref_type_trade",
    "ref_contract_status",
    "ref_currency",
    "ref_finsource",
    "ref_kato",
)


def announcement_in_period(row: dict[str, Any]) -> bool:
    publish_date = row.get("publishDate")
    if publish_date:
        try:
            return int(str(publish_date)[:4]) in YEARS
        except ValueError:
            return False
    years = row.get("finYear") or []
    if not isinstance(years, list):
        years = [years]
    return any(int(year) in YEARS for year in years if year is not None)


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def chunks(values: Iterable[int], size: int = 100) -> Iterator[list[int]]:
    chunk: list[int] = []
    for value in values:
        chunk.append(value)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def fetch_announcements(client: GraphQLClient, settings: Settings, source: Path) -> list[dict[str, Any]]:
    query = load_query("announcements")
    result: dict[int, dict[str, Any]] = {}
    ids = sorted(
        {
            int(row["trdBuyId"])
            for row in read_jsonl(source / "lots.jsonl")
            if row.get("trdBuyId") is not None
        }
    )
    LOGGER.info("Объявления по %s ID лотов", len(ids))
    for position, id_chunk in enumerate(chunks(ids), start=1):
        for page in iter_graphql_pages(
            client,
            query,
            "TrdBuy",
            {"filter": {"id": id_chunk}, "limit": settings.page_size},
            null_is_empty=True,
        ):
            result.update({int(row["id"]): row for row in page})
        if position % 50 == 0:
            LOGGER.info("Обработано пакетов ID: %s", position)

    # Дополняем объявления, где целевой БИН выступал только организатором.
    for bin_value in TARGET_BINS:
        for year in YEARS:
            for page in iter_graphql_pages(
                client,
                query,
                "TrdBuy",
                {
                    "filter": {"orgBin": bin_value, "finYear": year},
                    "limit": settings.page_size,
                },
            ):
                result.update({int(row["id"]): row for row in page})
    return [row for row in result.values() if announcement_in_period(row)]


def fetch_related_plans(
    client: GraphQLClient, settings: Settings, source: Path
) -> list[dict[str, Any]]:
    existing_ids = {int(row["id"]) for row in read_jsonl(source / "plans.jsonl")}
    ids = sorted(
        {
            int(plan_id)
            for row in read_jsonl(source / "lots.jsonl")
            for plan_id in (row.get("pointList") or [])
            if plan_id is not None
            and int(plan_id) not in existing_ids
        }
    )
    query = load_query("related_plans")
    result: dict[int, dict[str, Any]] = {}
    LOGGER.info("Связанные пункты планов по %s ID", len(ids))
    for position, id_chunk in enumerate(chunks(ids), start=1):
        for page in iter_graphql_pages(
            client,
            query,
            "Plans",
            {"filter": {"id": id_chunk}, "limit": settings.page_size},
        ):
            result.update({int(row["id"]): row for row in page})
        if position % 50 == 0:
            LOGGER.info("Связанные планы, пакетов: %s", position)
    return list(result.values())


def fetch_lots_with_plans(
    client: GraphQLClient, settings: Settings, source: Path
) -> list[dict[str, Any]]:
    existing_ids = {int(row["id"]) for row in read_jsonl(source / "plans.jsonl")}
    lot_ids = sorted(
        {
            int(row["id"])
            for row in read_jsonl(source / "lots.jsonl")
            if any(int(plan_id) not in existing_ids for plan_id in (row.get("pointList") or []))
        }
    )
    query = load_query("lots_with_plans")
    result: dict[int, dict[str, Any]] = {}
    LOGGER.info("Лоты с архивными pointList: %s", len(lot_ids))
    for position, id_chunk in enumerate(chunks(lot_ids), start=1):
        for page in iter_graphql_pages(
            client,
            query,
            "Lots",
            {"filter": {"id": id_chunk}, "limit": settings.page_size},
            null_is_empty=True,
        ):
            result.update({int(row["id"]): row for row in page})
        if position % 50 == 0:
            LOGGER.info("Лоты со связанными планами, пакетов: %s", position)
    return list(result.values())


def fetch_rest_collection(client: GraphQLClient, api_url: str, endpoint: str) -> list[dict[str, Any]]:
    base_url = api_url.split("/v3/graphql", 1)[0]
    next_url = f"{base_url}/v3/refs/{endpoint}"
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    while next_url:
        if next_url in seen_urls:
            raise RuntimeError(f"Зацикленная REST-пагинация: {endpoint}")
        seen_urls.add(next_url)
        response = None
        for attempt in range(1, 4):
            try:
                response = client.session.get(next_url, timeout=(15, client.timeout))
                response.raise_for_status()
                break
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt - 1))
        assert response is not None
        payload = response.json()
        items = payload.get("items")
        if items is None and payload.get("total") == 0:
            break
        if not isinstance(items, list):
            raise RuntimeError(f"Некорректный ответ справочника {endpoint}: {payload.get('error', 'items missing')}")
        rows.extend(items)
        relative = payload.get("next_page") or ""
        next_url = urljoin(base_url, relative) if relative else ""
    return rows


def observed_enstru(source: Path) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(source / "plans.jsonl"):
        code = row.get("refEnstruCode")
        if not code:
            continue
        result[str(code)] = {
            "code": code,
            "id": row.get("refEnstruId"),
            "sample_name_ru": row.get("nameRu"),
            "sample_name_kz": row.get("nameKz"),
            "source": "observed_in_plans",
        }
    return list(result.values())


def fetch_observed_currencies(
    client: GraphQLClient, api_url: str, source: Path
) -> list[dict[str, Any]]:
    base_url = api_url.split("/v3/graphql", 1)[0]
    codes = {
        str(row["refCurrencyCode"])
        for row in read_jsonl(source / "contracts.jsonl")
        if row.get("refCurrencyCode")
    }
    result: list[dict[str, Any]] = []
    for code in sorted(codes):
        response = client.session.get(
            f"{base_url}/v3/refs/ref_currency/{code}",
            timeout=(15, client.timeout),
        )
        response.raise_for_status()
        items = response.json().get("items") or []
        result.extend(items)
    return result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Обогащение выгрузки OWS")
    parser.add_argument("--skip-announcements", action="store_true")
    args = parser.parse_args()
    source = Path("data/export")
    output = Path("data/enriched")
    refs_output = output / "references"
    settings = Settings.from_env()
    client = GraphQLClient(settings)

    stats: dict[str, int] = {}
    announcements_file = output / "announcements.jsonl"
    if args.skip_announcements and announcements_file.exists():
        existing_announcements = [
            row for row in read_jsonl(announcements_file) if announcement_in_period(row)
        ]
        stats["announcements"] = export_records(
            "announcements", existing_announcements, output
        )["written"]
        LOGGER.info("Объявления уже сохранены: %s", stats["announcements"])
    else:
        announcements = fetch_announcements(client, settings, source)
        stats["announcements"] = export_records("announcements", announcements, output)["written"]
        LOGGER.info("Объявления сохранены: %s", stats["announcements"])

    related_path = output / "related_plans.jsonl"
    if related_path.exists():
        stats["related_plans"] = sum(1 for _ in read_jsonl(related_path))
    else:
        related_plans = fetch_related_plans(client, settings, source)
        stats["related_plans"] = export_records(
            "related_plans", related_plans, output
        )["written"]
    LOGGER.info("Связанные пункты планов: %s", stats["related_plans"])

    lots_with_plans_path = output / "lots_with_plans.jsonl"
    if lots_with_plans_path.exists():
        stats["lots_with_plans"] = sum(1 for _ in read_jsonl(lots_with_plans_path))
    else:
        rows = fetch_lots_with_plans(client, settings, source)
        stats["lots_with_plans"] = export_records(
            "lots_with_plans", rows, output
        )["written"]
    LOGGER.info("Лоты со связанными планами: %s", stats["lots_with_plans"])

    observed_kato = {
        str(code)
        for row in read_jsonl(source / "lots.jsonl")
        for code in (row.get("plnPointKatoList") or [])
        if code
    }
    failed: list[str] = []
    for endpoint in REFERENCE_ENDPOINTS:
        existing = refs_output / f"{endpoint}.jsonl"
        if existing.exists():
            stats[endpoint] = sum(1 for _ in read_jsonl(existing))
            LOGGER.info("%s уже сохранён: %s", endpoint, stats[endpoint])
            continue
        try:
            if endpoint == "ref_currency":
                # Общий endpoint валют OWS зацикливает next_page; берём только
                # фактически используемые в договорах коды через detail endpoint.
                rows = fetch_observed_currencies(client, settings.api_url, source)
            else:
                rows = fetch_rest_collection(client, settings.api_url, endpoint)
            if endpoint == "ref_kato":
                rows = [row for row in rows if str(row.get("code")) in observed_kato]
            stats[endpoint] = export_records(endpoint, rows, refs_output)["written"]
            LOGGER.info("%s: %s", endpoint, stats[endpoint])
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            LOGGER.error("Справочник %s пропущен: %s", endpoint, exc)
            failed.append(endpoint)

    enstru_rows = observed_enstru(source)
    stats["ref_enstru_observed"] = export_records(
        "ref_enstru_observed", enstru_rows, refs_output
    )["written"]
    (output / "manifest.json").write_text(
        json.dumps({"counts": stats, "failed": failed}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    failed_path = output / "failed_references.txt"
    if failed:
        failed_path.write_text("\n".join(failed) + "\n", encoding="utf-8")
    elif failed_path.exists():
        failed_path.unlink()
    print(json.dumps({"counts": stats, "failed": failed}, ensure_ascii=False))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
