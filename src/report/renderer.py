"""HTML report renderer."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.schemas import FullReport


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    abs_v = abs(value)
    if abs_v >= 1_000_000_000:
        return f"{value / 1_000_000_000:,.1f}bn"
    if abs_v >= 1_000_000:
        return f"{value / 1_000_000:,.1f}m"
    return f"{value:,.2f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        if abs(value) < 1:
            return _fmt_pct(value)
        return _fmt_money(value)
    if value is None:
        return "n/a"
    return str(value)


def render_report(report: FullReport, output_dir: Path, chart_paths: list[str] | None = None) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["fmt"] = _fmt
    env.filters["money"] = _fmt_money
    env.filters["pct"] = _fmt_pct
    template = env.get_template("initiation_report.html")
    html = template.render(report=report, chart_paths=chart_paths or [])
    path = output_dir / f"{report.snapshot.ticker.lower()}_{report.plan.report_type}_report.html"
    path.write_text(html, encoding="utf-8")
    return str(path)
