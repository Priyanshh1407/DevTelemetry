"""UPG-06: coaching guides can quote savings the code computed (prompt v3), never estimated ones."""
import ai.coaching_service as service
from ai.fallback import rule_based_guide
from ai.features import coaching_facts
from tests.conftest import engineer_id
from tests.test_prompts import SAVINGS, V2_DAY

RECENT = [dict(V2_DAY, compact_uses=2)] * 6


def test_the_fallback_guide_quotes_a_computed_saving():
    guide = rule_based_guide(coaching_facts(V2_DAY, RECENT, savings=SAVINGS))
    cache = next(a for a in guide["actions"] if a["focus"] == "cache")
    model = next(a for a in guide["actions"] if a["focus"] == "model_mix")
    assert "$61.27 per 30 days" in cache["problem"] and "82.4%" in cache["problem"]
    assert "$" not in model["problem"]                       # no saving to quote: none invented


def test_the_fallback_guide_without_savings_is_unchanged():
    facts = coaching_facts(V2_DAY, RECENT)
    assert "savings" not in facts
    assert all("per 30 days" not in a["problem"] for a in rule_based_guide(facts)["actions"])


def test_v3_service_sends_savings_computed_from_the_database(seeded_db, mock_gemini, monkeypatch):
    monkeypatch.setattr(service, "PROMPT_VERSION", "v3")

    coaching = service.get_coaching(engineer_id(0), "critical")

    prompt = mock_gemini.models.generate_content.call_args.kwargs["contents"]
    assert "SAVINGS (computed by re-pricing this engineer's real tokens from the last 3 days)" in prompt
    assert coaching.result.prompt_version == "v3"


def test_v2_service_sends_no_savings(seeded_db, mock_gemini):
    service.get_coaching(engineer_id(0), "critical")
    assert "SAVINGS" not in mock_gemini.models.generate_content.call_args.kwargs["contents"]
