"""
MarinaFleet central configuration.

Everything tunable lives here and can be overridden with environment variables
(see .env.example). Safety-critical constants that must NOT be changed at run
time (the 15 % battery reserve) are plain Python constants on purpose.
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # optional: load a local .env file if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # pragma: no cover - dotenv is optional
    pass

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- data paths
DATA_DB_PATH = Path(os.getenv("MARINA_DATA_DB", ROOT / "data" / "marina_stadium_egress.sqlite"))
RUNTIME_DIR = ROOT / "runtime"
OPS_DB_PATH = Path(os.getenv("MARINA_OPS_DB", RUNTIME_DIR / "marina_ops.sqlite"))
AUDIT_JSONL_PATH = Path(os.getenv("MARINA_AUDIT_JSONL", RUNTIME_DIR / "audit_log.jsonl"))

# ------------------------------------------------------- HARD SAFETY RULES
# Rule 2: no dispatch may leave a vehicle below this state of charge (percent),
# measured AFTER pickup leg + passenger trip + drive to nearest verified charger.
BATTERY_RESERVE_PCT: float = 15.0

# Rule 3: charger telemetry older than this (minutes) is treated as STALE.
STALE_TELEMETRY_MINUTES: float = float(os.getenv("MARINA_STALE_MINUTES", "5"))

# Vehicles below this SoC that are not given a ride are sent to charge.
CHARGE_THRESHOLD_PCT: float = 30.0

# A low vehicle is only sent to a charger it can reach with at least this SoC
# on arrival; otherwise a mobile charger is requested (vehicle not moved).
CHARGER_ARRIVAL_FLOOR_PCT: float = 5.0

# ------------------------------------------------------------------ LLM
LLM_BACKEND = os.getenv("MARINA_LLM_BACKEND", "mock").strip().lower()
LLM_FALLBACK_TO_MOCK = os.getenv("MARINA_LLM_FALLBACK_TO_MOCK", "true").lower() in ("1", "true", "yes")
LLM_TIMEOUT_S = float(os.getenv("MARINA_LLM_TIMEOUT_S", "60"))

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
# API keys are read lazily from the environment inside agent/llm_client.py
# (GEMINI_API_KEY, GROQ_API_KEY). They are never hard-coded.

AGENT_MAX_STEPS = int(os.getenv("MARINA_AGENT_MAX_STEPS", "16"))
