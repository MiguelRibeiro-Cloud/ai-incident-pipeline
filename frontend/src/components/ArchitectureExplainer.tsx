const architecture = [
  { code: '01', name: 'FastAPI', detail: 'Accepts the request and creates a durable job.' },
  { code: '02', name: 'Redis', detail: 'Carries queued Celery messages between processes.' },
  { code: '03', name: 'Celery', detail: 'Runs deterministic work outside the API lifecycle.' },
  { code: '04', name: 'Group', detail: 'Fans service analyses out in parallel.' },
  { code: '05', name: 'Gemini', detail: 'Returns schema-constrained service intelligence.' },
  { code: '06', name: 'Chord', detail: 'Waits for every branch before final synthesis.' },
  { code: '07', name: 'PostgreSQL', detail: 'Remains the durable source of truth.' },
]

const reliability = [
  { title: 'Retry', icon: '↻', text: 'Transient provider failures trigger exponential backoff with jitter.' },
  { title: 'Late acknowledgement', icon: '✓', text: 'Long-running tasks acknowledge only after successful execution.' },
  { title: 'Redelivery', icon: '⇢', text: 'A lost worker can leave work available for another worker to receive.' },
  { title: 'Idempotency', icon: '≡', text: 'Unique constraints and terminal guards keep repeated execution safe.' },
]

export function ArchitectureExplainer() {
  return (
    <>
      <section className="architecture-section" id="architecture" aria-labelledby="architecture-title">
        <div className="architecture-intro">
          <p className="eyebrow">05 / Under the hood</p>
          <h2 id="architecture-title">An API that stays responsive while the hard work moves elsewhere.</h2>
          <p>The browser polls durable state. It never needs a direct connection to a worker or the broker.</p>
        </div>
        <ol className="architecture-flow">
          {architecture.map((item, index) => (
            <li key={item.name}>
              <span className="architecture-code">{item.code}</span>
              <div><h3>{item.name}</h3><p>{item.detail}</p></div>
              {index < architecture.length - 1 && <span className="architecture-arrow" aria-hidden="true">→</span>}
            </li>
          ))}
        </ol>
        <div className="browser-note"><span>Browser / React</span><i aria-hidden="true">⇄</i><strong>Polls FastAPI every second</strong></div>
      </section>

      <section className="reliability-section" aria-labelledby="reliability-title">
        <div className="reliability-heading">
          <div><p className="eyebrow">06 / Failure is a design input</p><h2 id="reliability-title">Recovery you can see.</h2></div>
          <p><strong>At-least-once execution semantics</strong> means a task may run again after failure. The system protects durable state instead of pretending every task runs exactly once.</p>
        </div>
        <div className="reliability-grid">
          {reliability.map((item) => <article key={item.title}><span aria-hidden="true">{item.icon}</span><h3>{item.title}</h3><p>{item.text}</p></article>)}
        </div>
      </section>

      <section className="technical-signal" aria-label="Engineering capabilities">
        <div><span>Built to demonstrate</span><h2>Distributed systems, with the seams left visible.</h2></div>
        <ul>
          <li>Async job processing</li><li>Fan-out / fan-in orchestration</li>
          <li>Structured LLM output</li><li>Retry and backoff</li>
          <li>Worker-loss recovery</li><li>Idempotent state changes</li>
          <li>Durable execution history</li><li>API / frontend separation</li>
        </ul>
      </section>
    </>
  )
}
