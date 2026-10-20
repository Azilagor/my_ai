from decimal import Decimal

from analytics_builder import build_lot_rows, build_volume_rows, clean_text


def test_clean_text_removes_noise_but_preserves_meaningful_punctuation():
    assert clean_text("  !!!  н/д  ") is None
    assert clean_text("  Кабель --- силовой № 2  ") == "Кабель - силовой № 2"


def test_build_lot_rows_joins_each_plan_and_derives_unit_price():
    plans = {
        10: {
            "id": 10,
            "subjectBiin": "000740001307",
            "plnPointYear": 2025,
            "refEnstruCode": "123456.100.000000",
            "refUnitsCode": "796",
            "count": 4,
            "price": 25,
            "PlansKato": [{"refKatoCode": "710000000"}],
        }
    }
    lots = [
        {
            "id": 7,
            "lotNumber": "7-1",
            "customerBin": "000740001307",
            "nameRu": "  Кабель  ",
            "amount": 120,
            "count": 4,
            "pointList": [10],
            "plnPointKatoList": ["750000000"],
            "exportYear": 2025,
        }
    ]

    rows = list(build_lot_rows(lots, plans))

    assert rows[0]["ref_enstru_code"] == "123456.100.000000"
    assert rows[0]["unit_price"] == Decimal("30")
    assert rows[0]["kato_code"] == "750000000"
    assert rows[0]["name_ru"] == "Кабель"


def test_build_lot_rows_uses_plan_kato_when_lot_kato_is_missing():
    plans = {
        10: {
            "id": 10,
            "refEnstruCode": "X",
            "PlansKato": [{"refKatoCode": "710000000"}],
        }
    }
    lots = [{"id": 1, "pointList": [10], "amount": 10, "count": 1}]

    row = next(build_lot_rows(lots, plans))

    assert row["kato_code"] == "710000000"


def test_build_lot_rows_uses_announcement_kato_as_fallback():
    lots = [{"id": 1, "trdBuyId": 77, "amount": 10, "count": 1}]

    row = next(build_lot_rows(lots, {}, {77: {"kato": ["750000000"]}}))

    assert row["kato_code"] == "750000000"


def test_build_volume_rows_aggregates_by_bin_enstru_and_year():
    plans = [
        {"subjectBiin": "A", "plnPointYear": 2024, "refEnstruCode": "X", "count": 2, "amount": 10},
        {"subjectBiin": "A", "plnPointYear": 2024, "refEnstruCode": "X", "count": 3, "amount": 20},
        {"subjectBiin": "A", "plnPointYear": 2025, "refEnstruCode": "X", "count": 10, "amount": 50},
    ]

    rows = build_volume_rows(plans)

    assert rows[0]["count_2024"] == Decimal("5")
    assert rows[0]["count_2025"] == Decimal("10")
    assert rows[0]["change_2025_pct"] == Decimal("100")
