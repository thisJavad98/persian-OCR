export type OcrTable = {
  is_table?: boolean
  headers?: string[]
  rows: string[][]
}

export function parseTable(raw: unknown): OcrTable | null {
  if (!raw || typeof raw !== 'object') return null
  const t = raw as Record<string, unknown>
  const headers = Array.isArray(t.headers)
    ? t.headers.map((h) => String(h ?? '').trim())
    : undefined
  let rows: string[][] = []
  if (Array.isArray(t.rows)) {
    for (const row of t.rows) {
      if (!Array.isArray(row)) continue
      const cells = row.map((c) => String(c ?? '').trim())
      if (cells.some((c) => c !== '')) rows.push(cells)
    }
  }
  if (rows.length === 0) return null
  const isTable = t.is_table === true || rows.length >= 1
  if (!isTable) return null
  return { is_table: true, headers, rows }
}

export function tableColCount(table: OcrTable): number {
  if (table.headers?.length) return table.headers.length
  let max = 0
  for (const row of table.rows) {
    if (row.length > max) max = row.length
  }
  return max
}