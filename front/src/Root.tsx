import { useCallback, useEffect, useState, type ReactNode } from 'react'
import App from './App'
import Login from './Login'
import SiteFooter from './SiteFooter'
import { checkSession, logout } from './api'

function Shell({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <SiteFooter />
    </>
  )
}

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
      <Shell>
        <div className="gate-loading" lang="fa" dir="rtl">
          <p>در حال بررسی ورود…</p>
        </div>
      </Shell>
    )
  }

  if (gate === 'guest') {
    return (
      <Shell>
        <Login onSuccess={() => setGate('user')} />
      </Shell>
    )
  }

  return (
    <Shell>
      <App
        onLogout={async () => {
          await logout()
          setGate('guest')
        }}
      />
    </Shell>
  )
}