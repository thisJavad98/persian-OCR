import {
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from 'react'
import { excelUrl, uploadImage, wordUrl, type OcrJob } from './api'
import './App.css'

type UiState = 'idle' | 'uploading' | 'ready' | 'error'

function confidenceLabel(value: number | null | undefined): string {
  if (value == null) return '—'
  return `${Math.round(value * 100)}٪`
}

function App() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [job, setJob] = useState<OcrJob | null>(null)
  const [uiState, setUiState] = useState<UiState>('idle')
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)

  async function processFile(file: File) {
    if (!file.type.startsWith('image/')) {
      setError('فقط فایل تصویری بفرستید.')
      setUiState('error')
      return
    }

    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setPreviewUrl(URL.createObjectURL(file))
    setJob(null)
    setError(null)
    setUiState('uploading')

    try {
      const result = await uploadImage(file)
      setJob(result)
      if (result.status === 'failed') {
        setError(result.error_message || 'استخراج متن ناموفق بود.')
        setUiState('error')
        return
      }
      setUiState('ready')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطای ناشناخته')
      setUiState('error')
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) void processFile(file)
    event.target.value = ''
  }

  function onDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault()
    setDragOver(false)
    const file = event.dataTransfer.files?.[0]
    if (file) void processFile(file)
  }

  const words = (job?.words || []).filter((word) => Boolean((word.text || '').trim()))
  const sentences = (job?.sentences || []).filter((s) => Boolean(s.trim()))

  return (
    <div className="frame" data-ui="app">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            خ
          </span>
          <div>
            <p className="brand-name">خط‌خوان</p>
            <p className="brand-sub">استخراج دقیق متن با AI از هر تصویر</p>
          </div>
        </div>
        <div className="top-actions">
          <button
            type="button"
            className="btn ghost"
            onClick={() => inputRef.current?.click()}
            disabled={uiState === 'uploading'}
          >
            انتخاب تصویر
          </button>
          <a
            className={`btn ghost ${job?.status === 'completed' ? '' : 'is-disabled'}`}
            href={job?.status === 'completed' ? wordUrl(job.id) : undefined}
            aria-disabled={job?.status !== 'completed'}
            onClick={(event) => {
              if (job?.status !== 'completed') event.preventDefault()
            }}
          >
            دانلود ورد
          </a>
          <a
            className={`btn primary ${job?.status === 'completed' ? '' : 'is-disabled'}`}
            href={job?.status === 'completed' ? excelUrl(job.id) : undefined}
            aria-disabled={job?.status !== 'completed'}
            onClick={(event) => {
              if (job?.status !== 'completed') event.preventDefault()
            }}
          >
            دانلود اکسل
          </a>
        </div>
      </header>

      <main className="sheet">
        <div className="title-row">
          <div>
            <h1>خوانش دقیق با هوش مصنوعی</h1>
            <p className="lede">
              تصویر را بفرستید؛ مدل‌های قوی AI کلمات و جملات را عیناً از تصویر استخراج می‌کنند.
            </p>
          </div>
          {job?.confidence != null && (
            <div className="confidence" aria-label="میانگین اطمینان">
              <span className="confidence-label">اطمینان</span>
              <span className="confidence-value num">{confidenceLabel(job.confidence)}</span>
            </div>
          )}
        </div>

        <input
          ref={inputRef}
          className="sr-only"
          type="file"
          accept="image/*"
          onChange={onFileChange}
        />

        {!previewUrl ? (
          <section
            className={`dropzone ${dragOver ? 'is-over' : ''}`}
            onDragOver={(event) => {
              event.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                inputRef.current?.click()
              }
            }}
          >
            <p className="drop-title">تصویر را اینجا رها کنید</p>
            <p className="drop-hint">هر محتوایی — خروجی همان متن واقعی تصویر است</p>
          </section>
        ) : (
          <div className="workspace">
            <section className="panel image-panel">
              <div className="panel-head">
                <h2>تصویر منبع</h2>
                <button
                  type="button"
                  className="btn ghost compact"
                  onClick={() => inputRef.current?.click()}
                  disabled={uiState === 'uploading'}
                >
                  تعویض تصویر
                </button>
              </div>
              <figure className="image-frame">
                <img src={previewUrl} alt="تصویر منبع OCR" />
              </figure>
            </section>

            <section className="panel text-panel">
              <div className="panel-head">
                <h2>خروجی AI</h2>
                {job?.engine && <span className="meta mono">{job.engine}</span>}
              </div>

              {uiState === 'uploading' && (
                <div className="state-block" aria-live="polite">
                  <div className="pulse" />
                  <p>در حال استخراج دقیق کلمات و جملات با AI…</p>
                </div>
              )}

              {uiState === 'error' && (
                <div className="state-block error" role="alert">
                  <p>{error}</p>
                  <button type="button" className="btn ghost" onClick={() => inputRef.current?.click()}>
                    تلاش دوباره
                  </button>
                </div>
              )}

              {uiState === 'ready' && job && (
                <>
                  {job.warning && (
                    <div className="state-block error" role="status">
                      <p>{job.warning}</p>
                    </div>
                  )}

                  {job.extracted_text?.trim() && (
                    <div className="similar-box">
                      <div className="lines-head">
                        <span>متن کامل</span>
                      </div>
                      <article className="transcript" dir="rtl" lang="fa">
                        {job.extracted_text}
                      </article>
                    </div>
                  )}

                  {sentences.length > 0 && (
                    <div className="similar-box">
                      <div className="lines-head">
                        <span>جملات</span>
                        <span className="num">{sentences.length}</span>
                      </div>
                      <ol className="ocr-lines" dir="rtl" lang="fa">
                        {sentences.map((sentence, index) => (
                          <li key={`${index}-${sentence}`}>
                            <span>{sentence}</span>
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}

                  {(job.lines?.length || 0) > 0 && (
                    <div className="similar-box">
                      <div className="lines-head">
                        <span>خطوط</span>
                        <span className="num">{job.lines.length}</span>
                      </div>
                      <ol className="ocr-lines" dir="rtl" lang="fa">
                        {job.lines.map((line, index) => (
                          <li key={`${index}-${line.text}`}>
                            <span>{line.text}</span>
                            <span className="num similar-pct">{confidenceLabel(line.confidence)}</span>
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}

                  {words.length > 0 && (
                    <div className="similar-box">
                      <div className="lines-head">
                        <span>واژه‌ها</span>
                        <span className="num">{words.length}</span>
                      </div>
                      <p className="valid-words" dir="rtl" lang="fa">
                        {words.map((word) => word.text).join('، ')}
                      </p>
                    </div>
                  )}
                </>
              )}
            </section>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
