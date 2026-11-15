package api

type OcrLine struct {
	Text       string      `json:"text"`
	Confidence float64     `json:"confidence"`
	Box        interface{} `json:"box"`
	Row        *int        `json:"row,omitempty"`
}

type OcrWord struct {
	Text       string      `json:"text"`
	Confidence float64     `json:"confidence"`
	Box        interface{} `json:"box"`
	Row        int         `json:"row"`
	LineIndex  int         `json:"line_index"`
}

type OcrJobOut struct {
	Filename      string    `json:"filename"`
	MimeType      string    `json:"mime_type"`
	Status        string    `json:"status"`
	ExtractedText *string   `json:"extracted_text"`
	Lines         []OcrLine `json:"lines"`
	Words         []OcrWord `json:"words"`
	Sentences     []string  `json:"sentences"`
	Table         any       `json:"table"`
	DeathRecords  any       `json:"death_records"`
	Engine        *string   `json:"engine"`
	Confidence    *float64  `json:"confidence"`
	ErrorMessage  *string   `json:"error_message"`
	Warning       *string   `json:"warning"`
}

type ExportIn struct {
	Filename      string    `json:"filename"`
	ExtractedText string    `json:"extracted_text"`
	Lines         []OcrLine `json:"lines"`
	Words         []OcrWord `json:"words"`
	Sentences     []string  `json:"sentences"`
	Engine        string    `json:"engine"`
	Confidence    *float64  `json:"confidence"`
}

type HealthOut struct {
	Status          string         `json:"status"`
	Database        string         `json:"database"`
	OCRReady        bool           `json:"ocr_ready"`
	Engines         []string       `json:"engines"`
	CursorConnected bool           `json:"cursor_connected"`
	CursorAuthVia   string         `json:"cursor_auth_via"`
	CursorModel     string         `json:"cursor_model"`
	Details         map[string]any `json:"details"`
}

type ErrorDetail struct {
	Detail string `json:"detail"`
}