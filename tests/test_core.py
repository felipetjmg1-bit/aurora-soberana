from aurora_soberana import AuroraGovernance, Policy, RequestContext


def policy():
    return Policy(
        allowed_actors=frozenset({"operator-1"}),
        allowed_actions=frozenset({"read"}),
        allowed_resources=frozenset({"catalog"}),
        allowed_classifications=frozenset({"public", "personal"}),
    )


def test_default_policy_denies_everything():
    decision = AuroraGovernance().evaluate(
        RequestContext("operator-1", "read", "catalog", "support")
    )
    assert decision.allowed is False
    assert decision.reason == "actor_not_allowed"


def test_explicit_policy_allows_matching_request():
    decision = AuroraGovernance(policy()).evaluate(
        RequestContext("operator-1", "read", "catalog", "support")
    )
    assert decision.allowed is True
    assert decision.reason == "policy_match"


def test_sensitive_data_requires_consent_reference():
    decision = AuroraGovernance(policy()).evaluate(
        RequestContext(
            "operator-1", "read", "catalog", "support",
            data_classification="personal",
        )
    )
    assert decision.allowed is False
    assert decision.reason == "consent_reference_required"


def test_audit_chain_is_verifiable():
    engine = AuroraGovernance(policy())
    engine.evaluate(RequestContext("operator-1", "read", "catalog", "support"))
    engine.evaluate(RequestContext("intruder", "read", "catalog", "support"))
    assert engine.verify_audit_chain()
    assert len(engine.audit_events()) == 2


def test_audit_chain_detects_tampering():
    engine = AuroraGovernance(policy())
    engine.evaluate(RequestContext("operator-1", "read", "catalog", "support"))
    engine._events[0]["actor"] = "changed"
    assert not engine.verify_audit_chain()



def test_missing_purpose_is_denied_without_crashing():
    decision = AuroraGovernance(policy()).evaluate(
        RequestContext("operator-1", "read", "catalog", None)  # type: ignore[arg-type]
    )
    assert decision.allowed is False
    assert decision.reason == "purpose_required"
