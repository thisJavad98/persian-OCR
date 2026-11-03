import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type MouseEvent as ReactMouseEvent,
  type WheelEvent as ReactWheelEvent,
} from 'react'
import {
  excelUrl,
  uploadImage,
  wordUrl,
  type DeathRecord,
  type OcrJob,
  type ResolvedName,
} from './api'
import './App.css'

type UiState = 'idle' | 'uploading' | 'ready' | 'error'

type RowSlice = {
  row_index: number
  label?: string
  url?: string
}

function SliceZoomModal({
  slice,
  onClose,
}: {
  slice: RowSlice
  onClose: () => void
}) {
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const dragRef = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null)

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
      if (event.key === '+' || event.key === '=') setZoom((z) => Math.min(6, Number((z + 0.25).toFixed(2))))
      if (event.key === '-' || event.key === '_') setZoom((z) => Math.max(0.5, Number((z - 0.25).toFixed(2))))
      if (event.key === '0') {
        setZoom(1)
        setOffset({ x: 0, y: 0 })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function onWheel(event: ReactWheelEvent<HTMLDivElement>) {
    event.preventDefault()
    const delta = event.deltaY > 0 ? -0.15 : 0.15
    setZoom((z) => Math.min(6, Math.max(0.5, Number((z + delta).toFixed(2)))))
  }

  function onPointerDown(event: ReactMouseEvent<HTMLDivElement>) {
    dragRef.current = {
      x: event.clientX,
      y: event.clientY,
      ox: offset.x,
      oy: offset.y,
    }
  }

  function onPointerMove(event: ReactMouseEvent<HTMLDivElement>) {
    if (!dragRef.current) return
    setOffset({
      x: dragRef.current.ox + (event.clientX - dragRef.current.x),
      y: dragRef.current.oy + (event.clientY - dragRef.current.y),
    })
  }

  function onPointerUp() {
    dragRef.current = null
  }

  if (!slice.url) return null

  return (
    <div
      className="slice-zoom-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={`بزرگ‌نمایی برش ردیف ${slice.row_index}`}
      onClick={onClose}
    >
      <div className="slice-zoom-panel" onClick={(event) => event.stopPropagation()}>
        <header className="slice-zoom-head">
          <div>
            <p className="slice-zoom-title">
              ردیف {slice.row_index}
              {slice.label ? ` — ${slice.label}` : ''}
            </p>
            <p className="slice-zoom-hint">اسکرول برای زوم · کشیدن برای جابه‌جایی · Esc بستن</p>
          </div>
          <div className="slice-zoom-controls">
            <button type="button" className="btn ghost compact" onClick={() => setZoom((z) => Math.max(0.5, Number((z - 0.25).toFixed(2))))}>
              −
            </button>
            <span className="num slice-zoom-level">{Math.round(zoom * 100)}٪</span>
            <button type="button" className="btn ghost compact" onClick={() => setZoom((z) => Math.min(6, Number((z + 0.25).toFixed(2))))}>
              +
            </button>
            <button
              type="button"
              className="btn ghost compact"
              onClick={() => {
                setZoom(1)
                setOffset({ x: 0, y: 0 })
              }}
            >
              ۱۰۰٪
            </button>
            <button type="button" className="btn primary compact" onClick={onClose}>
              بستن
            </button>
          </div>
        </header>
        <div
          className="slice-zoom-stage"
          onWheel={onWheel}
          onMouseDown={onPointerDown}
          onMouseMove={onPointerMove}
          onMouseUp={onPointerUp}
          onMouseLeave={onPointerUp}
        >
          <img
            src={slice.url}
            alt={`برش ردیف ${slice.row_index}`}
            draggable={false}
            style={{
              transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`,
            }}
          />
        </div>
      </div>
    </div>
  )
}

function confidenceLabel(value: number | null | undefined): string {
  if (value == null) return '—'
  return `${Math.round(value * 100)}٪`
}

function genderFa(value?: string): string {
  if (value === 'male') return 'مرد'
  if (value === 'female') return 'زن'
  return 'نامشخص'
}

function NameBlock({
  label,
  value,
  showAlternatives = true,
}: {
  label: string
  value?: ResolvedName | null
  showAlternatives?: boolean
}) {
  if (!value?.final_name) {
    return (
      <div className="field">
        <span className="field-label">{label}</span>
        <span className="field-value muted">—</span>
      </div>
    )
  }

  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <span className="field-value">
        {value.final_name}
        {value.is_valid_iranian ? (
          <span className="name-badge ok">معتبر</span>
        ) : (
          <span className="name-badge warn">بازبینی</span>
        )}
        <span className="name-badge soft">{genderFa(value.gender)}</span>
      </span>
      {showAlternatives && value.alternatives?.length > 0 && (
        <ul className="alt-names">
          {value.alternatives.map((alt) => (
            <li key={`${alt.name}-${alt.similarity}`}>
              مشابه: <strong>{alt.name}</strong>
              <span className="num"> — {alt.similarity}٪</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function RecordCard({ record }: { record: DeathRecord }) {
  const sims = record.name_similarities?.length
    ? record.name_similarities
    : (record.deceased_name?.alternatives || []).map((alt) => ({
        row_index: 0,
        name: alt.name,
        similarity: alt.similarity,
      }))

  return (
    <article className="record-card" dir="rtl" lang="fa">
      <header className="record-head">
        <span className="record-index num">ردیف {record.row_index}</span>
        <span className="record-conf num">{confidenceLabel(record.confidence)}</span>
      </header>
      <NameBlock label="نام متوفی" value={record.deceased_name} showAlternatives={false} />
      <div className="field">
        <span className="field-label">کد ملی / شناسه</span>
        <span className="field-value num">{record.national_id || '—'}</span>
      </div>
      <NameBlock label="نام پدر" value={record.father_name} />
      <div className="field">
        <span className="field-label">علت فوت</span>
        <span className="field-value">{record.cause_of_death || '—'}</span>
      </div>
      <NameBlock label="پزشک معالج" value={record.physician_name} />
      <div className="field">
        <span className="field-label">متن خام ردیف</span>
        <span className="field-value">{record.raw_line || '—'}</span>
      </div>
      {sims.length > 0 && (
        <div className="field">
          <span className="field-label">شباهت با همه ردیف‌ها</span>
          <ul className="alt-names">
            {sims.map((item) => (
              <li key={`${item.row_index}-${item.name}-${item.similarity}`}>
                {item.row_index > 0 ? (
                  <span className="num">ردیف {item.row_index}: </span>
                ) : null}
                <strong>{item.name}</strong>
                <span className="num"> — {item.similarity}٪</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  )
}

function App() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [job, setJob] = useState<OcrJob | null>(null)
  const [uiState, setUiState] = useState<UiState>('idle')
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [zoomSlice, setZoomSlice] = useState<RowSlice | null>(null)

  async function processFile(file: File) {
    if (!file.type.startsWith('image/')) {
      setError('فقط فایل تصویری بفرستید.')
      setUiState('error')
      return
    }

    if (previewUrl) URL.revokeObjectURL(previewUrl)
    const localPreview = URL.createObjectURL(file)
    setPreviewUrl(localPreview)
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

  const records = job?.death_records?.records || []
  const similarPairs = job?.death_records?.similar_name_pairs || []

  return (
    <div className="frame" data-ui="app">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            خ
          </span>
          <div>
            <p className="brand-name">خط‌خوان</p>
            <p className="brand-sub">استخراج فهرست متوفیان از تصویر</p>
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
            <h1>خوانش فهرست از تصویر</h1>
            <p className="lede">
              کیفیت تصویر را بالا می‌بریم، واژه‌های نستعلیق را استخراج می‌کنیم، و برش هر ردیف را
              برای بازبینی و خروجی اکسل/ورد نگه می‌داریم.
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
            <p className="drop-title">تصویر فهرست را رها کنید</p>
            <p className="drop-hint">نام · کد ملی · پدر · علت فوت · پزشک — سپس ارتقا و استخراج</p>
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
                <img src={previewUrl} alt="تصویر فهرست متوفیان" />
              </figure>
            </section>

            <section className="panel text-panel">
              <div className="panel-head">
                <h2>نتیجه استخراج</h2>
                {job?.engine && <span className="meta mono">{job.engine}</span>}
              </div>

              {uiState === 'uploading' && (
                <div className="state-block" aria-live="polite">
                  <div className="pulse" />
                  <p>در حال خوانش همه ردیف‌های تصویر (نام، کد ملی، پدر، علت فوت، پزشک)…</p>
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
                  <div className="records">
                    <div className="lines-head">
                      <span>همه موارد شناسایی‌شده</span>
                      <span className="num">
                        {records.length} ردیف / {job.lines?.length || 0} خط
                      </span>
                    </div>
                    {records.length > 0 ? (
                      records.map((record) => (
                        <RecordCard key={record.row_index} record={record} />
                      ))
                    ) : (
                      <p className="muted-note">هنوز ردیف ساخت‌یافته‌ای نیست؛ متن کامل پایین آمده است.</p>
                    )}
                  </div>

                  {(job.lines?.length || 0) > 0 && (
                    <div className="similar-box">
                      <div className="lines-head">
                        <span>همه خطوط استخراج‌شده</span>
                        <span className="num">{job.lines.length} خط</span>
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

                  {job.extracted_text?.trim() && (
                    <div className="similar-box">
                      <div className="lines-head">
                        <span>متن کامل پاسخ</span>
                      </div>
                      <article className="transcript" dir="rtl" lang="fa">
                        {job.extracted_text}
                      </article>
                    </div>
                  )}

                  {similarPairs.length > 0 && (
                    <div className="similar-box">
                      <div className="lines-head">
                        <span>همه نرخ‌های شباهت</span>
                        <span className="num">{similarPairs.length}</span>
                      </div>
                      <ul>
                        {similarPairs.map((pair) => (
                          <li key={`${pair.left}-${pair.right}-${pair.similarity}`}>
                            <span>{pair.left}</span>
                            <span className="similar-sep">≈</span>
                            <span>{pair.right}</span>
                            <span className="num similar-pct">{pair.similarity}٪</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {(job.death_records?.ai_names?.names?.length || 0) > 0 && (
                    <div className="similar-box">
                      <div className="lines-head">
                        <span>نام‌های اعتبارسنجی‌شده AI</span>
                        <span className="num">{job.death_records?.ai_names?.names.length} مورد</span>
                      </div>
                      <ul>
                        {job.death_records?.ai_names?.names.map((entry) => (
                          <li key={`${entry.raw}-${entry.final_name}`}>
                            <span>{entry.raw || '—'}</span>
                            <span className="similar-sep">→</span>
                            <strong>{entry.final_name}</strong>
                            <span className="num similar-pct">{entry.similarity}٪</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {(job.death_records?.ai_names?.valid_words?.length || 0) > 0 && (
                    <div className="similar-box">
                      <div className="lines-head">
                        <span>واژه‌ها و نام‌های معتبر ایرانی</span>
                        <span className="num">
                          {job.death_records?.ai_names?.valid_words.length} مورد
                        </span>
                      </div>
                      <p className="valid-words">
                        {job.death_records?.ai_names?.valid_words.join('، ')}
                      </p>
                    </div>
                  )}

                  {Array.isArray(job.death_records?.details?.row_slices) &&
                    (job.death_records?.details?.row_slices as RowSlice[]).length > 0 && (
                      <div className="similar-box">
                        <div className="lines-head">
                          <span>برش تصویر ردیف‌ها (پس از ارتقای کیفیت)</span>
                          <span className="num">
                            {(job.death_records?.details?.row_slices as RowSlice[]).length}
                          </span>
                        </div>
                        <p className="slice-zoom-tip">برای بزرگ‌نمایی روی هر برش کلیک کنید.</p>
                        <div className="slice-grid">
                          {(job.death_records?.details?.row_slices as RowSlice[]).map((slice) => (
                            <figure key={slice.row_index} className="slice-card">
                              <figcaption>
                                ردیف {slice.row_index}
                                {slice.label ? ` — ${slice.label}` : ''}
                              </figcaption>
                              {slice.url ? (
                                <button
                                  type="button"
                                  className="slice-thumb"
                                  onClick={() => setZoomSlice(slice)}
                                  aria-label={`بزرگ‌نمایی ردیف ${slice.row_index}`}
                                >
                                  <img src={slice.url} alt={`برش ردیف ${slice.row_index}`} />
                                </button>
                              ) : null}
                            </figure>
                          ))}
                        </div>
                      </div>
                    )}
                </>
              )}
            </section>
          </div>
        )}
      </main>

      {zoomSlice ? <SliceZoomModal slice={zoomSlice} onClose={() => setZoomSlice(null)} /> : null}
    </div>
  )
}

export default App
