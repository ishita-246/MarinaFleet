# MarinaFleet: 5-minute demo script

*Clear the stadium. Protect every battery.*

**Setup (before you present):** `streamlit run app.py`, sidebar backend = **Mock**, weather = **Clear**,
stale threshold = **5 min**. Have `docs/roi_chart.png` open as a backup.

| Time | Do | Say |
|---|---|---|
| 0:00–0:30 | Show the sign-in page, then sign in as `admin`. | "Sixty thousand fans are leaving Marina City Stadium. On past nights pickup waits went past 35 minutes, cars drove empty across the city and chargers sat idle while robotaxis ran flat. MarinaFleet is an agent that orchestrates the fleet, but it is **not allowed to do maths** and **not allowed to touch physical lanes**. Clear the stadium. Protect every battery." |
| 0:30–1:10 | Before running anything, point at the **operations map** and the **KPI strip**. | "This is live telemetry before the agent acts. Gate 4 is pulsing red: 9,800 fans, 2.8 times expected, after a concourse closure, and a 35.5 minute pickup queue. Two charger hubs are marked untrusted. The surge flag and the queue model are Python; the agent only reads them." |
| 1:10–1:30 | Click **Run event-night scenario**. | "One click runs the whole loop: snapshot, optimiser, guards, dispatch, approval request, audit log, report." |
| 1:30–2:10 | Watch the **Agent vs Code trace** on the right. | "Every row is badged. **AGENT** in teal is the LLM choosing tools, the priority gate G4 and the strategy. **CODE** in gold is Python running the snapshot, the Hungarian optimiser and every order. **BLOCKED BY GUARD** in red is code refusing something. Here the agent wrote its rationale: prioritise G4 while keeping the 15% reserve." |
| 2:10–2:40 | **Dispatch Decisions** tab. | "380 battery-safe assignments. The lowest projected charge in any trip, *after* the pickup leg, the ride and the drive to a verified charger, is still above 15%. Below are the dispatches the guard **blocked**: for example RT-0089, a car at 23.4% that would reach 8.7% on a 30.7 km trip. The red line on each battery bar is the 15% floor." |
| 2:40–3:10 | **Charger Network** tab. | "Two hubs are refused, and the reason text comes from code: JBR reports 16 free slots, but its telemetry is 23 minutes old against a 5 minute limit, so it is stale. Media City is offline. *Routing blocked by code, not by the LLM.* 75 low-battery cars had one of these as their nearest hub; 58 were rerouted to verified hubs and the rest stay parked or get a mobile charger." |
| 3:10–4:00 | Scroll to the gold **Operator approval** panel under the map. First click **Try to execute without approval** (red refusal). Then click **Approve change** (or **Reject change**). | "The agent wants an extra pickup lane at Gate 4. That is a physical change, so code refuses it without a token, even if we try. As the operator I approve: code issues a one-time token and executes it. *(If rejected: lanes stay as they are and the walking guidance and buses remain the plan.)* The decision appears in the trace and in the **Approval Queue** tab." |
| 4:00–4:40 | **ROI vs Baseline** tab. | "Compared with naive nearest-car dispatch: zero stranded vehicles instead of 12, zero dispatches below reserve instead of 74, zero failed charger trips instead of 40, and the peak gate queue drops from 35.5 to 19.1 minutes, or 16.4 with the lane. Honest trade-off: the naive baseline looks about one minute faster on pickup because it sends cars that then die. Under the same safety rules, our optimiser beats greedy dispatch on wait and empty kilometres." |
| 4:40–5:00 | **Audit Log** tab. Optional: set weather to **Fog** in the sidebar and run again. | "Everything is in an auditable log: actor, tool, inputs, outputs, guard results, rationale, autonomous or human-approved. Weather recalculates every ETA and battery margin. Thank you." |

**Bonus (if time allows, 30 s):** sign out and sign in as `rider@demo.ae`. Book Gate 4 → Dubai Marina. The quote shows "Battery check passed" and suggests walking 200 m to Gate 5. The saving depends on when you ask: right after the admin run, 380 robotaxis are already dispatched and excluded from rider quotes, so the nearest free car is about 34 min away and the Gate 5 tip saves about 7 min (pickup 36 → 28 min). On a fresh database, before any run, the nearest car is 6 min away and the same tip saves about 26 min (36 → 9 min). Confirm, then sign back in as admin and show the booking in the **Bookings** tab.

**Backup if the UI fails:** `python run_scenario.py --decision approve` prints the same trace, refusals,
approval flow, report and KPI table in the terminal.
