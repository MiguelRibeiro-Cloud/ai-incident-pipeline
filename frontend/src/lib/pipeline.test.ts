import { DEMO_INCIDENT } from './demoIncident'
import { deriveServiceStates, getIncidentServices } from './pipeline'
import type { JobExecutionEvent, JobResponse } from '../types/api'

test('derives dynamic service branches from current job data', () => {
  const services = getIncidentServices(DEMO_INCIDENT, {
    deterministic_summary: {
      event_count: 2,
      earliest_timestamp: '2026-10-05T08:00:00Z',
      latest_timestamp: '2026-10-05T08:01:00Z',
      services: ['edge-api', 'ledger-service'],
      sources: ['test'],
      severity_counts: { ERROR: 2 },
      error_event_count: 2,
    },
  } as unknown as JobResponse)

  expect(services).toEqual(['edge-api', 'ledger-service'])
})

test('derives a retrying branch and its countdown from durable events', () => {
  const events: JobExecutionEvent[] = [{
    id: 1,
    job_id: 'job',
    created_at: '2026-10-05T08:00:00Z',
    event_type: 'RETRY_SCHEDULED',
    stage: 'analyze_service',
    service: 'checkout-api',
    celery_task_id: 'task',
    attempt: 1,
    message: 'retrying',
    metadata: { countdown_seconds: 2.3 },
  }]

  const [branch] = deriveServiceStates(['checkout-api'], events)
  expect(branch.state).toBe('retrying')
  expect(branch.attempts).toEqual([{ attempt: 1, outcome: 'retrying', message: 'retrying', retryDelay: 2.3 }])
})
