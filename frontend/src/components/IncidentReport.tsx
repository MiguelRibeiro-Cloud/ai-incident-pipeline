import type { DeterministicSummary, IncidentReportData, ServiceAnalysis } from '../types/api'

function Confidence({ value }: { value: number }) {
  const percent = Math.round(value * 100)
  return (
    <div className="confidence" aria-label={`Model confidence ${percent} percent`}>
      <div><span>Model confidence</span><strong>{percent}%</strong></div>
      <div className="confidence-track"><span style={{ width: `${percent}%` }} /></div>
      <small>Directional model assessment, not mathematical certainty.</small>
    </div>
  )
}

function DeterministicSummaryCard({ summary }: { summary: DeterministicSummary }) {
  return (
    <article className="deterministic-card">
      <div className="report-kicker"><span>Deterministic</span><i>Computed without AI</i></div>
      <h3>Incident signal summary</h3>
      <div className="summary-metrics">
        <div><strong>{summary.event_count}</strong><span>events</span></div>
        <div><strong>{summary.error_event_count}</strong><span>errors</span></div>
        <div><strong>{summary.services.length}</strong><span>services</span></div>
      </div>
      <p className="summary-window">
        {new Date(summary.earliest_timestamp).toLocaleTimeString()} — {new Date(summary.latest_timestamp).toLocaleTimeString()}
      </p>
      <div className="service-tags">{summary.services.map((service) => <span key={service}>{service}</span>)}</div>
    </article>
  )
}

function ServiceAnalysisCard({ analysis }: { analysis: ServiceAnalysis }) {
  return (
    <article className="analysis-card">
      <div className="analysis-card__head">
        <div><span className="report-kicker">Service analysis</span><h3>{analysis.service}</h3></div>
        <span className="confidence-number">{Math.round(analysis.confidence * 100)}% <small>confidence</small></span>
      </div>
      <p className="analysis-summary">{analysis.summary}</p>
      <div className="evidence-inference">
        <div className="evidence-block">
          <h4><span aria-hidden="true">●</span> Observed evidence</h4>
          {analysis.evidence.length ? (
            <ul>{analysis.evidence.map((item) => <li key={`${item.timestamp}-${item.observation}`}><time>{item.timestamp}</time>{item.observation}</li>)}</ul>
          ) : <p>No direct evidence was cited.</p>}
        </div>
        <div className="inference-block">
          <h4><span aria-hidden="true">◇</span> AI inference</h4>
          <p>{analysis.probable_cause}</p>
        </div>
      </div>
      <details className="recommended-checks">
        <summary>Recommended checks <span>{analysis.recommended_checks.length}</span></summary>
        <ul>{analysis.recommended_checks.map((check) => <li key={check}>{check}</li>)}</ul>
      </details>
    </article>
  )
}

function FinalReport({ report }: { report: IncidentReportData }) {
  return (
    <article className="final-report">
      <div className="final-report__head">
        <div><p className="eyebrow">Final intelligence</p><h3>Incident report</h3></div>
        <span className="report-ready"><i aria-hidden="true" /> Ready for review</span>
      </div>
      <p className="executive-summary">{report.executive_summary}</p>
      <Confidence value={report.confidence} />
      <div className="report-grid">
        <section><span className="field-label">Probable root cause</span><p>{report.probable_root_cause}</p></section>
        <section><span className="field-label">Impact</span><p>{report.impact}</p></section>
        <section className="report-grid__wide"><span className="field-label">Timeline synthesis</span><p>{report.timeline_summary}</p></section>
        <section><span className="field-label">Supporting evidence</span><ul>{report.supporting_evidence.map((item) => <li key={item}>{item}</li>)}</ul></section>
        <section><span className="field-label">Recommended actions</span><ol>{report.recommended_actions.map((item) => <li key={item}>{item}</li>)}</ol></section>
      </div>
      <div className="affected-row"><span>Affected services</span>{report.affected_services.map((service) => <strong key={service}>{service}</strong>)}</div>
    </article>
  )
}

interface IncidentReportProps {
  summary: DeterministicSummary | null
  analyses: ServiceAnalysis[]
  report: IncidentReportData | null
}

export function IncidentReport({ summary, analyses, report }: IncidentReportProps) {
  if (!summary && !analyses.length && !report) {
    return (
      <section className="results-section results-section--empty" aria-labelledby="results-title">
        <div className="section-heading"><div><p className="eyebrow">04 / Intelligence</p><h2 id="results-title">Evidence first. Inference second.</h2></div></div>
        <div className="results-empty"><span aria-hidden="true">04</span><p>The deterministic summary and structured AI report will appear here as the pipeline completes.</p></div>
      </section>
    )
  }

  return (
    <section className="results-section" aria-labelledby="results-title">
      <div className="section-heading">
        <div><p className="eyebrow">04 / Intelligence</p><h2 id="results-title">Evidence first. Inference second.</h2></div>
        <p>Each model conclusion stays visually separate from the observations that support it.</p>
      </div>
      {summary && <DeterministicSummaryCard summary={summary} />}
      {analyses.length > 0 && (
        <div className="service-analyses">
          <div className="subheading"><span>Parallel outputs</span><h3>Service-by-service analysis</h3></div>
          <div className="analysis-grid">{analyses.map((analysis) => <ServiceAnalysisCard key={analysis.service} analysis={analysis} />)}</div>
        </div>
      )}
      {report && <FinalReport report={report} />}
    </section>
  )
}
