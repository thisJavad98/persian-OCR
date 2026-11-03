export type OcrLine = {
  text: string
  confidence: number
  box?: number[][] | null
}

export type NameAlternative = {
  name: string
  similarity: number
}

export type ResolvedName = {
  final_name: string
  confidence: number
  alternatives: NameAlternative[]
  gender?: string
  is_valid_iranian?: boolean
  similarity?: number
  source?: string
  raw?: string
}

export type RowNameSimilarity = {
  row_index: number
  name: string
  similarity: number
}

export type DeathRecord = {
  row_index: number
  deceased_name: ResolvedName
  national_id: string
  father_name: ResolvedName
  cause_of_death: string
  physician_name: ResolvedName
  confidence: number
  raw_line: string
  name_similarities?: RowNameSimilarity[]
}

export type SimilarNamePair = {
  left: string
  right: string
  similarity: number
}

export type AiNameEntry = {
  raw: string
  final_name: string
  gender: string
  is_valid_iranian: boolean
  confidence: number
  similarity: number
  source: string
}

export type DeathRecordsPayload = {
  records: DeathRecord[]
  similar_name_pairs: SimilarNamePair[]
  summary_text: string
  confidence: number
  details?: Record<string, unknown>
  ai_names?: {
    names: AiNameEntry[]
    comparisons: SimilarNamePair[]
    valid_words: string[]
    details?: Record<string, unknown>
  }
}

export type OcrJob = {
  id: number
  filename: string
  mime_type: string
  status: string
  extracted_text: string | null
  lines: OcrLine[]
  table: unknown
  death_records: DeathRecordsPayload | null
  engine: string | null
  confidence: number | null
  error_message: string | null
  image_url: string | null
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
