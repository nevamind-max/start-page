"""
Інтерактивне демо дашборду артиста (/demo).

Повторює демо-режим репозиторію nevamind-max/dashboard: ті самі вигадані,
детерміновані дані (demo_stats.py) і той самий формат відповідей API, тож
шаблон templates/demo_dashboard.html — це майже без змін dashboard.html.
До Shopify не звертаємось.
"""

import random
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request

import demo_stats as stats

DEMO_DISPLAY_NAME = "Ваш гурт"
DEMO_COMMISSION_RATE = 0.2   # тариф «Делегуючий»
LOW_STOCK_THRESHOLD = 3

bp = Blueprint("demo", __name__)


def pct_change(current, previous):
    if previous == 0:
        return None if current == 0 else 100.0
    return round((current - previous) / previous * 100, 1)


def compute_product_highlights(current_products, comp_products):
    cur_by_title = {p["title"]: p["revenue"] for p in current_products}
    comp_by_title = {p["title"]: p["revenue"] for p in comp_products}
    best_growth = best_decline = None
    for title in set(cur_by_title) | set(comp_by_title):
        cur, prev = cur_by_title.get(title, 0), comp_by_title.get(title, 0)
        if cur == 0 and prev == 0:
            continue
        change = pct_change(cur, prev)
        if change is None:
            continue
        if best_growth is None or change > best_growth[1]:
            best_growth = (title, change)
        if best_decline is None or change < best_decline[1]:
            best_decline = (title, change)
    result = {}
    if best_growth and best_growth[1] > 0:
        result["top_growth"] = {"title": best_growth[0], "change": best_growth[1]}
    if best_decline and best_decline[1] < 0:
        result["top_decline"] = {"title": best_decline[0], "change": best_decline[1]}
    return result


def _period(start_dt, end_dt):
    sales, refunds = stats.demo_rows(start_dt, end_dt)
    return stats.compute(sales, refunds, start_dt, end_dt, DEMO_COMMISSION_RATE, {})


@bp.get("/demo")
def page():
    return render_template("demo_dashboard.html")


@bp.get("/demo/api/stats")
def demo_stats():
    try:
        start_dt, end_dt, comp_start, comp_end = stats.resolve_period(
            request.args.get("period", "this_month"), request.args.get("start"), request.args.get("end"))
    except ValueError:
        return jsonify({"error": "Невірний формат дати. Використовуйте YYYY-MM-DD."}), 400
    if (end_dt - start_dt).days > 400:
        return jsonify({"error": "Оберіть період до року."}), 400

    data = _period(start_dt, end_dt)
    comp = _period(comp_start, comp_end)
    daily = data.pop("daily")
    comparison_daily = comp.pop("daily")

    trend = {k: pct_change(data[k], comp[k]) for k in
             ("revenue", "net_revenue", "orders_count", "items_sold", "avg_order_value", "returns_amount")}
    highlight = compute_product_highlights(
        [{"title": p["title"], "revenue": p["net"]} for p in data["products"]],
        [{"title": p["title"], "revenue": p["net"]} for p in comp["products"]],
    )
    return jsonify({
        "vendor": DEMO_DISPLAY_NAME,
        "period": {"start": start_dt.date().isoformat(), "end": end_dt.date().isoformat()},
        "comparison_period": {"start": comp_start.date().isoformat(), "end": comp_end.date().isoformat()},
        "trend": trend,
        "daily": daily,
        "comparison_daily": comparison_daily,
        "product_highlight": highlight,
        "limited_history_since": None,
        "history_since": None,
        "commission_rate": round(DEMO_COMMISSION_RATE * 100, 2),
        "has_product_rates": False,
        **data,
    })


@bp.get("/demo/api/inventory")
def demo_inventory():
    rng = random.Random("demo-inventory")
    items = []
    for title, _, _, variants in stats.DEMO_PRODUCTS:
        for v in variants:
            items.append({"product": title, "variant": v, "sku": "",
                          "quantity": rng.choice([0, 1, 2, 3, 5, 8, 12, 20]), "tracked": True})
    return jsonify({
        "vendor": DEMO_DISPLAY_NAME,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "low_stock_threshold": LOW_STOCK_THRESHOLD,
        "summary": {
            "products_count": len({i["product"] for i in items}),
            "units_total": sum(max(0, i["quantity"]) for i in items),
            "low_stock_count": sum(1 for i in items if 0 < i["quantity"] <= LOW_STOCK_THRESHOLD),
            "out_of_stock_count": sum(1 for i in items if i["quantity"] <= 0),
        },
        "items": items,
    })
