import type {
  IncidentInput,
  JobExecutionEvent,
  JobResponse,
  PipelineState,
} from '../types/api'

export interface ServicePipelineState {
  service: string
  state: PipelineState
  attempts: Array<{
    attempt: number
    outcome: 'started' | 'retrying' | 'completed' | 'failed'
    message: string
    retryDelay?: number
  }>
}

function eventsForStage(events: JobExecutionEvent[], stage: string) {
  return events.filter((event) => event.stage === stage)
}

function hasEvent(events: JobExecutionEvent[], eventType: JobExecutionEvent['event_type']) {
  return events.some((event) => event.event_type === eventType)
}

export function deriveLinearStageState(
  stage: 'normalize_incident' | 'summarize_events',
  job: JobResponse | undefined,
  events: JobExecutionEvent[],
): PipelineState {
  if (!job) return 'waiting'
  const stageEvents = eventsForStage(events, stage)
  if (hasEvent(stageEvents, 'TASK_FAILED')) return 'failed'
  if (stage === 'normalize_incident') {
    if (job.deterministic_summary || events.some((event) => event.stage === 'summarize_events')) {
      return 'completed'
    }
  } else if (job.deterministic_summary) {
    return 'completed'
  }
  if (hasEvent(stageEvents, 'TASK_STARTED')) return 'running'
  if (job.status === 'FAILED') return 'failed'
  return 'waiting'
}

export function getIncidentServices(incident: IncidentInput, job?: JobResponse): string[] {
  const summaryServices = job?.deterministic_summary?.services
  if (summaryServices?.length) return summaryServices
  return [...new Set(incident.events.map((event) => event.service))].sort()
}

export function deriveServiceStates(
  services: string[],
  events: JobExecutionEvent[],
  completedServices: string[] = [],
): ServicePipelineState[] {
  return services.map((service) => {
    const serviceEvents = events.filter(
      (event) => event.stage === 'analyze_service' && event.service === service,
    )
    const attempts = [...new Set(serviceEvents.map((event) => event.attempt).filter(Boolean))].map(
      (attemptValue) => {
        const attempt = attemptValue as number
        const attemptEvents = serviceEvents.filter((event) => event.attempt === attempt)
        const retry = attemptEvents.find((event) => event.event_type === 'RETRY_SCHEDULED')
        const failed = attemptEvents.find((event) => event.event_type === 'TASK_FAILED')
        const completed = attemptEvents.find((event) => event.event_type === 'TASK_SUCCEEDED')
        return {
          attempt,
          outcome: (completed
            ? 'completed'
            : failed
              ? 'failed'
              : retry
                ? 'retrying'
                : 'started') as ServicePipelineState['attempts'][number]['outcome'],
          message: completed?.message ?? failed?.message ?? retry?.message ?? 'Analysis started',
          retryDelay:
            typeof retry?.metadata?.countdown_seconds === 'number'
              ? retry.metadata.countdown_seconds
              : undefined,
        }
      },
    )

    let state: PipelineState = 'waiting'
    if (completedServices.includes(service) || hasEvent(serviceEvents, 'TASK_SUCCEEDED')) {
      state = 'completed'
    } else if (hasEvent(serviceEvents, 'TASK_FAILED')) {
      state = 'failed'
    } else {
      const lastEvent = serviceEvents.at(-1)
      if (lastEvent?.event_type === 'RETRY_SCHEDULED') state = 'retrying'
      else if (serviceEvents.length) state = 'running'
    }
    return { service, state, attempts }
  })
}

export function deriveSynthesisState(
  job: JobResponse | undefined,
  events: JobExecutionEvent[],
): PipelineState {
  if (!job) return 'waiting'
  if (job.status === 'COMPLETED') return 'completed'
  const synthesisEvents = eventsForStage(events, 'synthesize_incident_report')
  if (hasEvent(synthesisEvents, 'TASK_FAILED') || job.status === 'FAILED') return 'failed'
  const last = synthesisEvents.at(-1)
  if (last?.event_type === 'RETRY_SCHEDULED') return 'retrying'
  if (synthesisEvents.length) return 'running'
  return 'waiting'
}
