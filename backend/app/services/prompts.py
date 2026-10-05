SERVICE_ANALYSIS_INSTRUCTION = """You analyze one service using only supplied incident events.
Do not invent logs, metrics, infrastructure, dependencies, deployments, or events.
Separate observed evidence from inference and express uncertainty through confidence.
Evidence must copy an event timestamp and message exactly. Recommendations may propose checks,
but must not claim those checks were performed."""


INCIDENT_SYNTHESIS_INSTRUCTION = """Synthesize an incident report using only the supplied original
events, deterministic summary, and validated service analyses. Do not invent facts, infrastructure,
dependencies, deployments, or events. Separate evidence from inference and express uncertainty
through confidence. Supporting evidence must copy original event messages exactly. Recommendations
may propose actions, but must not claim they were performed."""
