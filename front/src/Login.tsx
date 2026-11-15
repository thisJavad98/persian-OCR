import { useEffect, useRef, useState, type FormEvent } from 'react'
import { login } from './api'
import './Login.css'

type Props = {
  onSuccess: () => void
}

export default function Login({ onSuccess }: Props) {
  const userRef = useRef<HTMLInputElement>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPass, setShowPass] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia('(min-width: 600px)')
    const focus = () => {
      if (mq.matches) userRef.current?.focus()
    }
    focus()
    mq.addEventListener('change', focus)
    return () => mq.removeEventListener('change', focus)
  }, [])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setPending(true)
    try {
      await login(username.trim(), password)
      onSuccess()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ورود ناموفق بود.')
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="login" lang="fa" dir="rtl">
      <div className="login-layout">
        <figure className="login-exhibit" aria-hidden="true">
          <img
            src="/login-calligraphy.jpg"
            alt=""
            width={1200}
            height={1834}
            loading="eager"
            decoding="async"
          />
        </figure>

        <main className="login-main">
          <div className="login-stage login-enter">
            <header className="login-intro">
              <h1 className="login-title">
                <span className="login-title-accent">خ</span>ط ‌خوان
              </h1>
              <p className="login-lede">
                ورود فقط برای کاربر مجاز. پس از آن تصویر را بفرستید و متن را همان‌طور که روی صفحه
                است ببینید.
              </p>
            </header>

            <form
              className="login-form login-enter login-enter--delay"
              onSubmit={onSubmit}
              data-ui="login"
              aria-busy={pending}
            >
              <h2 className="login-form-title">ورود به سامانه</h2>

              {error && (
                <p className="login-error" role="alert">
                  {error}
                </p>
              )}

              <label className="login-field">
                <span className="login-label">نام کاربری</span>
                <input
                  ref={userRef}
                  name="username"
                  type="text"
                  inputMode="text"
                  autoComplete="username"
                  autoCapitalize="off"
                  spellCheck={false}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  disabled={pending}
                  aria-invalid={error ? true : undefined}
                />
              </label>

              <label className="login-field">
                <span className="login-label">رمز عبور</span>
                <div className="login-pass-row">
                  <input
                    name="password"
                    type={showPass ? 'text' : 'password'}
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    disabled={pending}
                    aria-invalid={error ? true : undefined}
                  />
                  <button
                    type="button"
                    className="login-show"
                    onClick={() => setShowPass((v) => !v)}
                    aria-pressed={showPass}
                    aria-label={showPass ? 'پنهان کردن رمز' : 'نمایش رمز'}
                  >
                    {showPass ? 'پنهان' : 'نمایش'}
                  </button>
                </div>
              </label>

              <button type="submit" className="login-submit" disabled={pending}>
                {pending ? 'در حال ورود…' : 'ادامه'}
              </button>
            </form>
          </div>
        </main>
      </div>

      <footer className="login-foot">
        <p>
          تصویر: «برگی از نسخهٔ خطی»، موزهٔ متروپولیتن نیویورک،{' '}
          <a
            href="https://www.metmuseum.org/art/collection/search/446169"
            rel="noreferrer"
            target="_blank"
          >
            CC0
          </a>
        </p>
      </footer>
    </div>
  )
}