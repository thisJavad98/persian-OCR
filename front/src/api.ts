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

export type OcrJob = {
  id: number
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
  image_url: string | null
  warning?: string | null
  created_at: string
  updated_at: string
}

export async function uploadImage(file: File): Promise<OcrJob> {
  const body = new FormData()
  body.append('file', file)
  const response = await fetch('/api/ocr/upload', {
    method: 'POST',
    body,
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail || 'بارگذاری تصویر ناموفق بود.')
  }
  return response.json()
}

export function excelUrl(jobId: number): string {
  return `/api/ocr/${jobId}/excel`
}

export function wordUrl(jobId: number): string {
  return `/api/ocr/${jobId}/word`
}
