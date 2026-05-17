"""Resumable pipeline — minimal, ADK-native, durable across days/weeks.

Architecture:

  ResumableOrchestrator (BaseAgent)
    └── runs sub-agents sequentially
        └── skips any sub-agent whose `output_key` is already in session state
        └── pauses cleanly if a sub-agent ran but didn't set its output_key
        └── stops if a sub-agent escalates (used by AgentGate for denial)

  AgentGate (BaseAgent)
    └── reads state[decision_key]
        - missing       → no output_key written → orchestrator pauses
        - in allow-list → writes output_key="approved" → orchestrator continues
        - not in list   → escalate=True            → orchestrator stops

Durability:
  DatabaseSessionService stores session.state in SQLite (or Postgres for prod).
  output_keys, gate decisions, and the agent gate's output all survive
  process restarts and arbitrary delays. A 40-day pause is just a 40-day
  gap between two calls to runner.run_async with the same session_id.

Usage:
  python main.py "Process case CASE-001 for Acme Corp, US, txns 12500 4200"
  python main.py --resume <session_id> approved
  python main.py --resume <session_id> denied
  python main.py --status <session_id>
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator, Optional
from typing_extensions import override

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.apps import App, ResumabilityConfig
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

# --------------------------------------------------------------------- #
# Constants — the SQLite file is what survives a 40-day pause
# --------------------------------------------------------------------- #
DB_PATH  = Path.home() / ".resumable_demo.db"
DB_URL   = f"sqlite:///{DB_PATH}"
APP_NAME = "resumable_demo"
USER_ID  = "console_user"
MODEL    = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

# Single state key the gate reads. The CLI/UI writes this when resuming.
DECISION_KEY = "approval_decision"


# ===================================================================== #
# 1.  AgentGate — the pause point
# ===================================================================== #
class AgentGate(BaseAgent):
    """Deterministic pause gate.

      - state[decision_key] missing → don't set output_key → ORCHESTRATOR PAUSES
      - decision in approved_values → output_key='approved' → continues
      - decision not in approved     → escalate=True       → ORCHESTRATOR STOPS

    Because the gate's output_key remains unset while paused, the
    orchestrator's normal skip-if-output-set check naturally re-enters
    this agent on every resume until a decision lands.
    """

    decision_key: str = DECISION_KEY
    approved_values: list[str] = ["approved", "yes", "ok", "accept"]
    # `output_key` is a standard ADK attribute on sub-agents; the
    # orchestrator below reads it via getattr.
    output_key: str = "gate_result"

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        decision = ctx.session.state.get(self.decision_key)

        # ----- PENDING (no decision yet) ----- #
        if not decision or not str(decision).strip():
            print(f"  [gate]  status=PENDING — no '{self.decision_key}' in state")
            # Emit an informational event but DO NOT write output_key.
            # Absence of output_key is the pause signal.
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                content=types.Content(role="model", parts=[types.Part(
                    text="GATE: pending — awaiting decision"
                )]),
            )
            return

        # ----- DECISION PRESENT ----- #
        normalized = str(decision).strip().lower()
        approved = any(
            normalized == v.lower() or normalized.startswith(v.lower() + " ")
            for v in self.approved_values
        )

        if approved:
            print(f"  [gate]  decision={decision!r} → APPROVED")
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                content=types.Content(role="model", parts=[types.Part(
                    text=f"GATE: approved (decision={decision!r})"
                )]),
                actions=EventActions(state_delta={self.output_key: "approved"}),
            )
        else:
            print(f"  [gate]  decision={decision!r} → DENIED, halting pipeline")
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                content=types.Content(role="model", parts=[types.Part(
                    text=f"GATE: denied (decision={decision!r})"
                )]),
                actions=EventActions(
                    state_delta={self.output_key: "denied"},
                    escalate=True,         # ← ADK-standard halt signal
                ),
            )


# ===================================================================== #
# 2.  ResumableOrchestrator — the custom BaseAgent
# ===================================================================== #
class ResumableOrchestrator(BaseAgent):
    """Custom sequential orchestrator with three outcomes per sub-agent:

      SKIP:   state[sub.output_key] is already set  → already done last run
      PAUSE:  sub ran but didn't set output_key      → pipeline halts; same
                                                       sub will re-enter on
                                                       next runner.run_async
      STOP:   any yielded event has escalate=True    → pipeline aborts

    All sub-agents must declare `output_key` (LlmAgent has it built-in;
    AgentGate above does too). The orchestrator never invents state keys.
    """

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        print(f"  [orch]  session={ctx.session.id}  "
              f"invocation={ctx.invocation_id}")

        for sub in self.sub_agents:
            out_key = getattr(sub, "output_key", None)
            if out_key is None:
                raise RuntimeError(
                    f"sub-agent {sub.name!r} must declare output_key"
                )

            # ---------- SKIP: already done in a prior run ---------- #
            if ctx.session.state.get(out_key) is not None and \
               not self._is_pause_marker(sub, ctx.session.state.get(out_key)):
                print(f"  [skip]  {sub.name:<14}  (state['{out_key}'] set)")
                continue

            # ---------- RUN this sub-agent ---------- #
            print(f"  [run]   {sub.name}")
            stop = False
            async for event in sub.run_async(ctx):
                yield event
                if event.actions and event.actions.escalate:
                    stop = True

            # ---------- STOP: any escalate signal ---------- #
            if stop:
                print(f"  [stop]  {sub.name:<14}  ✗  escalate=True received\n")
                return

            # ---------- PAUSE: output_key not set ---------- #
            if ctx.session.state.get(out_key) is None:
                print(f"  [pause] {sub.name:<14}  ⏸  output_key not set\n")
                return

            print(f"  [done]  {sub.name:<14}  ✓  ({out_key}={ctx.session.state[out_key]!r:.40})")

        print(f"  [orch]  ✓ all sub-agents complete\n")

    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_pause_marker(sub: BaseAgent, value) -> bool:
        """A defensive hook in case a sub-agent uses sentinel pause values.
        Default: any non-None value means done. Override if needed.
        """
        return False


# ===================================================================== #
# 3.  Build the pipeline — domain agents are vanilla LlmAgents
# ===================================================================== #
def build_pipeline() -> ResumableOrchestrator:
    ingest = LlmAgent(
        name="ingest", model=MODEL, output_key="case_raw",
        instruction=(
            "Extract case_id, customer name, country, transactions from the "
            "user's message. Reply ONLY with JSON like "
            '{"case_id":"...","customer":{"name":"...","country":"..."},'
            '"transactions":[{"amount":<num>,"currency":"..."}]}'
        ),
    )
    normalize = LlmAgent(
        name="normalize", model=MODEL, output_key="case_canonical",
        instruction=(
            "Read state.case_raw. Trim names, uppercase country, "
            "ensure numeric amounts. Reply with the same JSON shape. JSON only."
        ),
    )
    scoring = LlmAgent(
        name="scoring", model=MODEL, output_key="risk",
        instruction=(
            "Read state.case_canonical. Score: +0.5 if total txns >= 10000, "
            "+0.2 if >= 50000, +0.3 if country in (IR, KP, SY, CU). Cap 1.0. "
            'Reply {"score":<num>,"band":"low|medium|high"} '
            "(high>=0.7, medium>=0.4). JSON only."
        ),
    )
    summary = LlmAgent(
        name="summary", model=MODEL, output_key="review_summary",
        instruction=(
            "Read state.case_canonical and state.risk. Write a 1-2 sentence "
            "reviewer summary. Plain text only."
        ),
    )
    gate = AgentGate(
        name="approval_gate",
        approved_values=["approved", "yes", "ok"],
    )
    finalize = LlmAgent(
        name="finalize", model=MODEL, output_key="final_verdict",
        instruction=(
            "Read state.gate_result and state.risk.band. "
            "Reply 'FINAL VERDICT: CLEAR' if band='low' else 'FINAL VERDICT: ENHANCED_DD'. "
            "Include state.review_summary on the next line. Plain text only."
        ),
    )

    return ResumableOrchestrator(
        name="resumable_pipeline",
        description="Sequential pipeline with a pausable AgentGate.",
        sub_agents=[ingest, normalize, scoring, summary, gate, finalize],
    )


# ===================================================================== #
# 4.  Build App + Runner (proper ADK pattern, durable session service)
# ===================================================================== #
def build_app_and_runner() -> tuple[App, Runner]:
    pipeline = build_pipeline()

    app = App(
        name=APP_NAME,
        root_agent=pipeline,
        resumability_config=ResumabilityConfig(is_resumable=True),
    )

    # DatabaseSessionService is the key piece — session.state, including
    # every sub-agent's output_key, is persisted to SQLite (or Postgres)
    # and survives arbitrary delays between calls.
    session_service = DatabaseSessionService(db_url=DB_URL)

    runner = Runner(app=app, session_service=session_service)
    return app, runner


# ===================================================================== #
# 5.  CLI: start / resume / status
# ===================================================================== #
async def cmd_start(message: str) -> int:
    _, runner = build_app_and_runner()
    session_id = f"sess-{uuid.uuid4().hex[:8]}"

    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id, state={},
    )
    print(f"\n▶  session_id = {session_id}\n")

    final_text = await _stream(
        runner, session_id=session_id,
        message=types.Content(role="user", parts=[types.Part(text=message)]),
    )

    status = await _status(runner.session_service, session_id)
    _print_status_footer(status, session_id, final_text)
    return 0


async def cmd_resume(session_id: str, decision: str) -> int:
    _, runner = build_app_and_runner()

    # Confirm the session exists in the durable store (40 days later, it
    # still does — DatabaseSessionService loads it straight from SQLite).
    session = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id,
    )
    if session is None:
        print(f"❌  no session {session_id}")
        return 1

    print(f"\n▶  resuming {session_id}")
    print(f"   completed previously: "
          f"{[k for k in session.state if k in {'case_raw','case_canonical','risk','review_summary','gate_result','final_verdict'}]}")
    print(f"   decision being injected: {decision!r}\n")

    # Inject the decision into durable session state via append_event.
    # This is the canonical way to mutate session state from outside an
    # agent run — and it persists immediately to the DatabaseSessionService.
    await runner.session_service.append_event(
        session,
        Event(
            author="human",
            invocation_id=str(uuid.uuid4()),
            actions=EventActions(state_delta={DECISION_KEY: decision}),
        ),
    )

    final_text = await _stream(
        runner, session_id=session_id,
        message=types.Content(role="user",
                              parts=[types.Part(text=f"resume: {decision}")]),
    )

    status = await _status(runner.session_service, session_id)
    _print_status_footer(status, session_id, final_text)
    return 0


async def cmd_status(session_id: str) -> int:
    _, runner = build_app_and_runner()
    session = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id,
    )
    if session is None:
        print(f"❌  no session {session_id}")
        return 1

    print(f"\nsession_id   : {session_id}")
    print(f"output_keys in state (this is your durable progress record):")
    for k in ["case_raw", "case_canonical", "risk", "review_summary",
              "gate_result", "final_verdict"]:
        v = session.state.get(k)
        if v is None:
            print(f"   ✗  {k}: <not set>")
        else:
            preview = str(v)[:80]
            print(f"   ✓  {k}: {preview}{'...' if len(str(v)) > 80 else ''}")

    decision = session.state.get(DECISION_KEY)
    print(f"\n{DECISION_KEY}: {decision!r}")
    return 0


# ===================================================================== #
# Helpers
# ===================================================================== #
async def _stream(runner: Runner, *, session_id: str,
                  message: types.Content) -> Optional[str]:
    """Run the orchestrator; capture the last text reply for display."""
    final = None
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for p in event.content.parts:
                if getattr(p, "text", None):
                    final = p.text
    return final


async def _status(session_service, session_id: str) -> dict:
    """Compute a quick paused/stopped/done snapshot from session state."""
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id,
    )
    state = session.state or {}
    gate_result = state.get("gate_result")
    has_final = state.get("final_verdict") is not None
    return {
        "exists":  True,
        "paused":  gate_result is None and state.get("review_summary") is not None,
        "stopped": gate_result == "denied",
        "done":    has_final,
    }


def _print_status_footer(status: dict, session_id: str, final_text: Optional[str]):
    print()
    if status["paused"]:
        print(f"⏸  paused — to resume:")
        print(f'     python main.py --resume {session_id} approved')
        print(f'     python main.py --resume {session_id} denied')
    elif status["stopped"]:
        print(f"✗  stopped (denied). No further phases ran.")
    elif status["done"]:
        print(f"✓  completed.")
        if final_text:
            print(f"   {final_text}")
    print()


# ===================================================================== #
# Main
# ===================================================================== #
def main() -> int:
    p = argparse.ArgumentParser(description="Resumable ADK pipeline demo")
    p.add_argument("message", nargs="?", help="case description (fresh start)")
    p.add_argument("--resume", metavar="SESSION_ID",
                   help="resume the given session with the decision in `message`")
    p.add_argument("--status", metavar="SESSION_ID",
                   help="show progress of a session without running")
    args = p.parse_args()

    try:
        if args.status:
            return asyncio.run(cmd_status(args.status))
        if args.resume:
            if not args.message:
                print("provide the decision as the positional argument")
                return 2
            return asyncio.run(cmd_resume(args.resume, args.message))
        if args.message:
            return asyncio.run(cmd_start(args.message))
        p.print_help()
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
