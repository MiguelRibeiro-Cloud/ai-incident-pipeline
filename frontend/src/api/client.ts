import type { IncidentInput, JobExecutionEvent, JobResponse } from '../types/api'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body = (await response.json()) as { detail?: string | Array<{ msg: string }> }
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((item) => item.msg).join(', ')
    } catch {
      // Keep the safe status-based fallback when the response is not JSON.
    }
    throw new ApiError(message, response.status)
  }

  return response.json() as Promise<T>
}

export function createJob(incident: IncidentInput): Promise<JobResponse> {
  return request('/api/v1/jobs', { method: 'POST', body: JSON.stringify(incident) })
}

export function getJob(jobId: string): Promise<JobResponse> {
  return request(`/api/v1/jobs/${jobId}`)
}

export function getJobEvents(jobId: string): Promise<JobExecutionEvent[]> {
  return request(`/api/v1/jobs/${jobId}/events`)
}
