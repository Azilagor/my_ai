import csv
import json

import pytest
import requests

from exporter import CursorError, GraphQLClient, export_records, iter_graphql_pages


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def execute(self, query, variables):
        self.calls.append(dict(variables))
        return next(self.responses)


def test_cursor_pagination_stops_when_total_is_reached():
    client = FakeClient(
        [
            {
                "data": {"Plans": [{"id": 1}, {"id": 2}]},
                "extensions": {
                    "pageInfo": {
                        "totalCount": 2,
                        "hasNextPage": True,
                        "lastId": 2,
                    }
                },
            }
        ]
    )

    pages = list(iter_graphql_pages(client, "query", "Plans", {"limit": 2}))

    assert pages == [[{"id": 1}, {"id": 2}]]
    assert client.calls == [{"limit": 2, "after": None}]


def test_cursor_pagination_rejects_repeated_cursor():
    response = {
        "data": {"Plans": [{"id": 1}]},
        "extensions": {
            "pageInfo": {"totalCount": 3, "hasNextPage": True, "lastId": 1}
        },
    }
    client = FakeClient([response, response])

    with pytest.raises(CursorError, match="повторяющийся курсор"):
        list(iter_graphql_pages(client, "query", "Plans", {"limit": 1}))


def test_cursor_pagination_accepts_null_for_zero_total():
    client = FakeClient(
        [
            {
                "data": {"Contract": None},
                "extensions": {
                    "pageInfo": {
                        "totalCount": 0,
                        "hasNextPage": False,
                        "lastId": 0,
                    }
                },
            }
        ]
    )

    assert list(iter_graphql_pages(client, "query", "Contract", {"limit": 1})) == []


def test_cursor_pagination_can_accept_null_for_missing_id_filter():
    client = FakeClient([{"data": {"Plans": None}, "extensions": {}}])

    assert list(
        iter_graphql_pages(
            client, "query", "Plans", {"filter": {"id": [999]}, "limit": 1}, null_is_empty=True
        )
    ) == []


def test_export_records_writes_deduplicated_jsonl_and_csv(tmp_path):
    records = [
        {"id": 1, "nameRu": "Первый", "years": [2024, 2025]},
        {"id": 1, "nameRu": "Обновлённый", "years": [2026]},
        {"id": 2, "nameRu": "Второй", "years": []},
    ]

    stats = export_records("plans", records, tmp_path)

    assert stats == {"received": 3, "written": 2}
    json_rows = [json.loads(line) for line in (tmp_path / "plans.jsonl").read_text().splitlines()]
    assert json_rows[0]["nameRu"] == "Обновлённый"
    with (tmp_path / "plans.csv").open(newline="", encoding="utf-8-sig") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert csv_rows[0]["years"] == "[2026]"
    assert len(csv_rows) == 2


def test_graphql_client_retries_connection_error(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"Plans": []}}

    class Session:
        headers = {}

        def __init__(self):
            self.calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise requests.ConnectionError("read timed out")
            return Response()

    client = GraphQLClient.__new__(GraphQLClient)
    client.url = "https://example.invalid/graphql"
    client.timeout = 10
    client.session = Session()
    monkeypatch.setattr("exporter.time.sleep", lambda _: None)

    assert client.execute("query", {}) == {"data": {"Plans": []}}
    assert client.session.calls == 2
