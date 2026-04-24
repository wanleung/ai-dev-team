import React, { useState } from 'react'
import { useEmails, useMarkRead } from '../api/hooks'
import EmailList from './EmailList'
import type { EmailQueryParams } from '../types'

const EmailListPage: React.FC = () => {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [queryParams, setQueryParams] = useState<EmailQueryParams>({
    limit: 50,
    offset: 0,
  })

  const { data, isLoading, error } = useEmails(queryParams)
  const markRead = useMarkRead()

  const handleSelect = (id: number) => {
    setSelectedId(id)
  }

  const handleMarkRead = async (id: number) => {
    await markRead.mutateAsync(id)
  }

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    const form = e.target as HTMLFormElement
    const searchInput = form.elements.namedItem('search') as HTMLInputElement
    setQueryParams((prev) => ({ ...prev, search: searchInput.value || undefined, offset: 0 }))
  }

  return (
    <div className="email-list-page">
      <form className="email-search-form" onSubmit={handleSearch}>
        <input
          type="text"
          name="search"
          placeholder="Search by subject or sender..."
        />
        <button type="submit">Search</button>
        <button type="button" onClick={() => {
          setQueryParams({ limit: 50, offset: 0 })
          const form = e => e.preventDefault()
          const input = document.querySelector('input[name="search"]') as HTMLInputElement
          if (input) input.value = ''
        }}>
          Clear
        </button>
      </form>

      {isLoading && <p>Loading emails...</p>}
      {error && <p className="error">Failed to load emails: {error.message}</p>}
      {data && (
        <>
          <p className="email-count">{data.total} email(s) found</p>
          <EmailList
            emails={data.items}
            selectedId={selectedId}
            onSelect={handleSelect}
            onMarkRead={handleMarkRead}
          />
        </>
      )}
    </div>
  )
}

export default EmailListPage
