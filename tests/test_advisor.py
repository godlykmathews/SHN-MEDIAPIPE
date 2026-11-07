"""Verify that care guidance and references come from the local library."""
import asyncio
import json

import httpx
import pytest

from app import config
from app.advisor import OllamaAdvisor
from app.schemas import Finding


@pytest.fixture
def advisor():
    instance = OllamaAdvisor()
    yield instance
    asyncio.run(instance.close())


def finding(category="disease", issue="Possible early blight", **extra):
    return Finding.model_validate({
        "plant": "Tomato",
        "issue": issue,
        "category": category,
        "summary": "A possible issue is visible.",
        "observations": ["Leaf patches"],
        "possible_causes": [issue],
        "uncertainty": "Image-based assessment.",
        "needs_expert": category == "uncertain",
        **extra,
    })


@pytest.mark.parametrize("category", ["healthy", "uncertain", "not_plant"])
def test_non_diagnostic_categories_do_not_receive_specific_disease_care(advisor, category):
    result = finding(category=category, issue="Early blight or rust")
    assert [entry["id"] for entry in advisor.care_for(result)] == ["general"]
    built = advisor.make_report(result)
    if category == "not_plant":
        assert built.treatment == []
        assert built.sources == []
    else:
        general = next(entry for entry in advisor.remedies if entry["id"] == "general")
        assert built.treatment == general["treatment"]


@pytest.mark.parametrize(
    "issue, expected",
    [
        ("Tomato___Early_blight", "early_blight"),
        ("Possible two-spotted spider mites", "spider_mites"),
        ("Likely aphids", "aphids"),
        ("Unknown damage to the crust", "general"),
    ],
)
def test_remedies_match_complete_normalized_issue_terms(advisor, issue, expected):
    assert [entry["id"] for entry in advisor.care_for(finding(issue=issue))] == [expected]


def test_generated_treatment_and_citations_cannot_replace_reviewed_care(advisor):
    generated = finding(
        issue="Aphids",
        treatment=["Invented pesticide dose"],
        immediate_actions=["Invented treatment"],
        sources=[{"title": "Fabricated source", "url": "https://untrusted.example/"}],
    )
    result = advisor.make_report(generated)
    aphids = next(entry for entry in advisor.remedies if entry["id"] == "aphids")
    assert result.treatment == aphids["treatment"]
    assert result.immediate_actions == aphids["immediate_actions"]
    assert [source.model_dump() for source in result.sources] == aphids["sources"]


def test_unmatched_disease_is_explicitly_general_care(advisor):
    result = advisor.make_report(finding(issue="Uncatalogued leaf disease"))
    assert "no specific treatment record" in result.uncertainty
    general = next(entry for entry in advisor.remedies if entry["id"] == "general")
    assert result.treatment == general["treatment"]


def test_overlapping_remedies_do_not_duplicate_advice_or_sources(advisor):
    result = advisor.make_report(finding(issue="Early blight with leaf spots"))
    assert len(result.treatment) == len(set(result.treatment))
    assert len(result.sources) == len({source.url for source in result.sources})


@pytest.mark.parametrize("failure", ["http", "timeout", "invalid-json"])
def test_one_failed_model_discovery_does_not_hide_other_models_or_cache_failure(advisor, monkeypatch, failure):
    monkeypatch.setattr(config, "OLLAMA_MODEL", "")
    monkeypatch.setattr(config, "OLLAMA_VISION_MODEL", "")
    attempts = {"llama3.2:3b": 0, "working-vision": 0}

    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": name} for name in attempts]})
        assert request.url.path == "/api/show"
        name = json.loads(request.content)["model"]
        attempts[name] += 1
        if name == "llama3.2:3b" and attempts[name] == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("Model metadata timed out", request=request)
            if failure == "invalid-json":
                return httpx.Response(200, text="not valid JSON")
            return httpx.Response(500, json={"error": "Could not inspect this model"})
        return httpx.Response(200, json={"capabilities": ["completion", "vision"] if name == "working-vision" else ["completion"]})

    async def exercise():
        await advisor.client.aclose()
        advisor.client = httpx.AsyncClient(
            base_url="http://ollama.test", transport=httpx.MockTransport(handle)
        )
        initial = await advisor.status()
        assert initial["available"] is True
        assert initial["vision_model"] == "working-vision"
        assert initial["model"] == "working-vision"
        assert initial["error"] is None
        assert "llama3.2:3b" not in advisor.capabilities

        # A refresh retries only failed discoveries; the recovered preferred
        # text model becomes available without restarting the application.
        refreshed = await advisor.status(refresh=True)
        assert refreshed["available"] is True
        assert refreshed["model"] == "llama3.2:3b"
        assert refreshed["vision_model"] == "working-vision"
        assert refreshed["error"] is None
        assert attempts == {"llama3.2:3b": 2, "working-vision": 1}

    asyncio.run(exercise())
