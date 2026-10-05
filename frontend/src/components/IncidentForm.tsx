import type { IncidentInput } from '../types/api'

interface IncidentFormProps {
  incident: IncidentInput
  chaosEnabled: boolean
  isSubmitting: boolean
  isActive: boolean
  error: string | null
  onChaosChange: (enabled: boolean) => void
  onSubmit: () => void
}

export function IncidentForm({
  incident,
  chaosEnabled,
  isSubmitting,
  isActive,
  error,
  onChaosChange,
  onSubmit,
}: IncidentFormProps) {
  const services = new Set(incident.events.map((event) => event.service))

  return (
    <section className="incident-panel" aria-labelledby="incident-title">
      <div className="incident-panel__top">
        <div>
          <p className="eyebrow">01 / Input</p>
          <h2 id="incident-title">A real incident shape, ready to run</h2>
        </div>
        <span className="sample-label">Synthetic data</span>
      </div>

      <div className="incident-card">
        <div className="incident-summary">
          <div className="incident-mark" aria-hidden="true">!</div>
          <div>
            <p className="incident-summary__title">{incident.title}</p>
            <p className="muted">A multi-service production degradation</p>
          </div>
        </div>
        <dl className="incident-stats" aria-label="Incident summary">
          <div><dt>Environment</dt><dd>{incident.environment}</dd></div>
          <div><dt>Events</dt><dd>{incident.events.length}</dd></div>
          <div><dt>Services</dt><dd>{services.size}</dd></div>
        </dl>
      </div>

      <details className="event-payload">
        <summary>Inspect event payload <span>JSON-free view</span></summary>
        <div className="event-table-wrap">
          <table className="event-table">
            <thead><tr><th>Time</th><th>Service</th><th>Level</th><th>Observation</th></tr></thead>
            <tbody>
              {incident.events.map((event) => (
                <tr key={`${event.timestamp}-${event.service}`}>
                  <td>{new Date(event.timestamp).toISOString().slice(11, 19)}</td>
                  <td>{event.service}</td>
                  <td><span className={`severity severity--${event.severity.toLowerCase()}`}>{event.severity}</span></td>
                  <td>{event.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <div className="run-controls">
        <label className={`chaos-control ${chaosEnabled ? 'chaos-control--active' : ''}`}>
          <span className="switch">
            <input
              type="checkbox"
              checked={chaosEnabled}
              disabled={isActive}
              onChange={(event) => onChaosChange(event.target.checked)}
            />
            <span aria-hidden="true" />
          </span>
          <span>
            <strong>Chaos Demo</strong>
            <small>Simulates temporary provider failures so Celery retry behavior can be observed.</small>
          </span>
        </label>
        <button className="button button--primary" type="button" disabled={isActive || isSubmitting} onClick={onSubmit}>
          {isSubmitting ? 'Creating job…' : 'Run incident analysis'}
          <span aria-hidden="true">→</span>
        </button>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
  )
}
