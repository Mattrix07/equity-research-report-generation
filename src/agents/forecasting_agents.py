"""Forecasting agent layer.

This module exposes the forecast assumption builder and calculation workflow.
The design deliberately separates judgement from calculation:
- assumptions are selected from historical patterns and scenario logic
- forecasts are calculated by deterministic Python formulas
"""
from src.engines.forecast_engine import build_default_assumptions, run_forecast

__all__ = ["build_default_assumptions", "run_forecast"]
