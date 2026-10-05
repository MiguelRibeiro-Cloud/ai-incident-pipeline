export type JobStatus = 'QUEUED' | 'PROCESSING' | 'COMPLETED' | 'FAILED'

export type ExecutionEventType =
  | 'WORKFLOW_STARTED'
  | 'TASK_STARTED'
  | 'AI_REQUEST_STARTED'
  | 'CHAOS_FAILURE_INJECTED'
  | 'CHAOS_DELAY_INJECTED'
  | 'RETRY_SCHEDULED'
  | 'TASK_SUCCEEDED'
  | 'TASK_FAILED'
  | 'TASK_REDELIVERED'
  | 'SYNTHESIS_STARTED'
  | 'JOB_COMPLETED'
  | 'JOB_FAILED'

export interface IncidentEvent {
  timestamp: string
  source: string
  service: string
  severity: string
  message: string
}

export interface ChaosConfig {
  enabled: boolean
  fail_service: string
  fail_attempts: number
}

export interface IncidentInput {
  title: string
  environment: string
  events: IncidentEvent[]
  chaos?: ChaosConfig
}

export interface DeterministicSummary {
  event_count: number
  earliest_timestamp: string
  latest_timestamp: string
  services: string[]
  sources: string[]
  severity_counts: Record<string, number>
  error_event_count: number
}

export interface Evidence {
  timestamp: string
  observation: string
}

export interface ServiceAnalysis {
  service: string
  summary: string
  probable_cause: string
  confidence: number
  evidence: Evidence[]
  recommended_checks: string[]
}

export interface IncidentReportData {
  executive_summary: string
  probable_root_cause: string
  confidence: number
  affected_services: string[]
  impact: string
  timeline_summary: string
  supporting_evidence: string[]
  recommended_actions: string[]
}

export interface JobResult {
  deterministic_summary: DeterministicSummary
  service_analyses: ServiceAnalysis[]
  incident_report: IncidentReportData
  workflow?: { type: string; stages: string[] }
}

export interface JobResponse {
  id: string
  status: JobStatus
  progress: number
  celery_task_id: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  incident: IncidentInput | null
  deterministic_summary: DeterministicSummary | null
  service_analyses: ServiceAnalysis[]
  result: JobResult | null
  error: string | null
}

export interface JobExecutionEvent {
  id: number
  job_id: string
  created_at: string
  event_type: ExecutionEventType
  stage: string
  service: string | null
  celery_task_id: string | null
  attempt: number | null
  message: string
  metadata: Record<string, unknown> | null
}

export type PipelineState = 'waiting' | 'running' | 'retrying' | 'completed' | 'failed'
