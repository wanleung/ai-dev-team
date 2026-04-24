import React, { useState } from 'react'
import AccountList from './components/AccountList'
import EmailView from './components/EmailView'

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'emails' | 'accounts'>('emails')

  return (
    <div className="app">
      <header className="app-header">
        <h1>MCP Email Service</h1>
        <nav>
          <button
            className={activeTab === 'emails' ? 'active' : ''}
            onClick={() => setActiveTab('emails')}
          >
            Emails
          </button>
          <button
            className={activeTab === 'accounts' ? 'active' : ''}
            onClick={() => setActiveTab('accounts')}
          >
            Accounts
          </button>
        </nav>
      </header>

      <main className="app-main">
        {activeTab === 'emails' && <EmailView />}
        {activeTab === 'accounts' && <AccountList />}
      </main>
    </div>
  )
}

export default App
