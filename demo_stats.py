"""
Копія stats.py з репозиторію nevamind-max/dashboard (лише розрахунки й демо-дані).
Оновлюйте разом з оригіналом.

Розрахунок статистики вендора з позицій замовлень і повернень (див. store.py).

Правила:
* Продаж рахується за датою замовлення, повернення — за датою повернення.
  Тому повернення товару, проданого минулого місяця, зменшує виручку цього.
* Виручка = продажі зі знижками − повернення.
* До виплати = Σ виручки по кожному товару × (1 − комісія), де комісія —
  окрема ставка товару, а якщо її немає — ставка вендора.
"""

import json
import math
import random
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

TOP_CITIES = 10


def shift_months(dt, months_back):
    """Зсуває дату на N місяців назад, коректно обробляючи різну довжину місяців
    (наприклад, 31 березня - 1 місяць = останній день лютого)."""
    month = dt.month - months_back
    year = dt.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def resolve_period(period, start_param, end_param):
    """
    Визначає (start_dt, end_dt) на основі параметрів запиту, а також
    (comp_start, comp_end) — період для порівняння динаміки:
      - this_month / last_month: той самий діапазон, зсунутий на 1 місяць назад
        (тобто "з 1 по 17 число минулого місяця", якщо зараз 17-те цього)
      - last_7_days / last_30_days / custom: період такої самої довжини
        одразу перед обраним
    period: "this_month" | "last_month" | "last_7_days" | "last_30_days" | "custom"
    """
    now = datetime.now(timezone.utc)

    if period == "last_month":
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = first_of_this_month - timedelta(seconds=1)
        start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "last_7_days":
        end = now
        start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "last_30_days":
        end = now
        start = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "custom" and start_param and end_param:
        start = datetime.fromisoformat(start_param).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
        )
        end = datetime.fromisoformat(end_param).replace(
            hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc
        )
    else:
        # За замовчуванням — поточний місяць, "станом на зараз"
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now

    if period in ("this_month", "last_month") or not period:
        comp_start = shift_months(start, 1)
        comp_end = shift_months(end, 1)
    else:
        # last_7_days / last_30_days / custom — порівнюємо з періодом
        # такої самої довжини одразу перед обраним
        length = end - start
        comp_end = start - timedelta(microseconds=1)
        comp_start = comp_end - length

    return start, end, comp_start, comp_end


def _line_net(r):
    return r["price"] * r["quantity"] - r["discount"]


def _product_key(product_id, title):
    return str(product_id) if product_id else f"t:{title}"


