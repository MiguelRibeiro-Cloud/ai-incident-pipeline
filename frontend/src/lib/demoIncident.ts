import type { IncidentInput } from '../types/api'

export const DEMO_INCIDENT: IncidentInput = {
  title: 'Customer checkout outage',
  environment: 'production',
  events: [
    { timestamp: '2026-10-05T08:01:12Z', source: 'monitoring', service: 'checkout-api', severity: 'ERROR', message: 'HTTP 503 rate exceeded threshold' },
    { timestamp: '2026-10-05T08:01:47Z', source: 'application', service: 'payment-service', severity: 'ERROR', message: 'Upstream checkout-api unavailable' },
    { timestamp: '2026-10-05T08:02:05Z', source: 'application', service: 'authentication-service', severity: 'WARNING', message: 'Token validation latency exceeded threshold' },
    { timestamp: '2026-10-05T08:02:31Z', source: 'monitoring', service: 'checkout-api', severity: 'ERROR', message: 'Checkout success rate fell below 62 percent' },
    { timestamp: '2026-10-05T08:03:04Z', source: 'application', service: 'payment-service', severity: 'WARNING', message: 'Payment authorization queue depth increasing' },
  ],
}
