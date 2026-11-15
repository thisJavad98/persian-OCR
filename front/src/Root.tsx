import { useCallback, useEffect, useState } from 'react'
import App from './App'
import Login from './Login'
import { checkSession, logout } from './api'

type Gate = 'loading' | 'guest' | 'user'

export default function Root() {
  const [gate, setGate] = useState<Gate>('loading')

  const refresh = useCallback(async () => {
    const ok = await checkSession()
    setGate(ok ? 'user' : 'guest')
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  if (gate === 'loading') {
    return (
      <div className="gate-loading" lang="fa" dir="rtl">
        <p>در حال بررسی ورود…</p>
      </div>
    )
  }

  if (gate === 'guest') {
    return <Login onSuccess={() => setGate('user')} />
  }

  return (
    <App
      onLogout={async () => {
        await logout()
        setGate('guest')
      }}
    />
  )
}