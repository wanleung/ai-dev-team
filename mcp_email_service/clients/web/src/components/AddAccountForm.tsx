import React, { useState } from 'react'
import { useCreateAccount } from '../api/hooks'
import type { CreateAccountRequest } from '../types'

interface AddAccountFormProps {
  onSuccess: () => void
}

const AddAccountForm: React.FC<AddAccountFormProps> = ({ onSuccess }) => {
  const createAccount = useCreateAccount()
  const [formData, setFormData] = useState<CreateAccountRequest>({
    user_id: 'default',
    email_address: '',
    imap_host: '',
    imap_port: 993,
    username: '',
    password: '',
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    await createAccount.mutateAsync(formData)
    setFormData({
      user_id: 'default',
      email_address: '',
      imap_host: '',
      imap_port: 993,
      username: '',
      password: '',
    })
    onSuccess()
  }

  return (
    <form className="add-account-form" onSubmit={handleSubmit}>
      <h3>Add IMAP Account</h3>
      <div className="form-group">
        <label>Email Address</label>
        <input
          type="email"
          value={formData.email_address}
          onChange={(e) => setFormData({ ...formData, email_address: e.target.value })}
          required
        />
      </div>
      <div className="form-group">
        <label>IMAP Host</label>
        <input
          type="text"
          value={formData.imap_host}
          onChange={(e) => setFormData({ ...formData, imap_host: e.target.value })}
          required
        />
      </div>
      <div className="form-group">
        <label>IMAP Port</label>
        <input
          type="number"
          value={formData.imap_port}
          onChange={(e) => setFormData({ ...formData, imap_port: parseInt(e.target.value) || 993 })}
          min={1}
          max={65535}
          required
        />
      </div>
      <div className="form-group">
        <label>Username</label>
        <input
          type="text"
          value={formData.username}
          onChange={(e) => setFormData({ ...formData, username: e.target.value })}
          required
        />
      </div>
      <div className="form-group">
        <label>Password</label>
        <input
          type="password"
          value={formData.password}
          onChange={(e) => setFormData({ ...formData, password: e.target.value })}
          required
        />
      </div>
      <button type="submit" disabled={createAccount.isPending}>
        {createAccount.isPending ? 'Adding...' : 'Add Account'}
      </button>
      {createAccount.isError && (
        <p className="form-error">Failed to add account: {createAccount.error.message}</p>
      )}
    </form>
  )
}

export default AddAccountForm
