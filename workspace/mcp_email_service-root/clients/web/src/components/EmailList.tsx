import React from 'react'
import type { Email } from '../types'

interface EmailListProps {
  emails: Email[]
  selectedId: number | null
  onSelect: (id: number) => void
  onMarkRead: (id: number) => void
}

const EmailList: React.FC<EmailListProps> = ({
  emails,
  selectedId,
  onSelect,
  onMarkRead,
}) => {
  if (emails.length === 0) {
    return <div className="email-list-empty">No emails found.</div>
  }

  return (
    <ul className="email-list">
      {emails.map((email) => (
        <li
          key={email.id}
          className={`email-list-item ${email.id === selectedId ? 'selected' : ''} ${!email.is_read ? 'unread' : ''}`}
          onClick={() => onSelect(email.id)}
        >
          <div className="email-list-header">
            <span className="email-sender">{email.sender}</span>
            <span className="email-date">
              {new Date(email.date_received).toLocaleDateString()}
            </span>
          </div>
          <div className="email-subject">
            {email.subject || '(No subject)'}
          </div>
          <div className="email-actions">
            {!email.is_read && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onMarkRead(email.id)
                }}
              >
                Mark read
              </button>
            )}
            {email.has_attachments && (
              <span className="attachment-badge">Attachments</span>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}

export default EmailList
