"""Financial-analysis commentary: computed ratios + selected strengths/weaknesses."""
from __future__ import annotations

from app.services.commentary import build_commentary


def test_ratios_computed_from_statements():
    c = build_commentary()
    m = {x["key"]: x["value"] for x in c["metrics"]}
    # current assets 3,30,800 / current liabilities (54000+92200+21400+11900=179500)
    assert round(m["current_ratio"], 2) == round(330800 / 179500, 2)
    # debt (142000+54000) / equity (12000+589000)
    assert round(m["debt_to_equity"], 2) == round(196000 / 601000, 2)
    assert m["revenue_growth"] > 0


def test_strengths_and_weaknesses_selected():
    c = build_commentary(open_review_items=12)
    # low leverage + strong coverage → strengths present
    assert any("conservatively financed" in s for s in c["strengths"])
    assert any("interest coverage" in s.lower() for s in c["strengths"])
    # open review items → provisional-figures weakness present
    assert any("provisional" in w for w in c["weaknesses"])
    assert c["headline"]


def test_trends_computed_year_on_year():
    c = build_commentary()
    trends = {t["key"]: t for t in c["trends"]}
    # Revenue rose FY24→FY25 → favourable "up".
    assert trends["revenue"]["direction"] == "up" and trends["revenue"]["favorable"]
    assert trends["revenue"]["delta"] == round((964700 - 901300) / 901300 * 100, 1)
    # Lower leverage is favourable even though the number went down.
    assert trends["debt_to_equity"]["direction"] == "down"
    assert trends["debt_to_equity"]["favorable"] and trends["debt_to_equity"]["tone"] == "good"
    # Net margin is a percentage-point delta.
    assert trends["net_margin"]["kind"] == "percent"


def test_commentary_endpoint_and_localization(client):
    r = client.get("/api/v1/projects/demo/commentary")
    assert r.status_code == 200
    body = r.json()
    assert body["metrics"] and body["strengths"] and body["weaknesses"] and body["trends"]

    zh = client.get("/api/v1/projects/demo/commentary?locale=zh").json()
    labels = {m["label"] for m in zh["metrics"]}
    assert "流动比率" in labels           # Current ratio localized
    assert zh["headline"] != body["headline"]  # headline localized
    # Trend labels localize too.
    zh_trends = {t["key"]: t["label"] for t in zh["trends"]}
    assert zh_trends["revenue"] == "营业收入"
