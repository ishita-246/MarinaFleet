"""
Swappable LLM backends: Ollama (local qwen3), Gemini Flash, Groq, and a
deterministic offline Mock.

All backends share ONE interface:
    client.complete(system: str, messages: list[{"role": "user"|"assistant", "content": str}]) -> str
and are asked to answer with a single JSON action (see prompts.py). Using
structured JSON actions instead of each vendor's native tool-calling API keeps
the agent loop identical for every backend.

Select a backend with MARINA_LLM_BACKEND=mock|ollama|gemini|groq (or the UI sidebar).
API keys are read from environment variables only (GEMINI_API_KEY, GROQ_API_KEY).
"""
from __future__ import annotations

import json
import os
import re

import requests

import config
from agent.prompts import OBSERVATION_PREFIX

BACKENDS = ("mock", "ollama", "gemini", "groq")


class LLMConfigError(RuntimeError):
    """Backend cannot be used (missing key, unknown backend)."""


class LLMCallError(RuntimeError):
    """Backend call failed (network, HTTP error, bad response)."""


# ------------------------------------------------------------------ parsing
def parse_action(text: str) -> dict:
    """
    Extract the JSON action from a model reply. Handles qwen3 <think> blocks,
    ```json fences and leading/trailing chatter. Raises ValueError if no valid action.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty model reply")
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    t = re.sub(r"```(?:json)?", "", t)
    start = t.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(t[start:i + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, dict) and "tool" in obj:
                        obj.setdefault("arguments", {})
                        obj.setdefault("rationale", "")
                        if not isinstance(obj["arguments"], dict):
                            raise ValueError("'arguments' must be an object")
                        return obj
                    break
        start = t.find("{", start + 1)
    raise ValueError("no JSON action with a 'tool' field found in model reply")


# ------------------------------------------------------------------ base
class LLMClient:
    name = "base"

    def __init__(self, model: str | None = None, timeout: float = config.LLM_TIMEOUT_S):
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, messages: list[dict]) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def _post(self, url: str, **kw) -> dict:
        try:
            r = requests.post(url, timeout=self.timeout, **kw)
        except requests.RequestException as exc:
            raise LLMCallError(f"{self.name}: connection failed: {exc}") from exc
        if r.status_code >= 400:
            raise LLMCallError(f"{self.name}: HTTP {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError as exc:
            raise LLMCallError(f"{self.name}: non-JSON response") from exc


class OllamaClient(LLMClient):
    """Local Ollama server, e.g. `ollama pull qwen3:8b` then `ollama serve`."""

    name = "ollama"

    def __init__(self, model=None, host=None, **kw):
        super().__init__(model or config.OLLAMA_MODEL, **kw)
        self.host = (host or config.OLLAMA_HOST).rstrip("/")

    def complete(self, system, messages):
        body = {"model": self.model, "stream": False, "format": "json", "think": False,
                "options": {"temperature": 0},
                "messages": [{"role": "system", "content": system}] + messages}
        data = self._post(f"{self.host}/api/chat", json=body)
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LLMCallError(f"ollama: unexpected response {str(data)[:200]}") from exc


class GeminiClient(LLMClient):
    """Google Gemini (free tier) via REST generateContent. Needs GEMINI_API_KEY."""

    name = "gemini"

    def __init__(self, model=None, **kw):
        super().__init__(model or config.GEMINI_MODEL, **kw)
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        if not self.api_key:
            raise LLMConfigError("GEMINI_API_KEY is not set")

    def complete(self, system, messages):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                         for m in messages],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        data = self._post(url, json=body, headers={"x-goog-api-key": self.api_key})
        try:
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMCallError(f"gemini: unexpected response {str(data)[:200]}") from exc


class GroqClient(LLMClient):
    """Groq (free tier) OpenAI-compatible chat completions. Needs GROQ_API_KEY."""

    name = "groq"

    def __init__(self, model=None, **kw):
        super().__init__(model or config.GROQ_MODEL, **kw)
        self.api_key = os.getenv("GROQ_API_KEY", "")
        if not self.api_key:
            raise LLMConfigError("GROQ_API_KEY is not set")

    def complete(self, system, messages):
        body = {"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}] + messages}
        data = self._post("https://api.groq.com/openai/v1/chat/completions", json=body,
                          headers={"Authorization": f"Bearer {self.api_key}"})
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMCallError(f"groq: unexpected response {str(data)[:200]}") from exc


# ------------------------------------------------------------------ mock
class MockLLMClient(LLMClient):
    """
    Deterministic offline stand-in for an LLM. Like a real model it only sees the
    text conversation (it has no access to Python objects): it reads the JSON
    observations, picks the next tool, and writes rationales/reports by quoting
    numbers from those observations (it never computes any).
    """

    name = "mock"
    AUTONOMOUS_SEQUENCE = ["RIDE_DISPATCH", "CHARGER_RESERVATION", "MOBILE_CHARGER_REQUEST", "REBALANCE",
                           "BUS_DEPLOYMENT", "METRO_ANNOUNCEMENT", "RIDER_GUIDANCE"]

    def __init__(self, model=None, **kw):
        super().__init__(model or "mock-deterministic-v1", **kw)

    @staticmethod
    def _observations(messages):
        obs = {}
        for m in messages:
            if m["role"] == "user" and m["content"].startswith("OBSERVATION from "):
                head, _, body = m["content"].partition("\n")
                tool = head[len("OBSERVATION from "):].rstrip(":")
                try:
                    obs.setdefault(tool, []).append(json.loads(body))
                except json.JSONDecodeError:
                    obs.setdefault(tool, []).append({"raw": body})
        return obs

    @staticmethod
    def _actions(messages):
        out = []
        for m in messages:
            if m["role"] == "assistant":
                try:
                    out.append(parse_action(m["content"]))
                except ValueError:
                    pass
        return out

    def complete(self, system, messages):
        obs, acts = self._observations(messages), self._actions(messages)
        task = messages[0]["content"] if messages else ""
        weather = next((w for w in ("rain", "fog", "clear") if f"weather: {w}" in task.lower()), "clear")

        def act(thought, tool, arguments, rationale):
            return json.dumps({"thought": thought, "tool": tool, "arguments": arguments, "rationale": rationale})

        if "get_egress_and_fleet_snapshot" not in obs:
            return act("Need fresh telemetry before any decision.", "get_egress_and_fleet_snapshot",
                       {"weather": weather}, "Start every cycle from a code-verified telemetry snapshot.")

        snap = obs["get_egress_and_fleet_snapshot"][-1]
        surge = [g for g in snap.get("gates", []) if g.get("status") == "SURGE"]
        bad_ch = [c for c in snap.get("chargers", []) if c.get("verdict") in ("STALE", "OFFLINE")]

        if "run_ev_dispatch_optimizer" not in obs:
            sg = ", ".join(f"{g['gate_id']} ({g['fans_queued']} fans, {g['surge_ratio']}x expected, "
                           f"est. wait {g['est_pickup_wait_min']} min)" for g in surge) or "none"
            bc = ", ".join(f"{c['charger_id']} is {c['verdict']}" for c in bad_ch) or "none"
            return act(f"Crowd surge detected at {sg}. Charger notices: {bc}.", "run_ev_dispatch_optimizer",
                       {"priority_gates": [g["gate_id"] for g in surge], "strategy": "surge_first_battery_safe"},
                       f"Surge at {sg}. Prioritise surge gates while keeping every dispatch above the 15% reserve; "
                       f"chargers flagged by code ({bc}) must not receive low-battery vehicles.")

        opt = obs["run_ev_dispatch_optimizer"][-1]
        done_orders = [a["arguments"].get("order_type") for a in acts if a.get("tool") == "dispatch_fleet_or_charger_order"]
        for ot in self.AUTONOMOUS_SEQUENCE:
            if ot not in done_orders:
                return act(f"Execute optimizer plan item {ot}.", "dispatch_fleet_or_charger_order",
                           {"order_type": ot, "justification": self._why(ot, opt)}, self._why(ot, opt))

        props = opt.get("lane_proposals", [])
        if props and "PICKUP_ZONE_LANE_REALLOCATION" not in done_orders:
            p = props[0]
            why = (f"{p['description']} Code estimate: pickup wait {p['wait_before_min']} -> {p['wait_after_min']} min. "
                   f"Physical change: requesting human operator approval.")
            return act("Lane change could cut the surge wait but is physical; must go to the operator.",
                       "dispatch_fleet_or_charger_order",
                       {"order_type": "PICKUP_ZONE_LANE_REALLOCATION", "gate_id": p["gate_id"], "justification": why},
                       why)

        return act("All plan items handled; write the operator report.", "finish",
                   {"report": self._report(snap, opt, obs, surge, bad_ch)},
                   "Summarise decisions and trade-offs for the duty operator.")

    @staticmethod
    def _why(ot, opt):
        k = opt.get("kpis", {}).get("optimized", {})
        c = opt.get("counts", {})
        return {
            "RIDE_DISPATCH": f"Dispatch {c.get('ride_assignments')} battery-safe assignments; "
                             f"{c.get('blocked_dispatches')} nearest-car dispatches were blocked by the 15% guard.",
            "CHARGER_RESERVATION": f"Reserve {c.get('charger_orders')} verified charger slots; code refused "
                                   f"{c.get('charger_refusals')} routings to stale/offline hubs "
                                   f"({c.get('charger_refusals_rerouted')} rerouted to verified hubs).",
            "MOBILE_CHARGER_REQUEST": f"{c.get('mobile_charger_requests')} vehicles cannot safely reach any verified "
                                      f"hub; keep them parked and request mobile chargers.",
            "REBALANCE": f"Pre-position {c.get('rebalance_orders')} healthy vehicles toward priority gates "
                         f"({k.get('rebalance_km')} km) to absorb the next surge wave.",
            "BUS_DEPLOYMENT": f"Shift overflow to {c.get('bus_orders')} feeder buses instead of waiting for robotaxis.",
            "METRO_ANNOUNCEMENT": f"Publish {c.get('metro_announcements')} metro announcements for remaining overflow.",
            "RIDER_GUIDANCE": "Nudge fans to walk about 200 m to neighbouring gates with shorter pickup queues.",
        }.get(ot, ot)

    @staticmethod
    def _report(snap, opt, obs, surge, bad_ch):
        k, b = opt.get("kpis", {}).get("optimized", {}), opt.get("kpis", {}).get("baseline", {})
        c = opt.get("counts", {})
        lines = ["OPERATOR SITUATION REPORT (agent narrative; all figures quoted from Python tool outputs)", ""]
        for g in surge:
            lines.append(f"* CROWD: Surge at {g['gate_id']}: {g['fans_queued']} fans queued, {g['surge_ratio']}x expected, "
                         f"est. pickup wait {g['est_pickup_wait_min']} min.")
        for ch in bad_ch:
            lines.append(f"* CHARGERS: {ch['charger_id']} excluded ({ch['verdict']}). Code reason: {ch['verdict_reason']}")
        lines.append(f"* FLEET: {c.get('ride_assignments')} rides dispatched, all above the 15% reserve; "
                     f"{c.get('blocked_dispatches')} unsafe nearest-car dispatches blocked; "
                     f"{c.get('charger_orders')} vehicles sent to verified chargers; "
                     f"{c.get('charger_refusals')} routings to stale/offline hubs refused "
                     f"({c.get('charger_refusals_rerouted')} rerouted to verified hubs; the rest are held, waitlisted "
                     f"or get a mobile charger: {c.get('mobile_charger_requests')} mobile-charger requests).")
        lines.append(f"* MULTI-MODAL: {c.get('bus_orders')} feeder buses deployed, {c.get('metro_announcements')} metro "
                     f"announcements, rider guidance active.")
        lines.append(f"* TRADE-OFF: battery-safe dispatch gives mean pickup {k.get('mean_wait_min')} min vs naive "
                     f"{b.get('mean_wait_min')} min, but naive dispatch would strand {b.get('stranded_vehicles')} vehicles, "
                     f"leave {b.get('reserve_violations')} below reserve and make {b.get('failed_charger_attempts')} "
                     f"failed charger trips. Peak gate queue: {b.get('gate4_style_peak_queue_wait_min')} -> "
                     f"{k.get('gate4_style_peak_queue_wait_min')} min with rider guidance.")
        lanes = [o for o in obs.get("dispatch_fleet_or_charger_order", []) if o.get("status") == "PENDING_APPROVAL"]
        for o in lanes:
            lines.append(f"* ACTION REQUIRED: lane reallocation request {o.get('approval_request_id')} is PENDING_APPROVAL. "
                         f"If approved, code estimates peak queue {k.get('peak_queue_wait_if_lane_approved_min')} min. "
                         f"Nothing physical has changed yet.")
        return "\n".join(lines)


# ------------------------------------------------------------------ factory
def get_llm_client(backend: str | None = None, model: str | None = None) -> LLMClient:
    backend = (backend or config.LLM_BACKEND).lower()
    if backend == "mock":
        return MockLLMClient(model)
    if backend == "ollama":
        return OllamaClient(model)
    if backend == "gemini":
        return GeminiClient(model)
    if backend == "groq":
        return GroqClient(model)
    raise LLMConfigError(f"Unknown backend '{backend}'. Choose one of {BACKENDS}")


def observation_message(tool: str, payload: dict) -> dict:
    return {"role": "user", "content": OBSERVATION_PREFIX.format(tool=tool) + json.dumps(payload, default=str)}
