import React, { useState } from 'react'
import { useEmails, useMarkRead } from '../api/hooks'
import EmailList from './EmailList'
import EmailDetail from './EmailDetail'
import type { EmailQueryParams } from '../types'

const EmailView: React.FC = () => {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [queryParams, setQueryParams] = useState<EmailQueryParams>({
    limit: 50,
    offset: 0,
  })

  const { data, isLoading, error } = useEmails(queryParams)
  const markRead = useMarkRead()
  const { data: selectedEmail, isLoading: isLoadingDetail } = useEmail(selectedId ?? 0)

  const handleSelect = async (id: number) => {
    setSelectedId(id)
    if (!data?.items.find((e) => e.id === id)?.is_read) {
      await markRead.mutateAsync(id)
    }
  }

  const handleMarkRead = async (id: number) => {
    await markRead.mutateAsync(id)
  }

  const handleSearch = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const form = e.currentTarget
    const searchInput = form.elements.namedItem('search') as HTMLInputElement
    setQueryParams((prev) => ({ ...prev, search: searchInput.value || undefined, offset: 0 }))
  }

  return (
    <div className="email-view">
      <div className="email-view-sidebar">
        <form className="email-search-form" onSubmit={handleSearch}>
          <input
            type="text"
            name="search"
            placeholder="Search by subject or sender..."
          />
          <button type="submit">Search</button>
        </form>

        {isLoading && <p>Loading emails...</p>}
        {error && <p className="error">Failed to load emails: {error.message}</p>}
        {data && (
          <EmailList
            emails={data.items}
            selectedId={selectedId}
            onSelect={handleSelect}
            onMarkRead={handleMarkRead}
          />
        )}
      </div>

      <div className="email-view-content">
        <EmailDetail email={selectedEmail} isLoading={isLoadingDetail} />
      </div>
    </div>
  )
}

export default EmailView
