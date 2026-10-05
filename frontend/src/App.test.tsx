import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import type { JobExecutionEvent, JobResponse } from './types/api'

const jobId = '79d0e62b-bf7a-48b0-b5f4-e165b11d565b'

const summary = {
  event_count: 5,
  earliest_timestamp: '2026-10-05T08:01:12Z',
  latest_timestamp: '2026-10-05T08:03:04Z',
  services: ['authentication-service', 'checkout-api', 'payment-service'],
  sources: ['application', 'monitoring'],
  severity_counts: { ERROR: 3, WARNING: 2 },
  error_event_count: 3,
}

const analysis = {
  service: 'checkout-api',
  summary: 'Checkout returned elevated errors.',
  probable_cause: 'The checkout service was likely unavailable.',
  confidence: 0.82,
  evidence: [{ timestamp: '2026-10-05T08:01:12Z', observation: 'HTTP 503 rate exceeded threshold' }],
  recommended_checks: ['Inspect checkout-api health'],
}

function makeJob(status: JobResponse['status'], overrides: Partial<JobResponse> = {}): JobResponse {
  return {
    id: jobId,
    status,
    progress: status === 'COMPLETED' ? 100 : 0,
    celery_task_id: 'celery-1',
    created_at: '2026-10-05T08:00:00Z',
    started_at: status === 'QUEUED' ? null : '2026-10-05T08:00:01Z',
    completed_at: status === 'COMPLETED' || status === 'FAILED' ? '2026-10-05T08:00:10Z' : null,
    incident: null,
    deterministic_summary: status === 'QUEUED' ? null : summary,
    service_analyses: status === 'COMPLETED' ? [analysis] : [],
    result: status === 'COMPLETED' ? {
      deterministic_summary: summary,
      service_analyses: [analysis],
      incident_report: {
        executive_summary: 'Checkout errors blocked customer payments.',
        probable_root_cause: 'Checkout capacity was exhausted.',
        confidence: 0.82,
        affected_services: ['checkout-api', 'payment-service'],
        impact: 'Customers could not complete checkout.',
        timeline_summary: 'Checkout errors preceded payment queue growth.',
        supporting_evidence: ['HTTP 503 rate exceeded threshold'],
        recommended_actions: ['Inspect checkout capacity'],
      },
    } : null,
    error: status === 'FAILED' ? 'analyze_service failed: provider authentication rejected' : null,
    ...overrides,
  }
}

function jsonResponse(value: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } }))
}

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>)
}

function installJobFetch(job: JobResponse, events: JobExecutionEvent[] = []) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (init?.method === 'POST') return jsonResponse(makeJob('QUEUED'), 202)
    if (url.endsWith('/events')) return jsonResponse(events)
    return jsonResponse(job)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

test('submits the prepared incident and enters live processing mode', async () => {
  const fetchMock = installJobFetch(makeJob('PROCESSING', { progress: 40 }))
  const user = userEvent.setup()
  renderApp()

  await user.click(screen.getByRole('button', { name: /run incident analysis/i }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  const postCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
  expect(postCall).toBeDefined()
  const payload = JSON.parse(String(postCall?.[1]?.body))
  expect(payload.title).toBe('Customer checkout outage')
  expect(payload.events).toHaveLength(5)
  expect(screen.getByRole('button', { name: /run incident analysis/i })).toBeDisabled()
  expect(await screen.findByRole('status')).toHaveTextContent(/79d0e62b/i)
})

test('renders a completed final incident report and stops polling', async () => {
  const fetchMock = installJobFetch(makeJob('COMPLETED'))
  const user = userEvent.setup()
  renderApp()
  await user.click(screen.getByRole('button', { name: /run incident analysis/i }))

  expect(await screen.findByText('Checkout errors blocked customer payments.')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Incident report' })).toBeInTheDocument()
  await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/events'))).toBe(true))
  const terminalCallCount = fetchMock.mock.calls.length

  await act(() => new Promise((resolve) => setTimeout(resolve, 1150)))
  expect(fetchMock).toHaveBeenCalledTimes(terminalCallCount)
})

test('renders retry events as human-readable recovery history', async () => {
  const retryEvent: JobExecutionEvent = {
    id: 4,
    job_id: jobId,
    created_at: '2026-10-05T08:00:04Z',
    event_type: 'RETRY_SCHEDULED',
    stage: 'analyze_service',
    service: 'checkout-api',
    celery_task_id: 'task-1',
    attempt: 1,
    message: 'Transient AI failure; retry scheduled in 1.80s',
    metadata: { countdown_seconds: 1.8, next_attempt: 2 },
  }
  installJobFetch(makeJob('COMPLETED'), [retryEvent])
  const user = userEvent.setup()
  renderApp()
  await user.click(screen.getByRole('button', { name: /run incident analysis/i }))

  expect(await screen.findByText('Retry scheduled')).toBeInTheDocument()
  expect(screen.getByText('Transient AI failure; retry scheduled in 1.80s')).toBeInTheDocument()
  expect(screen.getAllByText('Attempt 1').length).toBeGreaterThan(0)
  expect(screen.getByText('Retried after ~1.8s')).toBeInTheDocument()
})

test('renders an active retry as a pending countdown', async () => {
  const retryEvent: JobExecutionEvent = {
    id: 4,
    job_id: jobId,
    created_at: '2026-10-05T08:00:04Z',
    event_type: 'RETRY_SCHEDULED',
    stage: 'analyze_service',
    service: 'checkout-api',
    celery_task_id: 'task-1',
    attempt: 1,
    message: 'Transient AI failure; retry scheduled in 1.80s',
    metadata: { countdown_seconds: 1.8, next_attempt: 2 },
  }
  installJobFetch(makeJob('PROCESSING', { progress: 40 }), [retryEvent])
  const user = userEvent.setup()
  renderApp()
  await user.click(screen.getByRole('button', { name: /run incident analysis/i }))

  expect(await screen.findByText('Retrying in ~1.8s')).toBeInTheDocument()
})

test('shows a sanitized failed-job state with a restart action', async () => {
  installJobFetch(makeJob('FAILED'))
  const user = userEvent.setup()
  renderApp()
  await user.click(screen.getByRole('button', { name: /run incident analysis/i }))

  expect(await screen.findByRole('heading', { name: 'Analysis failed' })).toBeInTheDocument()
  expect(screen.getByText('analyze_service failed: provider authentication rejected')).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: /run again/i }).length).toBeGreaterThan(0)
})
