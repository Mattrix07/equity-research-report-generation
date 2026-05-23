"""Report Manager Agent.

Creates the report plan: report type, ticker, sector, template, sections,
valuation methods and required charts.
"""
from src.agents.report_agents import build_report_plan

__all__ = ["build_report_plan"]
