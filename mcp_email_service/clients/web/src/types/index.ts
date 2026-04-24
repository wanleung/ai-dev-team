export interface Account {
  id: number
  user_id: string
  email_address: string
  imap_host: string
  imap_port: number
  username: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface Attachment {
  id: number
  filename: string
  content_type: string
  size_bytes: number
  storage_path: string
}

export interface Email {
  id: number
  account_id: number
  uid: number
  message_id: string
  subject: string | null
  sender: string
  recipients: string
  date_received: string
  body_text: string | null
  body_html: string | null
  has_attachments: boolean
  is_read: boolean
  created_at: string
  attachments: Attachment[]
}

export interface SyncRequest {
  folders?: string[]
}

export interface SyncResponse {
  status: string
  messages_synced: number
}

export interface EmailQueryParams {
  account_id?: number
  limit?: number
  offset?: number
  search?: string
  is_read?: boolean
  has_attachments?: boolean
}

export interface CreateAccountRequest {
  user_id: string
  email_address: string
  imap_host: string
  imap_port: number
  username: string
  password: string
}
