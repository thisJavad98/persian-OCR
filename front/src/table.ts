export type OcrTable = {
  is_table?: boolean
  headers?: string[]
  rows: string[][]
}

const headerHints =
  /ردیف|رديف|نام|کد|كد|تاریخ|تاريخ|مبلغ|قیمت|قيمت|شماره|شهر|سن|جنسیت|جنسيت|وضعیت|وضعيت|شرح|ستون/i

function mostlyDigits(s: string): boolean {
  const t = s.trim()
  if (!t) return false
  let d = 0
  let o = 0
  for (const ch of t) {
    if (/\d|[.,\-/]/.test(ch)) d++
    else if (!/\s/.test(ch)) o++
  }
  return d > 0 && o <= 1
}

function rowLooksLikeHeader(cells: string[], dataRows: string[][]): boolean {
  const nonEmpty = cells.filter((c) => c.trim() !== '')
  if (nonEmpty.length < 2) return false
  if (nonEmpty.some((c) => headerHints.test(c))) return true
  if (nonEmpty.every(mostlyDigits)) return false
  if (nonEmpty.some((c) => [...c].length > 42)) return false
  if (dataRows.length === 0) return nonEmpty.length >= 2
  const hAvg =
    nonEmpty.reduce((n, c) => n + [...c].length, 0) / Math.max(1, nonEmpty.length)
  let sum = 0
  let n = 0
  for (const row of dataRows) {
    const vals = row.filter((c) => c.trim() !== '')
    if (vals.length < 2) continue
    sum += vals.reduce((a, c) => a + [...c].length, 0) / vals.length
    n++
  }
  if (n === 0) return hAvg <= 22
  return hAvg + 5 < sum / n
}

function padRow(row: string[], n: number): string[] {
  const out = row.slice(0, n)
  while (out.length < n) out.push('')
  return out
}

function colCount(headers: string[] | undefined, rows: string[][]): number {
  if (headers?.length) return headers.length
  let max = 0
  for (const row of rows) {
    if (row.length > max) max = row.length
  }
  return max
}

export function parseTable(raw: unknown): OcrTable | null {
  if (!raw || typeof raw !== 'object') return null
  const t = raw as Record<string, unknown>
  let headers = Array.isArray(t.headers)
    ? t.headers.map((h) => String(h ?? '').trim())
    : undefined
  let rows: string[][] = []
  if (Array.isArray(t.rows)) {
    for (const row of t.rows) {
      if (!Array.isArray(row)) continue
      const cells = row.map((c) => unwrapTableCell(String(c ?? '')))
      if (cells.some((c) => c !== '')) rows.push(cells)
    }
  }
  if (rows.length === 0) return null

  if ((!headers || headers.every((h) => !h)) && rows.length > 0) {
    const candidate = rows[0]
    if (rowLooksLikeHeader(candidate, rows.slice(1))) {
      headers = [...candidate]
      rows = rows.slice(1)
    }
  }

  if (headers?.length && rows.length > 0) {
    const a = headers.map((h) => h.trim().toLowerCase())
    const b = rows[0].map((c) => c.trim().toLowerCase())
    const same =
      a.length === b.length && a.filter((_, i) => a[i] === b[i]).length >= Math.min(a.length, b.length) - 1
    if (same) rows = rows.slice(1)
  }

  const ncol = colCount(headers, rows)
  if (ncol < 2 && rows.length < 1) return null

  if (headers?.length) {
    headers = padRow(headers, ncol)
  }
  rows = rows.map((r) => padRow(r, ncol))

  const isTable = t.is_table === true || rows.length >= 1 || Boolean(headers?.some(Boolean))
  if (!isTable) return null
  return { is_table: true, headers: headers?.some(Boolean) ? headers : undefined, rows }
}

export function tableColCount(table: OcrTable): number {
  return colCount(table.headers, table.rows)
}

export function parseTableFromJSONString(text: string | null | undefined): OcrTable | null {
  if (!text?.trim()) return null
  const raw = text.trim()
  if (!raw.startsWith('{')) return null
  try {
    const j = JSON.parse(raw) as Record<string, unknown>
    if (j.table && typeof j.table === 'object') return parseTable(j.table)
    if (j.is_table || Array.isArray(j.rows)) return parseTable(j)
  } catch {
    return null
  }
  return null
}

function mergeTables(primary: OcrTable | null, extra: OcrTable | null): OcrTable | null {
  if (!primary) return extra
  if (!extra) return primary
  const headers =
    primary.headers?.some((h) => h.trim()) ? primary.headers : extra.headers
  let rows = primary.rows.length > 0 ? primary.rows : extra.rows
  rows = rows.map((row) => row.map(unwrapTableCell))
  return parseTable({ is_table: true, headers, rows })
}

export function parseTableFromJob(job: {
  table?: unknown
  extracted_text?: string | null
  lines?: { text?: string }[]
}): OcrTable | null {
  const fromField = parseTable(job.table)
  const fromText = parseTableFromJSONString(job.extracted_text)
  let merged = mergeTables(fromField, fromText)
  if (!merged?.rows.length && job.lines?.length) {
    const fromLines = parseTableFromLines(job.lines.map((l) => l.text || ''))
    merged = mergeTables(merged, fromLines)
  }
  return merged
}

function parseTableFromLines(lines: string[]): OcrTable | null {
  for (const line of lines) {
    const t = parseTableFromJSONString(line)
    if (t?.rows.length) return t
  }
  const rows: string[][] = []
  for (const line of lines) {
    if (looksLikeJsonLine(line)) continue
    const cells = line.split(/\s*\|\s*|\t+/).map((c) => c.trim())
    if (cells.length >= 2) rows.push(cells.map(unwrapTableCell))
  }
  if (rows.length === 0) return null
  return parseTable({ is_table: true, rows })
}

function unwrapTableCell(cell: string): string {
  const c = cell.trim()
  if (!c.startsWith('{') && !c.startsWith('[')) return c
  try {
    const j = JSON.parse(c) as Record<string, unknown>
    if (typeof j.text === 'string' && j.text.trim()) return j.text.trim()
    if (j.table && typeof j.table === 'object') {
      const inner = parseTable(j.table)
      if (inner?.rows[0]) return inner.rows.map((r) => r.join(' ')).join(' / ')
    }
    if (Array.isArray(j.rows)) {
      const inner = parseTable(j)
      if (inner) return inner.rows.map((r) => r.join(' | ')).join('\n')
    }
  } catch {
    /* keep raw */
  }
  return c
}

export function looksLikeJsonLine(text: string | null | undefined): boolean {
  if (!text?.trim()) return false
  const t = text.trim()
  if (!t.startsWith('{') && !t.startsWith('[')) return false
  if (t.includes('"is_table"') || t.includes('"table"') || t.includes('"headers"')) return true
  try {
    JSON.parse(t)
    return true
  } catch {
    return t.length > 80 && t.includes('":')
  }
}

export function isAgentJsonPayload(text: string | null | undefined): boolean {
  return looksLikeJsonLine(text)
}

export function tablePlainPreview(table: OcrTable): string {
  const lines: string[] = []
  if (table.headers?.some((h) => h.trim())) {
    lines.push(table.headers.join(' | '))
  }
  for (const row of table.rows) {
    lines.push(row.join(' | '))
  }
  return lines.join('\n')
}