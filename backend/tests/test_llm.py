from unittest.mock import Mock, patch

import pytest
from pydantic import SecretStr, ValidationError

from app.schemas.analysis import IncidentReport, ServiceAnalysis
from app.services import llm
from app.services.llm import build_gemini_json_schema, parse_structured_output

VALID_SERVICE_ANALYSIS_JSON = """{
  "service": "checkout-api",
  "summary": "Elevated errors were observed.",
  "probable_cause": "The available evidence suggests service failure.",
  "confidence": 0.78,
  "evidence": [{
    "timestamp": "2026-10-05T08:02:10Z",
    "observation": "HTTP 503 rate exceeded threshold"
  }],
  "recommended_checks": ["Inspect service health"]
}"""

VALID_INCIDENT_REPORT_JSON = """{
  "executive_summary": "Checkout errors were observed.",
  "probable_root_cause": "The supplied evidence suggests checkout degradation.",
  "confidence": 0.74,
  "affected_services": ["checkout-api"],
  "impact": "Checkout requests returned errors.",
  "timeline_summary": "The supplied event occurred at 08:02 UTC.",
  "supporting_evidence": ["HTTP 503 rate exceeded threshold"],
  "recommended_actions": ["Inspect checkout service health"]
}"""


def test_structured_service_analysis_parsing() -> None:
    model = parse_structured_output(VALID_SERVICE_ANALYSIS_JSON, ServiceAnalysis)

    assert model.service == "checkout-api"
    assert model.confidence == 0.78


def test_gemini_request_uses_standard_json_schema_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm.settings, "gemini_api_key", SecretStr("test-key"))
    monkeypatch.setattr(llm.settings, "gemini_model", "gemini-3.5-flash-lite")
    client = Mock()
    client.models.generate_content.return_value = Mock(text=VALID_SERVICE_ANALYSIS_JSON)

    with patch("app.services.llm.genai.Client", return_value=client):
        result = llm.generate_service_analysis(
            service="checkout-api",
            incident_context={"title": "Incident", "environment": "test"},
            events=[
                {
                    "timestamp": "2026-10-05T08:02:10Z",
                    "message": "HTTP 503 rate exceeded threshold",
                }
            ],
        )

    assert result.service == "checkout-api"
    request = client.models.generate_content.call_args.kwargs
    assert request["model"] == "gemini-3.5-flash-lite"
    config = request["config"]
    assert config.response_schema is None
    assert config.response_json_schema == build_gemini_json_schema(ServiceAnalysis)


def test_final_report_request_uses_its_standard_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm.settings, "gemini_api_key", SecretStr("test-key"))
    monkeypatch.setattr(llm.settings, "gemini_model", "gemini-3.5-flash-lite")
    client = Mock()
    client.models.generate_content.return_value = Mock(text=VALID_INCIDENT_REPORT_JSON)
    normalized_incident = {
        "title": "Incident",
        "environment": "test",
        "events": [
            {
                "timestamp": "2026-10-05T08:02:10Z",
                "service": "checkout-api",
                "message": "HTTP 503 rate exceeded threshold",
            }
        ],
    }

    with patch("app.services.llm.genai.Client", return_value=client):
        result = llm.generate_incident_report(
            normalized_incident=normalized_incident,
            deterministic_summary={"services": ["checkout-api"]},
            service_analyses=[],
        )

    assert result.affected_services == ["checkout-api"]
    config = client.models.generate_content.call_args.kwargs["config"]
    assert config.response_schema is None
    assert config.response_json_schema == build_gemini_json_schema(IncidentReport)


@pytest.mark.parametrize("schema", [ServiceAnalysis, IncidentReport])
def test_gemini_schema_retains_strict_objects_and_supported_keywords(schema) -> None:
    pydantic_schema = schema.model_json_schema()
    gemini_schema = build_gemini_json_schema(schema)

    assert pydantic_schema["additionalProperties"] is False
    assert gemini_schema["additionalProperties"] is False
    assert set(gemini_schema["required"]) == set(schema.model_fields)
    assert "minLength" in str(pydantic_schema)
    assert "minLength" not in str(gemini_schema)

    if schema is ServiceAnalysis:
        assert pydantic_schema["$defs"]["Evidence"]["additionalProperties"] is False
        assert gemini_schema["$defs"]["Evidence"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "response_text",
    [
        "not JSON",
        """{
          "service": "checkout-api",
          "summary": "",
          "probable_cause": "Unknown.",
          "confidence": 0.4,
          "evidence": [],
          "recommended_checks": []
        }""",
        """{
          "service": "checkout-api",
          "summary": "Elevated errors were observed.",
          "probable_cause": "Unknown.",
          "confidence": 1.4,
          "evidence": [],
          "recommended_checks": []
        }""",
    ],
)
def test_malformed_model_output_is_rejected(response_text: str) -> None:
    with pytest.raises(ValidationError):
        parse_structured_output(response_text, ServiceAnalysis)


def test_missing_gemini_configuration_fails_only_when_analysis_is_attempted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm.settings, "gemini_api_key", SecretStr(""))
    monkeypatch.setattr(llm.settings, "gemini_model", "")

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm.generate_service_analysis(
            service="checkout-api",
            incident_context={"title": "Incident", "environment": "test"},
            events=[
                {
                    "timestamp": "2026-10-05T08:02:10Z",
                    "message": "HTTP 503 rate exceeded threshold",
                }
            ],
        )
