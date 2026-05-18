import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as api from './client'
import type { EmailQueryParams, SyncRequest, CreateAccountRequest } from '../types'

export function useAccounts() {
  return useQuery({
    queryKey: ['accounts'],
    queryFn: api.getAccounts,
  })
}

export function useCreateAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.createAccount,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
    },
  })
}

export function useDeleteAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.deleteAccount,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
    },
  })
}

export function useSyncAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data?: SyncRequest }) =>
      api.syncAccount(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['emails'] })
    },
  })
}

export function useEmails(params: EmailQueryParams = {}) {
  return useQuery({
    queryKey: ['emails', params],
    queryFn: () => api.getEmails(params),
  })
}

export function useEmail(id: number) {
  return useQuery({
    queryKey: ['email', id],
    queryFn: () => api.getEmail(id),
    enabled: id > 0,
  })
}

export function useMarkRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.markEmailRead,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['emails'] })
      queryClient.setQueryData(['email', data.id], data)
    },
  })
}
