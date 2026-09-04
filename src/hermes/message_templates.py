"""Deterministic approved customer-message copy.

A live model must NOT emit free-form customer text. The engine's
``_validate_proposal`` accepts a proposal's ``message_intent`` only when it is
verbatim one of :data:`APPROVED_MESSAGE_INTENTS`; anything else is rejected as
invalid strategist output (repair, then failure). The copy here never promises
a discount, threatens suspension, claims payment success, or contains a URL,
amount, or provider identifier - those rules are baked into the fixed strings,
not re-checked per generation.

No customer message is ever actually sent in this build; the recovery
intervention is simulated and labelled.
"""

from __future__ import annotations

# The first entry is what ``ScriptedStrategist`` proposes; it must stay in the
# set for the offline Case 3 tests. The others give a live model a small honest
# choice without opening free-text generation.
APPROVED_MESSAGE_INTENTS: frozenset[str] = frozenset(
    {
        "Your last payment attempt did not go through. "
        "Please use the secure link we sent to complete it.",
        "We could not process your recent subscription payment. "
        "A secure link to finish it is ready for you.",
        "Your subscription payment did not complete. "
        "You can retry it using the secure link we provided.",
    }
)


def is_approved_message_intent(text: str | None) -> bool:
    """True when ``text`` is None (no message) or an exact approved template."""
    return text is None or text in APPROVED_MESSAGE_INTENTS


# For the model prompt: an ordered, stable list of the exact strings it may pick.
APPROVED_MESSAGE_INTENT_LIST: tuple[str, ...] = tuple(sorted(APPROVED_MESSAGE_INTENTS))
