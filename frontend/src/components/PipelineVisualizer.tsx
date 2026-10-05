import {
  deriveLinearStageState,
  deriveServiceStates,
  deriveSynthesisState,
  getIncidentServices,
} from '../lib/pipeline'
import type { IncidentInput, JobExecutionEvent, JobResponse, PipelineState } from '../types/api'

interface PipelineVisualizerProps {
  incident: IncidentInput
  job?: JobResponse
  events: JobExecutionEvent[]
}

const stateLabels: Record<PipelineState, string> = {
  waiting: 'Waiting',
  running: 'Running',
  retrying: 'Retrying',
  completed: 'Completed',
  failed: 'Failed',
}

function StatePill({ state }: { state: PipelineState }) {
  return <span className={`state-pill state-pill--${state}`}><i aria-hidden="true" />{stateLabels[state]}</span>
}

function StageCard({
  index,
  title,
  detail,
  state,
}: {
  index: string
  title: string
  detail: string
  state: PipelineState
}) {
  return (
    <div className={`stage-card stage-card--${state}`}>
      <span className="stage-index">{index}</span>
      <div><h3>{title}</h3><p>{detail}</p></div>
      <StatePill state={state} />
    </div>
  )
}

function shortService(service: string) {
  return service.replace('-service', '').replace('-api', '')
}

export function PipelineVisualizer({ incident, job, events }: PipelineVisualizerProps) {
  const services = getIncidentServices(incident, job)
  const serviceStates = deriveServiceStates(
    services,
    events,
    job?.service_analyses.map((analysis) => analysis.service),
  )
  const normalizeState = deriveLinearStageState('normalize_incident', job, events)
  const summarizeState = deriveLinearStageState('summarize_events', job, events)
  const synthesisState = deriveSynthesisState(job, events)
  const isTerminal = job?.status === 'COMPLETED' || job?.status === 'FAILED'

  return (
    <section className="pipeline-section" aria-labelledby="pipeline-title" aria-live="polite">
      <div className="section-heading section-heading--light">
        <div><p className="eyebrow">02 / Live workflow</p><h2 id="pipeline-title">Follow the work, not just a spinner</h2></div>
        <div className="pipeline-status">
          <span className={`live-dot ${job && !['COMPLETED', 'FAILED'].includes(job.status) ? 'live-dot--active' : ''}`} aria-hidden="true" />
          {job ? `${job.status} · ${job.progress}%` : 'Ready to submit'}
        </div>
      </div>

      <div className="pipeline-progress" aria-label={`Job progress ${job?.progress ?? 0}%`}>
        <span style={{ width: `${job?.progress ?? 0}%` }} />
      </div>

      <div className="pipeline-canvas">
        <div className="linear-stages">
          <StageCard index="01" title="Normalize" detail="Validate and order events" state={normalizeState} />
          <span className="flow-arrow" aria-hidden="true">→</span>
          <StageCard index="02" title="Summarize" detail="Deterministic signal pass" state={summarizeState} />
        </div>

        <div className="flow-down" aria-hidden="true"><span>Redis queue</span><i>↓</i></div>

        <div className="fanout-shell">
          <div className="fanout-title">
            <span>Celery group</span>
            <strong>Parallel service analysis</strong>
            <small>{services.length} independent tasks</small>
          </div>
          <div className="service-grid" style={{ '--service-count': services.length } as React.CSSProperties}>
            {serviceStates.map((item) => (
              <article className={`service-node service-node--${item.state}`} key={item.service}>
                <div className="service-node__top">
                  <span className="service-glyph" aria-hidden="true">{shortService(item.service).slice(0, 2).toUpperCase()}</span>
                  <StatePill state={item.state} />
                </div>
                <h3>{item.service}</h3>
                <p className="gemini-line"><span aria-hidden="true">◆</span> Gemini analysis</p>
                {item.attempts.length > 0 ? (
                  <ol className="attempt-list" aria-label={`${item.service} attempts`}>
                    {item.attempts.map((attempt) => (
                      <li key={attempt.attempt} className={`attempt attempt--${attempt.outcome}`}>
                        <span>Attempt {attempt.attempt}</span>
                        <strong>{attempt.outcome === 'retrying' && attempt.retryDelay
                          ? `${isTerminal ? 'Retried after' : 'Retrying in'} ~${attempt.retryDelay.toFixed(1)}s`
                          : attempt.outcome}</strong>
                      </li>
                    ))}
                  </ol>
                ) : <p className="awaiting-copy">{item.state === 'completed' ? 'Result persisted' : item.state === 'running' ? 'Worker active' : 'Awaiting fan-out'}</p>}
              </article>
            ))}
          </div>
        </div>

        <div className="chord-gate">
          <span className="chord-line" aria-hidden="true" />
          <div><span>Celery chord</span><strong>Waits for every branch</strong></div>
          <span className="chord-line" aria-hidden="true" />
        </div>

        <div className="synthesis-wrap">
          <StageCard index="04" title="Final synthesis" detail="One coherent incident report" state={synthesisState} />
          <span className="postgres-note"><i aria-hidden="true" /> PostgreSQL stores durable state</span>
        </div>
      </div>
    </section>
  )
}