def compute(sales, refunds, start_dt, end_dt, vendor_rate=None, product_rates=None):
    product_rates = product_rates or {}

    def rate_for(pid):
        return product_rates.get(pid, vendor_rate)

    days = {}
    d = start_dt.date()
    while d <= end_dt.date():
        days[d.isoformat()] = 0.0
        d += timedelta(days=1)

    gross = 0.0
    items_sold = 0
    orders = set()
    payout = 0.0
    no_rate = set()
    products = {}
    cities = defaultdict(lambda: {"orders": set(), "revenue": 0.0})
    disc = {"items": 0, "amount": 0.0, "orders": set(), "labels": defaultdict(lambda: {"orders": set(), "amount": 0.0})}

    def product(pid, title):
        key = _product_key(pid, title)
        p = products.get(key)
        if p is None:
            p = products[key] = {"title": title, "quantity": 0, "revenue": 0.0, "returned_qty": 0,
                                 "returned_amount": 0.0, "variants": {}}
        return p

    def variant(p, vtitle):
        v = p["variants"].get(vtitle)
        if v is None:
            v = p["variants"][vtitle] = {"title": vtitle, "quantity": 0, "revenue": 0.0, "returned_qty": 0,
                                         "returned_amount": 0.0}
        return v

    for r in sales:
        net = _line_net(r)
        qty = r["quantity"]
        gross += net
        items_sold += qty
        orders.add(r["order_id"])
        if r["local_date"] in days:
            days[r["local_date"]] += net

        p = product(r["product_id"], r["title"])
        p["quantity"] += qty
        p["revenue"] += net
        v = variant(p, r["variant_title"] or "")
        v["quantity"] += qty
        v["revenue"] += net

        rate = rate_for(r["product_id"])
        if rate is None:
            no_rate.add(_product_key(r["product_id"], r["title"]))
        else:
            payout += net * (1 - rate)

        if r["city"]:
            c = cities[r["city"]]
            c["orders"].add(r["order_id"])
            c["revenue"] += net

        if r["discount"] > 0:
            disc["items"] += qty
            disc["amount"] += r["discount"]
            disc["orders"].add(r["order_id"])
            labels = json.loads(r["discount_labels"]) if r["discount_labels"] else [["Знижка", r["discount"]]]
            for label, amount in labels:
                disc["labels"][label]["orders"].add(r["order_id"])
                disc["labels"][label]["amount"] += amount

    returns_amount = 0.0
    returns_qty = 0
    for r in refunds:
        returns_amount += r["amount"]
        returns_qty += r["quantity"]
        p = product(r["product_id"], r["title"])
        p["returned_qty"] += r["quantity"]
        p["returned_amount"] += r["amount"]
        v = variant(p, r["variant_title"] or "")
        v["returned_qty"] += r["quantity"]
        v["returned_amount"] += r["amount"]
        rate = rate_for(r["product_id"])
        if rate is None:
            no_rate.add(_product_key(r["product_id"], r["title"]))
        else:
            payout -= r["amount"] * (1 - rate)

    revenue = gross - returns_amount
    orders_count = len(orders)

    product_list = []
    for p in products.values():
        variants = sorted(p["variants"].values(), key=lambda v: (-v["quantity"], v["title"]))
        if len(variants) == 1 and not variants[0]["title"]:
            variants = []  # товар без розмірів/кольорів — підпунктів не показуємо
        product_list.append({
            "title": p["title"],
            "quantity": p["quantity"],
            "revenue": round(p["revenue"], 2),
            "returned_qty": p["returned_qty"],
            "returned_amount": round(p["returned_amount"], 2),
            "net": round(p["revenue"] - p["returned_amount"], 2),
            "variants": [
                {"title": v["title"] or "Без варіанту", "quantity": v["quantity"],
                 "revenue": round(v["revenue"], 2), "returned_qty": v["returned_qty"],
                 "net": round(v["revenue"] - v["returned_amount"], 2)}
                for v in variants
            ],
        })
    product_list.sort(key=lambda p: (-p["net"], p["title"]))

    city_list = sorted(
        ({"city": k, "orders": len(v["orders"]), "revenue": round(v["revenue"], 2)} for k, v in cities.items()),
        key=lambda c: (-c["orders"], -c["revenue"]),
    )
    orders_with_city = len(set().union(*(v["orders"] for v in cities.values()))) if cities else 0

    has_any_rate = vendor_rate is not None or any(rate_for(_pid(k)) is not None for k in products)
    return {
        "gross": round(gross, 2),
        "returns_amount": round(returns_amount, 2),
        "returns_qty": returns_qty,
        "revenue": round(revenue, 2),
        "orders_count": orders_count,
        "items_sold": items_sold,
        "avg_order_value": round(gross / orders_count, 2) if orders_count else 0,
        "net_revenue": round(payout, 2) if has_any_rate else None,
        "products_without_rate": len(no_rate) if has_any_rate else 0,
        "products": product_list,
        "daily": [{"date": k, "revenue": round(v, 2)} for k, v in sorted(days.items())],
        "cities": city_list[:TOP_CITIES],
        "cities_other_orders": max(0, orders_with_city - sum(c["orders"] for c in city_list[:TOP_CITIES])),
        "orders_without_city": orders_count - orders_with_city,
        "discounts": {
            "items": disc["items"],
            "orders": len(disc["orders"]),
            "amount": round(disc["amount"], 2),
            "labels": sorted(
                ({"label": k, "orders": len(v["orders"]), "amount": round(v["amount"], 2)} for k, v in disc["labels"].items()),
                key=lambda x: -x["amount"],
            ),
        },
    }


def _pid(key):
    return None if key.startswith("t:") else int(key)


def vendor_totals(sales, refunds, vendor_rates, product_rates):
    """Зведення по всіх вендорах: {vendor: {gross, returns, revenue, payout, orders, no_rate}}."""
    out = defaultdict(lambda: {"gross": 0.0, "returns": 0.0, "orders": set(), "payout": 0.0, "no_rate": 0, "items": 0})
    for r in sales:
        t = out[r["vendor"]]
        net = _line_net(r)
        t["gross"] += net
        t["items"] += r["quantity"]
        t["orders"].add(r["order_id"])
        rate = product_rates.get(r["product_id"], vendor_rates.get(r["vendor"]))
        if rate is None:
            t["no_rate"] += 1
        else:
            t["payout"] += net * (1 - rate)
    for r in refunds:
        t = out[r["vendor"]]
        t["returns"] += r["amount"]
        rate = product_rates.get(r["product_id"], vendor_rates.get(r["vendor"]))
        if rate is None:
            t["no_rate"] += 1
        else:
            t["payout"] -= r["amount"] * (1 - rate)
    result = {}
    for vendor, t in out.items():
        result[vendor] = {
            "gross": round(t["gross"], 2),
            "returns": round(t["returns"], 2),
            "revenue": round(t["gross"] - t["returns"], 2),
            "payout": round(t["payout"], 2),
            "orders": len(t["orders"]),
            "items": t["items"],
            "no_rate": t["no_rate"],
        }
    return result


