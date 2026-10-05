import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createJob, getJob, getJobEvents } from '../api/client'
import type { IncidentInput, JobResponse } from '../types/api'

export const POLL_INTERVAL_MS = 1000

function isTerminal(job?: JobResponse): boolean {
  return job?.status === 'COMPLETED' || job?.status === 'FAILED'
}

export function useIncidentJob(jobId: string | null) {
  const queryClient = useQueryClient()
  const createMutation = useMutation({
    mutationFn: (incident: IncidentInput) => createJob(incident),
    onSuccess: (job) => queryClient.setQueryData(['job', job.id], job),
  })

  const jobQuery = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => getJob(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) => (isTerminal(query.state.data) ? false : POLL_INTERVAL_MS),
  })

  const eventsQuery = useQuery({
    queryKey: ['job-events', jobId],
    queryFn: () => getJobEvents(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: () => (isTerminal(jobQuery.data) ? false : POLL_INTERVAL_MS),
  })

  return { createMutation, jobQuery, eventsQuery }
}
