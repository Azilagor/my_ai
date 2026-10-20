from enrich import announcement_in_period


def test_announcement_period_uses_publish_date_before_fin_year():
    assert not announcement_in_period({"publishDate": "2023-12-31", "finYear": [2024]})
    assert announcement_in_period({"publishDate": "2024-01-01", "finYear": [2023]})


def test_announcement_period_falls_back_to_fin_year_when_publish_date_missing():
    assert announcement_in_period({"publishDate": None, "finYear": [2025]})
