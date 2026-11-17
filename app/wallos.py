import httpx

# Wallos cycle codes: 0 = daily, 1 = weekly, 2 = monthly, 3 = yearly
_CYCLE_TO_MONTHLY = {
    0: 30.4375,
    1: 52.0 / 12.0,
    2: 1.0,
    3: 1.0 / 12.0,
}


def monthly_cost(price: float, cycle: int, frequency: int) -> float:
    per_cycle = _CYCLE_TO_MONTHLY.get(int(cycle), 1.0)
    freq = int(frequency) if frequency else 1
    return round(price * per_cycle / max(freq, 1), 2)


async def fetch_subscriptions(wallos_url: str, api_key: str) -> dict:
    base = wallos_url.rstrip("/")
    url = f"{base}/api/subscriptions/get_subscriptions.php"
    params = {"api_key": api_key, "convert_currency": "true"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def build_summary(payload: dict) -> dict:
    subs = payload.get("subscriptions", [])
    active = [s for s in subs if not s.get("inactive")]
    items = []
    total = 0.0
    for s in active:
        cost = monthly_cost(float(s.get("price", 0)), s.get("cycle", 2), s.get("frequency", 1))
        total += cost
        items.append(
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "price": round(float(s.get("price", 0)), 2),
                "monthly_cost": cost,
                "next_payment": s.get("next_payment", ""),
                "cycle": s.get("cycle"),
                "frequency": s.get("frequency"),
                "category": s.get("category_name", ""),
                "payment_method": s.get("payment_method_name", ""),
            }
        )
    items.sort(key=lambda x: x["monthly_cost"], reverse=True)
    return {
        "success": True,
        "currency_note": "Montants dans la devise principale Wallos",
        "monthly_total": round(total, 2),
        "active_count": len(active),
        "inactive_count": len(subs) - len(active),
        "subscriptions": items,
    }
