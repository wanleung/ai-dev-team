import type {
  Account,
  Email,
  EmailQueryParams,
  SyncRequest,
  SyncResponse,
  CreateAccountRequest,
} from '../types'

const API_BASE = '/api'

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const body = await response.text()
    throw new Error(`API Error ${response.status}: ${body}`)
  }

  return response.json()
}

export async function getAccounts(): Promise<Account[]> {
  const res = await request<{ items: Account[]; total: number }>('/accounts')
  return res.items
}

export async function createAccount(
  data: CreateAccountRequest,
): Promise<Account> {
  return request('/accounts', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function getAccount(id: number): Promise<Account> {
  return request(`/accounts/${id}`)
}

export async function deleteAccount(id: number): Promise<void> {
  await request(`/accounts/${id}`, { method: 'DELETE' })
}

export async function syncAccount(
  id: number,
  data?: SyncRequest,
): Promise<SyncResponse> {
  return request(`/accounts/${id}/sync`, {
    method: 'POST',
    body: JSON.stringify(data ?? {}),
  })
}

export async function getEmails(
  params: EmailQueryParams = {},
): Promise<{ items: Email[]; total: number }> {
  const query = new URLSearchParams()
  if (params.account_id) query.set('account_id', String(params.account_id))
  if (params.limit) query.set('limit', String(params.limit))
  if (params.offset) query.set('offset', String(params.offset))
  if (params.search) query.set('search', params.search)
  if (params.is_read !== undefined) query.set('is_read', String(params.is_read))
  if (params.has_attachments !== undefined)
    query.set('has_attachments', String(params.has_attachments))

  const qs = query.toString()
  return request(`/emails${qs ? `?${qs}` : ''}`)
}

export async function getEmail(id: number): Promise<Email> {
  return request(`/emails/${id}`)
}

export async function markEmailRead(id: number): Promise<Email> {
  return request(`/emails/${id}/read`, {
    method: 'PATCH',
  })
}

export async function downloadAttachment(
  emailId: number,
  attachmentId: number,
): Promise<Blob> {
  const response = await fetch(
    `${API_BASE}/emails/${emailId}/attachments/${attachmentId}/download`,
  )
  if (!response.ok) {
    const body = await response.text()
    throw new Error(`API Error ${response.status}: ${body}`)
  }
  return response.blob()
}
