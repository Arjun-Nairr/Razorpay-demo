"""In-memory test doubles for the three external seams.

Real Razorpay / Gemini / Neon adapters land in a later iteration behind these
same method shapes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import (
    AuditEvent,
    Case,
    ProposalAction,
    RazorpayWebhook,
    ScheduledWork,
    StrategyProposal,
    WebhookType,
)


# --- Razorpay ---------------------------------------------------------------


@dataclass(frozen=True)
class CaptureInfo:
    obligation_id: str
    payment_id: str
    amount_minor: int


class FakeRazorpayAdapter:
    """Holds captured payments the engine has been told about, and 'verifies'
    them. In this slice a captured webhook is trusted, so verification only
    confirms the recorded amount/obligation are self-consistent.
    """

    def __init__(self) -> None:
        self._captures: dict[str, CaptureInfo] = {}  # obligation_id -> capture

    def record_capture(self, obligation_id: str, payment_id: str, amount_minor: int) -> None:
        self._captures.setdefault(
            obligation_id, CaptureInfo(obligation_id, payment_id, amount_minor)
        )

    def verify_capture(self, obligation_id: str) -> CaptureInfo | None:
        return self._captures.get(obligation_id)


# --- AI strategist --------------------------------------------------------


class ScriptedStrategist:
    """Returns a canned typed proposal keyed by failure reason code.

    ``calls`` lets tests assert the strategist is not consulted for terminal
    cases.
    """

    _DEFAULT_SCRIPT: dict[str, StrategyProposal] = {
        "bank_temporary_error": StrategyProposal(
            action=ProposalAction.WAIT_FOR_PROVIDER_RETRY,
            diagnosis="Temporary bank-side decline; provider retry is eligible.",
            rationale="Normal payment history and a transient error: wait for the "
            "next Razorpay-managed retry before any customer contact.",
            confidence=0.82,
            proposed_wait_hours=24,
        ),
    }

    def __init__(self, script: dict[str, StrategyProposal] | None = None) -> None:
        self.script = script or dict(self._DEFAULT_SCRIPT)
        self.calls = 0

    def propose(self, snapshot: dict) -> StrategyProposal:
        self.calls += 1
        reason = snapshot.get("reason_code") or ""
        try:
            return self.script[reason]
        except KeyError:  # keep the failure typed and obvious
            raise KeyError(f"ScriptedStrategist has no proposal for reason {reason!r}")


# --- Recovery ledger -----------------------------------------------------


class InMemoryLedger:
    """Authoritative in-memory state: cases, scheduled work, append-only audit,
    provider-event dedup, and the recovered-value accumulator.
    """

    def __init__(self) -> None:
        self.cases: dict[str, Case] = {}
        self._by_obligation: dict[str, str] = {}  # obligation_id -> case_id
        self.work: list[ScheduledWork] = []
        self.audit: list[AuditEvent] = []
        self.seen_events: set[str] = set()
        self.recovered_minor: int = 0
        self._seq = 0
        self._id_seq = 0

    # cases
    def add_case(self, case: Case) -> None:
        self.cases[case.case_id] = case
        self._by_obligation[case.obligation_id] = case.case_id

    def case_for_obligation(self, obligation_id: str) -> Case | None:
        case_id = self._by_obligation.get(obligation_id)
        return self.cases.get(case_id) if case_id else None

    # scheduled work
    def add_work(self, work: ScheduledWork) -> None:
        self.work.append(work)

    def pending_work(self, case_id: str) -> list[ScheduledWork]:
        return [w for w in self.work if w.case_id == case_id and not w.cancelled]

    def due_work(self, at: int) -> list[ScheduledWork]:
        return sorted(
            (w for w in self.work if not w.cancelled and w.due_time <= at),
            key=lambda w: (w.due_time, w.work_id),
        )

    # audit
    def append_audit(self, logical_time: int, case_id: str, kind: str, detail: dict) -> AuditEvent:
        self._seq += 1
        event = AuditEvent(self._seq, logical_time, case_id, kind, dict(detail))
        self.audit.append(event)
        return event

    def next_id(self, prefix: str) -> str:
        self._id_seq += 1
        return f"{prefix}-{self._id_seq}"
