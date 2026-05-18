import React, { useState } from 'react'
import { useAccounts, useDeleteAccount, useSyncAccount } from '../api/hooks'
import AddAccountForm from './AddAccountForm'

const AccountList: React.FC = () => {
  const { data: accounts, isLoading, error } = useAccounts()
  const deleteAccount = useDeleteAccount()
  const syncAccount = useSyncAccount()
  const [showForm, setShowForm] = useState(false)

  const handleDelete = async (id: number) => {
    if (confirm('Are you sure you want to delete this account?')) {
      await deleteAccount.mutateAsync(id)
    }
  }

  const handleSync = async (id: number) => {
    await syncAccount.mutateAsync({ id })
  }

  if (isLoading) return <p>Loading accounts...</p>
  if (error) return <p className="error">Failed to load accounts: {error.message}</p>

  return (
    <div className="account-list">
      <div className="account-list-header">
        <h2>IMAP Accounts</h2>
        <button onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : 'Add Account'}
        </button>
      </div>

      {showForm && <AddAccountForm onSuccess={() => setShowForm(false)} />}

      {accounts && accounts.length === 0 && (
        <p>No accounts registered yet.</p>
      )}

      {accounts && (
        <ul className="accounts">
          {accounts.map((account) => (
            <li key={account.id} className="account-item">
              <div className="account-info">
                <span className="account-email">{account.email_address}</span>
                <span className="account-host">{account.imap_host}:{account.imap_port}</span>
                <span className={`account-status ${account.is_active ? 'active' : 'inactive'}`}>
                  {account.is_active ? 'Active' : 'Inactive'}
                </span>
              </div>
              <div className="account-actions">
                <button
                  onClick={() => handleSync(account.id)}
                  disabled={syncAccount.isPending && syncAccount.variables?.id === account.id}
                >
                  {syncAccount.isPending && syncAccount.variables?.id === account.id
                    ? 'Syncing...'
                    : 'Sync'}
                </button>
                <button
                  onClick={() => handleDelete(account.id)}
                  disabled={deleteAccount.isPending}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default AccountList
