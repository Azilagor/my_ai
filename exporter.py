"""Выгрузка OWS v3 GraphQL в JSONL и CSV без раскрытия токена."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LOGGER = logging.getLogger("ows_export")
YEARS = (2024, 2025, 2026)
TARGET_BINS = (
    "000740001307", "020240002363", "020440003656", "030440003698",
    "050740004819", "051040005150", "100140011059", "120940001946",
    "140340016539", "150540000186", "171041003124", "210240019348",
    "210240033968", "210941010761", "230740013340", "231040023028",
    "780140000023", "900640000128", "940740000911", "940940000384",
    "960440000220", "970940001378", "971040001050", "980440001034",
    "981140001551", "990340005977", "990740002243",
)


class GraphQLError(RuntimeError):
    """Безопасная ошибка GraphQL без данных авторизации."""


class CursorError(GraphQLError):
    """Сервер вернул некорректную последовательность курсоров."""


@dataclass(frozen=True)
class Settings:
    api_url: str
    token: str
    page_size: int = 200
    timeout_seconds: int = 120

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token = os.getenv("OWS_API_TOKEN") or os.getenv("Token") or ""
        if not token.strip():
            raise ValueError("Добавьте OWS_API_TOKEN (или Token) в .env")
        return cls(
            api_url=os.getenv(
                "OWS_API_URL", "https://ows.goszakup.gov.kz/v3/graphql"
            ),
            token=token.strip(),
            page_size=min(200, max(1, int(os.getenv("OWS_PAGE_SIZE", "200")))),
            timeout_seconds=max(10, int(os.getenv("OWS_TIMEOUT_SECONDS", "120"))),
        )


class GraphQLClient:
    def __init__(self, settings: Settings):
        self.url = settings.api_url
        self.timeout = settings.timeout_seconds
        self.session = requests.Session()
        retry = Retry(
            total=5,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {
                "Authorization": f"Bearer {settings.token}",
                "Content-Type": "application/json",
                "User-Agent": "goszakup-etl/1.0",
            }
        )

    def execute(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        response = None
        for attempt in range(1, 4):
            try:
                response = self.session.post(
                    self.url,
                    json={"query": query, "variables": dict(variables)},
                    timeout=(15, self.timeout),
                )
                break
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 3:
                    raise
                LOGGER.warning("Сетевая ошибка OWS, повтор страницы %s/3", attempt + 1)
                time.sleep(2 ** (attempt - 1))
        assert response is not None
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            messages = [str(item.get("message", "GraphQL error")) for item in payload["errors"]]
            raise GraphQLError("; ".join(messages))
        if not isinstance(payload.get("data"), dict):
            raise GraphQLError("OWS вернул ответ без объекта data")
        return payload


def iter_graphql_pages(
    client: Any,
    query: str,
    root_field: str,
    variables: Mapping[str, Any],
    *,
    max_pages: int | None = None,
    null_is_empty: bool = False,
) -> Iterator[list[dict[str, Any]]]:
    """Проходит курсорные страницы и защищается от зацикливания API."""
    base = dict(variables)
    after = base.pop("after", None)
    seen_cursors: set[Any] = set()
    received = 0
    page_number = 0

    while True:
        request_variables = {**base, "after": after}
        payload = client.execute(query, request_variables)
        rows = payload["data"].get(root_field)
        page_info = payload.get("extensions", {}).get("pageInfo", {})
        if rows is None and (page_info.get("totalCount") == 0 or null_is_empty):
            return
        if not isinstance(rows, list):
            raise GraphQLError(f"Поле data.{root_field} отсутствует или не является списком")

        page_number += 1
        if rows:
            received += len(rows)
            yield rows

        total = page_info.get("totalCount")
        has_next = bool(page_info.get("hasNextPage"))
        if max_pages is not None and page_number >= max_pages:
            return
        if total is not None and received >= int(total):
            return
        if not has_next or not rows:
            return

        cursor = page_info.get("lastId")
        if cursor is None:
            raise CursorError("hasNextPage=true, но lastId отсутствует")
        if cursor == after or cursor in seen_cursors:
            raise CursorError(f"OWS вернул повторяющийся курсор lastId={cursor}")
        seen_cursors.add(cursor)
        after = cursor


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def export_records(name: str, records: Iterable[dict[str, Any]], output_dir: Path) -> dict[str, int]:
    """Атомарно сохраняет дедуплицированные записи в JSONL и CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    received = 0
    unique: dict[str, dict[str, Any]] = {}
    without_id: list[dict[str, Any]] = []
    for record in records:
        received += 1
        key = record.get("id", record.get("pid"))
        if key is None:
            without_id.append(record)
        else:
            unique[str(key)] = record
    rows = list(unique.values()) + without_id
    rows.sort(key=lambda item: str(item.get("id", item.get("pid", ""))))

    json_tmp = output_dir / f".{name}.jsonl.tmp"
    csv_tmp = output_dir / f".{name}.csv.tmp"
    with json_tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    columns = sorted({key for row in rows for key in row})
    with csv_tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(value) for key, value in row.items()})

    json_tmp.replace(output_dir / f"{name}.jsonl")
    csv_tmp.replace(output_dir / f"{name}.csv")
    return {"received": received, "written": len(rows)}


