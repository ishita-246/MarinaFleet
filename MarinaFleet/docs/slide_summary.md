<p align="center"><img src="../assets/logo.svg" alt="MarinaFleet" height="56"></p>

# MarinaFleet: slide-ready summary

**Clear the stadium. Protect every battery.** *Intelligence that moves a city.*

**Problem.** 60,000 fans, 90 minutes, 800 EV robotaxis. Past nights: pickup waits over 35 minutes, empty
cross-city driving, robotaxis running flat while venue chargers sat idle. LLMs that "do the battery maths
in their head" hallucinate numbers and strand vehicles.

**Solution.** A hybrid agentic orchestrator.
- **Agent (LLM):** reads the situation, spots the Gate 4 surge and the untrustworthy chargers, picks the
  strategy, calls tools, explains trade-offs, writes the operator report.
- **Code (Python):** all battery, ETA and allocation maths (SciPy Hungarian assignment), the 15% reserve
  guard, the telemetry freshness check, execution, and a full audit trail.
- **Human:** must approve any physical lane or signal change (enforced by a token-based state machine).

**Results (seeded event-night snapshot, clear weather; all from `run_scenario.py`):**

| Metric | Naive nearest-car | MarinaFleet |
|---|---|---|
| Stranded vehicles | 12 | **0** |
| Dispatches below 15% reserve | 74 | **0** |
| Failed trips to stale/offline chargers | 40 (107 km wasted) | **0** |
| Peak gate pickup-queue wait | 35.5 min | **19.1 min** (16.4 with approved lane) |
| Mean / P90 rider pickup wait | 12.7 / 17.4 min | 13.8 / 19.7 min |

Under the same 15% rule, the optimiser beats greedy dispatch: mean wait 14.3 → 13.8 min, P90 20.7 → 19.7 min,
pickup deadhead 2,174 → 2,073 km.

**Honest trade-off.** Battery safety costs about one minute of mean pickup time against the naive baseline,
because the naive baseline sends nearby low-battery cars that later strand.

**Also:** rider booking portal and operator sign-in (role-based, hashed passwords); bookings use the same 15% guard.

**Interface:** one brand from sign-in to the last tab. An operator command center with a KPI strip, an operations map with the
Gate 4 surge, a live trace that badges every step as AGENT, CODE or BLOCKED BY GUARD, and a gold operator-approval panel.
See `docs/BRAND_GUIDE.md`.

**Stretch goals delivered:** ROI comparator, multi-modal balancer (30 buses, metro announcements),
rider walking guidance (~200 m to Gates 3/5), weather adapter (rain/fog).

**Stack:** Python · SQLite · Streamlit · SciPy · Ollama qwen3 / Gemini Flash / Groq / offline Mock (swappable).
110 pytest tests, including deliberate "break the guard" checks and design-system checks (contrast, token use).
