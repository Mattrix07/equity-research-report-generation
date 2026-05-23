"""Simple trading comparables engine."""
from __future__ import annotations

from statistics import median
from typing import Any


def run_comps(peer_snapshots: list[dict[str, Any]], company_ebitda: float | None, net_debt: float, shares: float | None) -> dict[str, Any]:
    ev_ebitda: list[float] = []
    ev_revenue: list[float] = []
    table: list[dict[str, Any]] = []

    for peer in peer_snapshots:
        ev = peer.get("enterprise_value")
        ebitda = peer.get("ebitda")
        revenue = peer.get("revenue_ttm")
        row = {
            "ticker": peer.get("ticker"),
            "company_name": peer.get("company_name"),
            "market_cap": peer.get("market_cap"),
            "enterprise_value": ev,
            "ev_ebitda": ev / ebitda if ev and ebitda else None,
            "ev_revenue": ev / revenue if ev and revenue else None,
            "forward_pe": peer.get("forward_pe"),
        }
        if row["ev_ebitda"]:
            ev_ebitda.append(row["ev_ebitda"])
        if row["ev_revenue"]:
            ev_revenue.append(row["ev_revenue"])
        table.append(row)

    median_ev_ebitda = median(ev_ebitda) if ev_ebitda else None
    implied_price = None
    implied_equity_value = None
    if median_ev_ebitda and company_ebitda and shares:
        implied_ev = company_ebitda * median_ev_ebitda
        implied_equity_value = implied_ev - net_debt
        implied_price = implied_equity_value / shares

    return {
        "peer_table": table,
        "median_ev_ebitda": median_ev_ebitda,
        "median_ev_revenue": median(ev_revenue) if ev_revenue else None,
        "implied_equity_value": implied_equity_value,
        "implied_price": implied_price,
    }
