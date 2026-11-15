export type OcrLine = {
  text: string
  confidence: number
  box?: number[][] | null
  row?: number | null
}

export type OcrWord = {
  text: string
  confidence: number
  box?: number[][] | null
  row?: number
  line_index?: number
}

const apiInit: RequestInit = { credentials: 'include' }

export async function checkSession(): Promise<boolean> {
  const response = await fetch('/api/auth/me', apiInit)
  return response.ok
}

export async function login(username: string, password: string): Promise<void> {
  const response = await fetch('/api/auth/login', {
    ...apiInit,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail || 'نام کاربری یا رمز اشتباه است.')
  }
}

export async function logout(): Promise<void> {
  await fetch('/api/auth/logout', { ...apiInit, method: 'POST' })
}

export type HealthStatus = {
  status: string
  ocr_ready: boolean
  cursor_connected: boolean
  cursor_auth_via: string
  cursor_model: string
  engines: string[]
  details?: { init_error?: string | null }
}

export async function fetchHealth(): Promise<HealthStatus> {
  const response = await fetch('/api/health', apiInit)
  if (!response.ok) {
    throw new Error('وضعیت سرور در دسترس نیست.')
  }
  return response.json()
}

export type OcrJob = {
  filename: string
  mime_type: string
  status: string
  extracted_text: string | null
  lines: OcrLine[]
  words?: OcrWord[]
  sentences?: string[]
  table: unknown
  death_records: unknown
  engine: string | null
  confidence: number | null
  error_message: string | null
  warning?: string | null
}

const OCR_UPLOAD_TIMEOUT_MS = 12 * 60 * 1000

export async function uploadImage(file: File): Promise<OcrJob> {
  const body = new FormData()
  body.append('file', file)
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), OCR_UPLOAD_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetch('/api/ocr/upload', {
      ...apiInit,
      method: 'POST',
      body,
      signal: controller.signal,
    })
  } finally {
    window.clearTimeout(timer)
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail || 'بارگذاری تصویر ناموفق بود.')
  }
  return response.json()
}

function exportBody(job: OcrJob): object {
  return {
    filename: job.filename,
    extracted_text: job.extracted_text || '',
    lines: job.lines || [],
    words: job.words || [],
    sentences: job.sentences || [],
    engine: job.engine || '',
    confidence: job.confidence,
  }
}

async function downloadExport(path: string, job: OcrJob, fallbackExt: string): Promise<void> {
  const response = await fetch(path, {
    ...apiInit,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(exportBody(job)),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail || 'دانلود ناموفق بود.')
  }
  const blob = await response.blob()
  const base = job.filename.replace(/\.[^.]+$/, '') || 'ocr'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${base}.${fallbackExt}`
  a.click()
  URL.revokeObjectURL(url)
}

export function downloadExcel(job: OcrJob): Promise<void> {
  return downloadExport('/api/ocr/export/excel', job, 'xlsx')
}

export function downloadWord(job: OcrJob): Promise<void> {
  return downloadExport('/api/ocr/export/word', job, 'docx')
}