import json
from typing import Any, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import settings
from app.schemas.analysis import IncidentReport, ServiceAnalysis
from app.services.llm_errors import raise_classified_provider_exception
from app.services.prompts import INCIDENT_SYNTHESIS_INSTRUCTION, SERVICE_ANALYSIS_INSTRUCTION

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)
GEMINI_JSON_SCHEMA_KEYWORDS = frozenset(
    {
        "$anchor",
        "$defs",
        "$id",
        "$ref",
        "additionalProperties",
        "anyOf",
        "description",
        "enum",
        "format",
        "items",
        "maximum",
        "maxItems",
        "minimum",
        "minItems",
        "oneOf",
        "prefixItems",
        "properties",
        "propertyOrdering",
        "required",
        "title",
        "type",
    }
)


def build_gemini_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Return the model schema limited to Gemini's documented JSON Schema subset.

    Pydantic emits ``minLength`` for our non-empty strings, but the installed
    Google Gen AI SDK does not list that keyword as supported by
    ``response_json_schema``. It is omitted only from the provider request;
    the unchanged Pydantic model still enforces it when parsing the response.
    Unknown future keywords fail locally instead of producing a remote 400.
    """

    def normalize(node: Any, path: str) -> Any:
        if isinstance(node, list):
            return [normalize(item, f"{path}[]") for item in node]
        if not isinstance(node, dict):
            return node

        normalized: dict[str, Any] = {}
        for keyword, value in node.items():
            if keyword == "minLength":
                continue
            if keyword not in GEMINI_JSON_SCHEMA_KEYWORDS:
                raise ValueError(f"Unsupported Gemini JSON Schema keyword {keyword!r} at {path}")
            if keyword in {"$defs", "properties"}:
                normalized[keyword] = {
                    name: normalize(subschema, f"{path}.{keyword}.{name}")
                    for name, subschema in value.items()
                }
            else:
                normalized[keyword] = normalize(value, f"{path}.{keyword}")
        return normalized

    return normalize(schema.model_json_schema(), schema.__name__)


def parse_structured_output(
    response_text: str | None, schema: type[StructuredOutput]
) -> StructuredOutput:
    """Validate model text even when the provider promises schema-constrained JSON."""
    if not response_text:
        raise ValueError("Gemini returned an empty response")
    return schema.model_validate_json(response_text)


def _generate_structured(
    *, prompt: str, system_instruction: str, schema: type[StructuredOutput]
) -> StructuredOutput:
    api_key = settings.gemini_api_key.get_secret_value()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for AI analysis")
    if not settings.gemini_model:
        raise RuntimeError("GEMINI_MODEL is required for AI analysis")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.1,
                response_mime_type="application/json",
                response_json_schema=build_gemini_json_schema(schema),
            ),
        )
    except Exception as exc:
        raise_classified_provider_exception(exc)
    return parse_structured_output(response.text, schema)


def generate_service_analysis(
    *, service: str, incident_context: dict[str, Any], events: list[dict[str, Any]]
) -> ServiceAnalysis:
    prompt = json.dumps(
        {"service": service, "incident": incident_context, "events_for_service": events},
        separators=(",", ":"),
    )
    result = _generate_structured(
        prompt=prompt,
        system_instruction=SERVICE_ANALYSIS_INSTRUCTION,
        schema=ServiceAnalysis,
    )
    if result.service != service:
        raise ValueError(
            f"Gemini analyzed service {result.service!r}; expected assigned service {service!r}"
        )

    supplied_evidence = {(str(event["timestamp"]), str(event["message"])) for event in events}
    for evidence in result.evidence:
        if (evidence.timestamp, evidence.observation) not in supplied_evidence:
            raise ValueError("Gemini evidence does not match a supplied service event")
    return result


def generate_incident_report(
    *,
    normalized_incident: dict[str, Any],
    deterministic_summary: dict[str, Any],
    service_analyses: list[dict[str, Any]],
) -> IncidentReport:
    prompt = json.dumps(
        {
            "incident": normalized_incident,
            "deterministic_summary": deterministic_summary,
            "service_analyses": service_analyses,
        },
        separators=(",", ":"),
    )
    result = _generate_structured(
        prompt=prompt,
        system_instruction=INCIDENT_SYNTHESIS_INSTRUCTION,
        schema=IncidentReport,
    )

    services = set(deterministic_summary.get("services", []))
    if not set(result.affected_services).issubset(services):
        raise ValueError("Gemini report names a service absent from the incident")
    event_messages = {str(event["message"]) for event in normalized_incident.get("events", [])}
    if not set(result.supporting_evidence).issubset(event_messages):
        raise ValueError("Gemini report evidence does not match supplied incident events")
    return result