def load_query(name: str) -> str:
    return (Path(__file__).parent / "queries" / f"{name}.graphql").read_text(encoding="utf-8")


def _year_from_lot(row: Mapping[str, Any]) -> int | None:
    trade = row.get("TrdBuy") or {}
    value = trade.get("publishDate") or row.get("indexDate") or row.get("lastUpdateDate")
    if not value:
        return None
    try:
        return int(str(value)[:4])
    except ValueError:
        return None


def collect_entities(
    client: GraphQLClient,
    settings: Settings,
    entities: Iterable[str],
    bins: Iterable[str],
    *,
    max_pages: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    requested = set(entities)
    result = {name: [] for name in requested}
    for bin_value in bins:
        LOGGER.info("Организация %s", bin_value)
        if "subjects" in requested:
            for page in iter_graphql_pages(
                client,
                load_query("subjects"),
                "Subjects",
                {"filter": {"bin": bin_value}, "limit": settings.page_size},
                max_pages=max_pages,
            ):
                result["subjects"].extend(page)

        if "plans" in requested:
            for year in YEARS:
                for page in iter_graphql_pages(
                    client,
                    load_query("plans"),
                    "Plans",
                    {
                        "filter": {"subjectBiin": bin_value, "plnPointYear": year},
                        "limit": settings.page_size,
                    },
                    max_pages=max_pages,
                ):
                    result["plans"].extend(page)

        if "lots" in requested:
            for page in iter_graphql_pages(
                client,
                load_query("lots"),
                "Lots",
                {"filter": {"customerBin": bin_value}, "limit": settings.page_size},
                max_pages=max_pages,
            ):
                for row in page:
                    year = _year_from_lot(row)
                    if year in YEARS:
                        row["exportYear"] = year
                        result["lots"].append(row)

        if "contracts" in requested:
            for year in YEARS:
                for party_filter in ("customerBin", "supplierBiin"):
                    for page in iter_graphql_pages(
                        client,
                        load_query("contracts"),
                        "Contract",
                        {
                            "filter": {party_filter: bin_value, "finYear": year},
                            "limit": settings.page_size,
                        },
                        max_pages=max_pages,
                    ):
                        result["contracts"].extend(page)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Выгрузка данных OWS v3 в JSONL и CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("data/export"))
    parser.add_argument(
        "--entities",
        nargs="+",
        choices=("subjects", "plans", "lots", "contracts"),
        default=("subjects", "plans", "lots", "contracts"),
    )
    parser.add_argument("--bins", nargs="+", default=TARGET_BINS)
    parser.add_argument("--max-pages", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    settings = Settings.from_env()
    client = GraphQLClient(settings)
    accumulated = {entity: [] for entity in args.entities}
    failed_bins: list[str] = []
    for position, bin_value in enumerate(args.bins, start=1):
        try:
            chunk = collect_entities(
                client,
                settings,
                args.entities,
                [bin_value],
                max_pages=args.max_pages,
            )
        except (GraphQLError, requests.RequestException) as exc:
            LOGGER.error("БИН %s пропущен после повторов: %s", bin_value, exc)
            failed_bins.append(bin_value)
            continue

        for entity, rows in chunk.items():
            accumulated[entity].extend(rows)
            export_records(entity, accumulated[entity], args.output_dir)
        LOGGER.info("Checkpoint %s/%s сохранён", position, len(args.bins))

    for entity, rows in accumulated.items():
        stats = export_records(entity, rows, args.output_dir)
        LOGGER.info(
            "%s: получено=%s, сохранено=%s",
            entity,
            stats["received"],
            stats["written"],
        )
    if failed_bins:
        (args.output_dir / "failed_bins.txt").write_text(
            "\n".join(failed_bins) + "\n", encoding="utf-8"
        )
        LOGGER.error("Не выгружены БИН: %s", ", ".join(failed_bins))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
