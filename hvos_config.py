"""
HVOS Central Path Configuration
=================================
Single source of truth for all HVOS paths.
Usage: from hvos_config import HVOS_ROOT, KG_DB, ...
"""

import os
from pathlib import Path

# ── Root: always computed from this file's location ────────────
_HVOS_ROOT = Path(__file__).resolve().parent

# Public: can also be overridden via env var for testing/migration
HVOS_ROOT = os.environ.get("HVOS_ROOT") or str(_HVOS_ROOT)

# ── Database paths ─────────────────────────────────────────────
KG_DB         = os.path.join(HVOS_ROOT, "knowledge_graph", "kg.db")
EVOLUTION_DB  = os.path.join(HVOS_ROOT, "knowledge_graph", "evolution.db")
WM_DB         = os.path.join(HVOS_ROOT, "knowledge_graph", "world_model.db")
STRATEGY_DB   = os.path.join(HVOS_ROOT, "knowledge_graph", "strategy_memory.db")
CAPITAL_DB    = os.path.join(HVOS_ROOT, "knowledge_graph", "capital_book.db")
EVENTS_DB     = os.path.join(HVOS_ROOT, "reality", "events.db")
OPPORTUNITY_DIR = os.path.join(HVOS_ROOT, "opportunity")
KG_DIR        = os.path.join(HVOS_ROOT, "knowledge_graph")

# ── V10 submodule dirs ─────────────────────────────────────────
V10_SUBMODULES = {
    "world_model":     os.path.join(HVOS_ROOT, "core", "world_model"),
    "adaptive_learn":  os.path.join(HVOS_ROOT, "learning"),
    "causal_intel":    os.path.join(HVOS_ROOT, "reasoning"),
    "governance":      os.path.join(HVOS_ROOT, "governance"),
}

__all__ = [
    "HVOS_ROOT", "KG_DB", "EVOLUTION_DB", "WM_DB",
    "STRATEGY_DB", "CAPITAL_DB", "EVENTS_DB",
    "OPPORTUNITY_DIR", "KG_DIR", "V10_SUBMODULES",
]
