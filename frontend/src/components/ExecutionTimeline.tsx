import type { JobExecutionEvent } from '../types/api'

interface ExecutionTimelineProps {
  events: JobExecutionEvent[]
}

const labels: Record<JobExecutionEvent['event_type'], string> = {
  WORKFLOW_STARTED: 'Workflow accepted',
  TASK_STARTED: 'Task started',
  AI_REQUEST_STARTED: 'AI request',
  CHAOS_FAILURE_INJECTED: 'Simulated failure',
  CHAOS_DELAY_INJECTED: 'Demo delay',
  RETRY_SCHEDULED: 'Retry scheduled',
  TASK_SUCCEEDED: 'Task completed',
  TASK_FAILED: 'Task failed',
  TASK_REDELIVERED: 'Task redelivered',
  SYNTHESIS_STARTED: 'Synthesis started',
  JOB_COMPLETED: 'Analysis completed',
  JOB_FAILED: 'Analysis failed',
}

function formatTime(timestamp: string) {
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3,
  }).format(new Date(timestamp))
}

function Metadata({ event }: { event: JobExecutionEvent }) {
  const entries = Object.entries({
    stage: event.stage,
    service: event.service,
    attempt: event.attempt,
    task: event.celery_task_id,
    ...event.metadata,
  }).filter(([, value]) => value !== null && value !== undefined)
  if (!entries.length) return null
  return (
    <details className="event-details">
      <summary>Technical metadata</summary>
      <dl>{entries.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl>
    </details>
  )
}

export function ExecutionTimeline({ events }: ExecutionTimelineProps) {
  return (
    <section className="timeline-panel" aria-labelledby="timeline-title">
      <div className="timeline-heading">
        <div><p className="eyebrow">03 / Durable history</p><h2 id="timeline-title">Execution timeline</h2></div>
        <span>{events.length} {events.length === 1 ? 'event' : 'events'}</span>
      </div>
      {events.length === 0 ? (
        <div className="timeline-empty"><span aria-hidden="true">↳</span><p>Execution events will appear here as workers make progress.</p></div>
      ) : (
        <ol className="timeline-list">
          {events.map((event) => (
            <li className={`timeline-event timeline-event--${event.event_type.toLowerCase()}`} key={event.id}>
              <time dateTime={event.created_at}>{formatTime(event.created_at)}</time>
              <span className="timeline-marker" aria-hidden="true" />
              <div className="timeline-copy">
                <div><strong>{labels[event.event_type]}</strong>{event.service && <span>{event.service}</span>}{event.attempt && <span>Attempt {event.attempt}</span>}</div>
                <p>{event.message}</p>
                <Metadata event={event} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
