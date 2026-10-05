import { useState } from 'react'
import { ArchitectureExplainer } from './components/ArchitectureExplainer'
import { ExecutionTimeline } from './components/ExecutionTimeline'
import { IncidentForm } from './components/IncidentForm'
import { IncidentReport } from './components/IncidentReport'
import { PipelineVisualizer } from './components/PipelineVisualizer'
import { useIncidentJob } from './hooks/useIncidentJob'
import { DEMO_INCIDENT } from './lib/demoIncident'
import type { IncidentInput } from './types/api'

function Header() {
  return (
    <header className="site-header">
      <a className="brand" href="#top" aria-label="Pipeline home"><span aria-hidden="true">P/05</span><strong>Incident pipeline</strong></a>
      <nav aria-label="Page navigation"><a href="#demo">Live demo</a><a href="#architecture">Architecture</a></nav>
      <a className="header-cta" href="#demo">Run the pipeline <span aria-hidden="true">↘</span></a>
    </header>
  )
}

function Hero() {
  return (
    <section className="hero" id="top">
      <div className="hero-copy">
        <p className="hero-label"><span /> Distributed incident intelligence</p>
        <h1>AI Incident<br />Processing <em>Pipeline</em></h1>
        <p className="hero-subtitle">A distributed asynchronous pipeline for analyzing operational incidents with Celery, Redis and structured AI.</p>
        <div className="hero-themes"><span>Parallel processing</span><span>Retries</span><span>Worker recovery</span><span>Idempotency</span></div>
      </div>
      <div className="hero-system" aria-label="Technology flow">
        <div className="system-caption"><span>System topology</span><strong>5 components</strong></div>
        <div className="system-flow">
          <div className="system-node system-node--api"><span>Request</span><strong>FastAPI</strong></div>
          <span className="system-connector"><i />queued</span>
          <div className="system-node"><span>Broker</span><strong>Redis</strong></div>
          <span className="system-connector"><i />dispatch</span>
          <div className="system-node system-node--wide"><span>Workers</span><strong>Celery × 3</strong><small>parallel execution</small></div>
          <div className="system-branches" aria-hidden="true"><i /><i /><i /></div>
          <div className="system-bottom"><div><span>Intelligence</span><strong>Gemini</strong></div><div><span>Durable state</span><strong>PostgreSQL</strong></div></div>
        </div>
        <div className="system-footer"><span><i className="pulse-dot" /> Architecture online</span><code>chain → group → chord</code></div>
      </div>
      <div className="hero-stack" aria-label="Technology stack"><span>FASTAPI</span><span>CELERY</span><span>REDIS</span><span>POSTGRESQL</span><span>GEMINI</span></div>
    </section>
  )
}

export default function App() {
  const [jobId, setJobId] = useState<string | null>(null)
  const [chaosEnabled, setChaosEnabled] = useState(false)
  const { createMutation, jobQuery, eventsQuery } = useIncidentJob(jobId)
  const job = jobQuery.data
  const events = eventsQuery.data ?? []
  const isTerminal = job?.status === 'COMPLETED' || job?.status === 'FAILED'

  const submit = () => {
    const payload: IncidentInput = chaosEnabled
      ? { ...DEMO_INCIDENT, chaos: { enabled: true, fail_service: 'checkout-api', fail_attempts: 2 } }
      : DEMO_INCIDENT
    createMutation.mutate(payload, { onSuccess: (created) => setJobId(created.id) })
  }

  const reset = () => {
    setJobId(null)
    setChaosEnabled(false)
    createMutation.reset()
  }

  const error = createMutation.error?.message ?? jobQuery.error?.message ?? eventsQuery.error?.message ?? null
  const report = job?.result?.incident_report ?? null
  const summary = job?.deterministic_summary ?? job?.result?.deterministic_summary ?? null

  return (
    <>
      <Header />
      <main>
        <Hero />
        <div className="demo-shell" id="demo">
          <div className="demo-intro">
            <div><p className="eyebrow">Interactive case study</p><h2>Watch one request become a distributed workflow.</h2></div>
            <p>Submit the prepared incident. Then follow durable state, parallel service tasks, AI requests and retry recovery in real time.</p>
          </div>
          <IncidentForm
            incident={DEMO_INCIDENT}
            chaosEnabled={chaosEnabled}
            isSubmitting={createMutation.isPending}
            isActive={Boolean(jobId)}
            error={error}
            onChaosChange={setChaosEnabled}
            onSubmit={submit}
          />
          {jobId && (
            <div className="active-job-bar" role="status">
              <span><i className={isTerminal ? '' : 'pulse-dot'} aria-hidden="true" /> Job <code>{jobId.slice(0, 8)}</code></span>
              <strong>{job?.status ?? 'QUEUED'}</strong>
              {isTerminal && <button className="text-button" type="button" onClick={reset}>{job?.status === 'FAILED' ? 'Run again' : 'New analysis'} <span aria-hidden="true">↗</span></button>}
            </div>
          )}
          <PipelineVisualizer incident={DEMO_INCIDENT} job={job} events={events} />
          {job?.status === 'FAILED' && (
            <section className="failure-card" role="alert">
              <span aria-hidden="true">×</span><div><p className="eyebrow">Terminal state</p><h2>Analysis failed</h2><p>{job.error || 'The analysis could not be completed.'}</p></div>
              <button className="button button--secondary" type="button" onClick={reset}>Run again</button>
            </section>
          )}
          <div className="timeline-wrap"><ExecutionTimeline events={events} /></div>
          <IncidentReport summary={summary} analyses={job?.service_analyses ?? []} report={report} />
        </div>
        <ArchitectureExplainer />
      </main>
      <footer><div><span>P/05</span><strong>AI Incident Processing Pipeline</strong></div><p>React at the edge. Durable state at the core.</p><a href="#top">Back to top ↑</a></footer>
    </>
  )
}
