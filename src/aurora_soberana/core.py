"""Motor de políticas default-deny e trilha de auditoria encadeada."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class RequestContext:
    actor: str
    action: str
    resource: str
    purpose: str
    data_classification: str = "public"
    consent_reference: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class Policy:
    allowed_actors: frozenset[str]
    allowed_actions: frozenset[str]
    allowed_resources: frozenset[str]
    allowed_classifications: frozenset[str] = frozenset({"public"})
    require_purpose: bool = True
    require_consent_for_sensitive: bool = True

    @classmethod
    def restrictive_default(cls) -> "Policy":
        return cls(
            allowed_actors=frozenset(),
            allowed_actions=frozenset(),
            allowed_resources=frozenset(),
        )


@dataclass(frozen=True)
class Decision:
    request_id: str
    allowed: bool
    reason: str
    policy_version: str
    audit_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuroraGovernance:
    """Avalia autorização explicitamente e registra decisões sem armazenar payloads."""

    def __init__(self, policy: Policy | None = None) -> None:
        self.policy = policy or Policy.restrictive_default()
        self._events: list[dict[str, Any]] = []
        self._last_hash = "0" * 64

    def evaluate(self, context: RequestContext) -> Decision:
        request_id = context.request_id or str(uuid4())
        reason = self._deny_reason(context)
        allowed = reason is None
        reason = "policy_match" if allowed else reason
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "actor": context.actor,
            "action": context.action,
            "resource": context.resource,
            "purpose_present": bool(context.purpose.strip()),
            "classification": context.data_classification,
            "allowed": allowed,
            "reason": reason,
            "previous_hash": self._last_hash,
        }
        encoded = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        event_hash = sha256(encoded).hexdigest()
        event["event_hash"] = event_hash
        self._events.append(event)
        self._last_hash = event_hash
        return Decision(request_id, allowed, reason, "1.0", event_hash)

    def _deny_reason(self, context: RequestContext) -> str | None:
        if (
            not isinstance(context.actor, str) or not context.actor.strip()
            or not isinstance(context.action, str) or not context.action.strip()
            or not isinstance(context.resource, str) or not context.resource.strip()
        ):
            return "missing_identity_action_or_resource"
        if not isinstance(context.purpose, str):
            return "purpose_required"
        if self.policy.require_purpose and not context.purpose.strip():
            return "purpose_required"
        if context.actor not in self.policy.allowed_actors:
            return "actor_not_allowed"
        if context.action not in self.policy.allowed_actions:
            return "action_not_allowed"
        if context.resource not in self.policy.allowed_resources:
            return "resource_not_allowed"
        if context.data_classification not in self.policy.allowed_classifications:
            return "classification_not_allowed"
        if (
            context.data_classification in {"personal", "sensitive", "restricted"}
            and self.policy.require_consent_for_sensitive
            and not context.consent_reference
        ):
            return "consent_reference_required"
        return None

    def audit_events(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events]

    def verify_audit_chain(self) -> bool:
        previous = "0" * 64
        for event in self._events:
            payload = {key: value for key, value in event.items() if key != "event_hash"}
            if payload.get("previous_hash") != previous:
                return False
            expected = sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if event.get("event_hash") != expected:
                return False
            previous = expected
        return True
