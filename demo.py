"""
Інтерактивне демо дашборду артиста (/demo).

Повторює демо-режим репозиторію nevamind-max/dashboard: ті самі вигадані,
детерміновані дані (demo_stats.py) і той самий формат відповідей API, тож
шаблон templates/demo_dashboard.html — це майже без змін dashboard.html.
До Shopify не звертаємось.
"""

import json
import random
from datetime import datetime, timedelta, timezone

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


# ---------- Демо-дані для лендингу ----------
# Статичний набір замовлень: ~12 000 грн за 30 днів, у періоді для порівняння
# ~8 500 грн: рідші замовлення, дешевші кошики й ціни на 8% нижчі. Для коротших чи довших періодів беремо
# пропорційно менше чи більше замовлень і рівномірно розкладаємо їх по днях.
# Шаблон замовлення: [(індекс товару в DEMO_PRODUCTS, варіант, кількість), ...]
CURRENT_ORDERS = [  # 8 замовлень, 5980 грн; за 30 днів — 16 замовлень, 11 960 грн
    [(1, "M / Білий", 1)],
    [(0, "L / Чорний", 1)],
    [(4, "", 2), (5, "", 1)],
    [(1, "L / Білий", 1), (2, "", 1)],
    [(3, "A2", 1)],
    [(1, "S / Білий", 1), (4, "", 1)],
    [(2, "", 1)],
    [(6, "41-45", 1), (5, "", 1)],
]
PREVIOUS_ORDERS = [  # 7 замовлень, 5000 грн (−8% → 4600); за 30 днів — 13 замовлень, ≈8 500 грн
    [(1, "M / Білий", 1)],
    [(2, "", 1)],
    [(0, "M / Чорний", 1)],
    [(3, "A3", 1)],
    [(1, "L / Білий", 1), (4, "", 1)],
    [(4, "", 2), (5, "", 1)],
    [(5, "", 1), (4, "", 2)],
]
CITIES = ["Київ", "Львів", "Київ", "Харків", "Одеса", "Київ", "Дніпро", "Львів", "Вінниця", "Київ"]
DISCOUNT_EVERY = 6      # кожне 6-те замовлення — з промокодом WELCOME10 (−10%)


def _demo_rows(start_dt, end_dt, templates, per_month, price_factor=1.0):
    start = start_dt.date()
    last = min(end_dt.date(), datetime.now(timezone.utc).date())
    days = (last - start).days + 1
    if days <= 0:
        return [], []
    n = max(1, round(per_month * days / 30))
    sales, refunds = [], []
    for i in range(n):
        d = start + timedelta(days=i * days // n)
        oid = int(d.strftime("%Y%m%d")) * 100 + i
        code = "WELCOME10" if i % DISCOUNT_EVERY == DISCOUNT_EVERY - 1 else None
        for j, (idx, variant, qty) in enumerate(templates[i % len(templates)]):
            title, _, price, _ = stats.DEMO_PRODUCTS[idx]
            price = round(price * price_factor, 2)
            discount = round(price * qty * 0.1, 2) if code else 0.0
            sales.append({
                "order_id": oid, "id": oid * 10 + j, "product_id": 9000 + idx, "title": title,
                "variant_title": variant, "sku": "", "quantity": qty, "price": float(price),
                "discount": discount, "discount_labels": json.dumps([[code, discount]]) if code else None,
                "local_date": d.isoformat(), "city": CITIES[i % len(CITIES)], "province": None, "vendor": "__DEMO__",
            })
    if templates is CURRENT_ORDERS and n >= 8:
        # одне повернення стікерпаку, щоб було видно, як воно враховується
        title = stats.DEMO_PRODUCTS[4][0]
        refunds.append({"quantity": 1, "amount": 150.0, "local_date": last.isoformat(), "vendor": "__DEMO__",
                        "product_id": 9004, "title": title, "variant_title": "", "sku": ""})
    return sales, refunds


def _period(start_dt, end_dt, comparison=False):
    if comparison:
        sales, refunds = _demo_rows(start_dt, end_dt, PREVIOUS_ORDERS, 13, price_factor=0.92)
    else:
        sales, refunds = _demo_rows(start_dt, end_dt, CURRENT_ORDERS, 16)
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
    comp = _period(comp_start, comp_end, comparison=True)
    daily = data.pop("daily")
    comparison_daily = comp.pop("daily")

    trend = {k: pct_change(data[k], comp[k]) for k in
             ("revenue", "net_revenue", "orders_count", "items_sold", "avg_order_value", "returns_amount")}
    highlight = compute_product_highlights(
        [{"title": p["title"], "revenue": p["net"]} for p in data["products"]],
        [{"title": p["title"], "revenue": p["net"]} for p in comp["products"]],
    )
    highlight.pop("top_decline", None)  # демо показує лише ріст
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
