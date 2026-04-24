import React from 'react'
import type { Email } from '../types'
import { downloadAttachment } from '../api/client'

interface EmailDetailProps {
  email: Email | undefined
  isLoading: boolean
}

const EmailDetail: React.FC<EmailDetailProps> = ({ email, isLoading }) => {
  if (isLoading) {
    return <div className="email-detail-loading">Loading...</div>
  }

  if (!email) {
    return <div className="email-detail-empty">Select an email to view.</div>
  }

  const handleDownload = async (attachmentId: number, filename: string) => {
    try {
      const blob = await downloadAttachment(email.id, attachmentId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Failed to download attachment:', err)
    }
  }

  return (
    <div className="email-detail">
      <div className="email-detail-header">
        <h2>{email.subject || '(No subject)'}</h2>
        <div className="email-meta">
          <span><strong>From:</strong> {email.sender}</span>
          <span><strong>To:</strong> {email.recipients}</span>
          <span><strong>Date:</strong> {new Date(email.date_received).toLocaleString()}</span>
        </div>
      </div>

      {email.has_attachments && email.attachments.length > 0 && (
        <div className="email-attachments">
          <h3>Attachments</h3>
          <ul>
            {email.attachments.map((att) => (
              <li key={att.id}>
                <span>{att.filename} ({(att.size_bytes / 1024).toFixed(1)} KB)</span>
                <button onClick={() => handleDownload(att.id, att.filename)}>
                  Download
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="email-body">
        {email.body_html ? (
          <div
            className="email-body-html"
            dangerouslySetInnerHTML={{ __html: email.body_html }}
          />
        ) : (
          <pre className="email-body-text">{email.body_text}</pre>
        )}
      </div>
    </div>
  )
}

export default EmailDetail