# ---------------------------------------------------------------- демо-дані
DEMO_PRODUCTS = [
    # назва, вага в продажах, ціна, варіанти
    ("Худі «Кураж» Ваш гурт", 0.28, 1900, ["S / Чорний", "M / Чорний", "L / Чорний", "M / Сірий", "L / Сірий"]),
    ("Футболка «Сигнал» Ваш гурт", 0.22, 650, ["S / Білий", "M / Білий", "L / Білий", "XL / Білий"]),
    ("Кепка Ваш гурт", 0.15, 450, [""]),
    ("Постер «Ехо» Ваш гурт", 0.12, 300, ["A3", "A2"]),
    ("Стікерпак Ваш гурт", 0.13, 150, [""]),
    ("Значок Ваш гурт", 0.06, 150, [""]),
    ("Шкарпетки Ваш гурт", 0.04, 180, ["36-40", "41-45"]),
]
DEMO_CITIES = [("Київ", 40), ("Львів", 16), ("Харків", 9), ("Одеса", 8), ("Дніпро", 7), ("Вінниця", 4),
               ("Івано-Франківськ", 4), ("Запоріжжя", 3), ("Ужгород", 2), ("Чернівці", 2), ("Полтава", 2)]
DEMO_ANCHOR = date(2026, 1, 1)


def _demo_day(d):
    """Детерміновані замовлення одного дня (той самий день — ті самі дані)."""
    rng = random.Random(f"demo-{d.isoformat()}")
    months = (d.year - DEMO_ANCHOR.year) * 12 + (d.month - DEMO_ANCHOR.month)
    t = (d - DEMO_ANCHOR).days
    wave = 1 + 0.35 * math.sin(t / 3.3) + 0.15 * math.sin(t / 7 + 1)
    n_orders = max(0, round(1.1 * (1.03 ** months) * wave * rng.uniform(0.6, 1.4) * (1.15 if d.weekday() >= 5 else 1)))
    weights = [p[1] for p in DEMO_PRODUCTS]
    city_names = [c[0] for c in DEMO_CITIES]
    city_w = [c[1] for c in DEMO_CITIES]
    sales, refunds = [], []
    for i in range(n_orders):
        oid = int(d.strftime("%Y%m%d")) * 100 + i
        city = rng.choices(city_names, city_w)[0]
        code = "WELCOME10" if rng.random() < 0.12 else None
        for j in range(rng.choice([1, 1, 1, 2, 2, 3])):
            idx = rng.choices(range(len(DEMO_PRODUCTS)), weights)[0]
            title, _, price, variants = DEMO_PRODUCTS[idx]
            qty = 1 if rng.random() < 0.85 else 2
            discount = round(price * qty * 0.1, 2) if code else 0.0
            line = {
                "order_id": oid, "id": oid * 10 + j, "product_id": 9000 + idx, "title": title,
                "variant_title": rng.choice(variants), "sku": "", "quantity": qty, "price": float(price),
                "discount": discount, "discount_labels": json.dumps([[code, discount]]) if code else None,
                "local_date": d.isoformat(), "city": city, "province": None, "vendor": "__DEMO__",
            }
            sales.append(line)
            if rng.random() < 0.07:
                rd = d + timedelta(days=rng.randint(3, 12))
                refunds.append({
                    "quantity": 1, "amount": round((price * qty - discount) / qty, 2), "local_date": rd.isoformat(),
                    "vendor": "__DEMO__", "product_id": line["product_id"], "title": title,
                    "variant_title": line["variant_title"], "sku": "",
                })
    return sales, refunds


def demo_rows(start_dt, end_dt):
    start, end = start_dt.date(), end_dt.date()
    today = datetime.now(timezone.utc).date()
    sales, refunds = [], []
    d = start - timedelta(days=12)
    while d <= min(end, today):
        s, r = _demo_day(d)
        if d >= start:
            sales.extend(s)
        refunds.extend(x for x in r if start.isoformat() <= x["local_date"] <= min(end, today).isoformat())
        d += timedelta(days=1)
    return sales, refunds
