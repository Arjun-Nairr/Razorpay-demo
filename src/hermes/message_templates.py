"""Deterministic approved customer-message copy.

A live model must NOT emit free-form customer text. The engine's
``_validate_proposal`` accepts a proposal's ``message_intent`` only when it is
verbatim one of :data:`APPROVED_MESSAGE_INTENTS`; anything else is rejected as
invalid strategist output (repair, then failure). The copy here never promises
a discount, threatens suspension, claims payment success, or contains a URL,
amount, or provider identifier - those rules are baked into the fixed strings,
not re-checked per generation.

A verified Telegram send now exists in this build (see HANDOFF.md Iteration
26) - the message is real, but its copy is still this single fixed,
deterministic template only.

For the isolated real Hermes runtime specifically, this template is exposed
to and accepted from the child ONLY when the evidence actually disclosed for
that decision proves a reliable customer (see
``hermes_agent_strategist._reliable_customer_from_evidence``); otherwise no
approved message is offered and any non-null ``message_intent`` the child
still returns is rejected fail-closed before it reaches this module's check.
"""

from __future__ import annotations

# Exactly one approved template - what ``ScriptedStrategist`` proposes and the
# only copy a live model may ever attach. No discount, suspension threat,
# payment-success claim, URL, amount, or provider identifier; the recovery
# URL is appended separately by the engine (never by Hermes) at delivery time.
APPROVED_MESSAGE_INTENTS: frozenset[str] = frozenset(
    {
        "Hi, I’m Hermes, the automated billing assistant. We couldn’t "
        "complete your latest subscription payment. You can use the secure "
        "link below to complete it with an available payment method. If "
        "you’ve already resolved the payment elsewhere, please ignore "
        "this reminder.",
    }
)


def is_approved_message_intent(text: str | None) -> bool:
    """True when ``text`` is None (no message) or an exact approved template."""
    return text is None or text in APPROVED_MESSAGE_INTENTS


# For the model prompt: an ordered, stable list of the exact strings it may pick.
APPROVED_MESSAGE_INTENT_LIST: tuple[str, ...] = tuple(sorted(APPROVED_MESSAGE_INTENTS))
