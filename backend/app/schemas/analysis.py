from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

AnalysisText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: AnalysisText
    observation: AnalysisText


class ServiceAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: AnalysisText
    summary: AnalysisText
    probable_cause: AnalysisText
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence]
    recommended_checks: list[AnalysisText]


class IncidentReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: AnalysisText
    probable_root_cause: AnalysisText
    confidence: float = Field(ge=0, le=1)
    affected_services: list[AnalysisText]
    impact: AnalysisText
    timeline_summary: AnalysisText
    supporting_evidence: list[AnalysisText]
    recommended_actions: list[AnalysisText]
