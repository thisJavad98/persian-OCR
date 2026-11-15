import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { downloadExcel, downloadWord, fetchHealth, uploadImage, type HealthStatus, type OcrJob } from "./api";
import "./App.css";

type UiState = "idle" | "uploading" | "ready" | "error";

function confidenceLabel(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${Math.round(value * 100)}٪`;
}

type AppProps = {
  onLogout: () => void | Promise<void>
}

function App({ onLogout }: AppProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [job, setJob] = useState<OcrJob | null>(null);
  const [uiState, setUiState] = useState<UiState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [exporting, setExporting] = useState<"excel" | "word" | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      try {
        const data = await fetchHealth();
        if (!alive) return;
        setHealth(data);
        setHealthError(null);
      } catch {
        if (!alive) return;
        setHealth(null);
        setHealthError("اتصال به سرور برقرار نیست.");
      }
    };
    void refresh();
    const id = window.setInterval(() => void refresh(), 20_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  async function processFile(file: File) {
    if (!file.type.startsWith("image/")) {
      setError("فقط فایل تصویری بفرستید.");
      setUiState("error");
      return;
    }

    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(URL.createObjectURL(file));
    setJob(null);
    setError(null);
    setUiState("uploading");

    if (health && !health.cursor_connected) {
      setError(
        health.details?.init_error ||
          "Cursor وصل نیست. CURSOR_API_KEY یا cursor-agent login را چک کنید.",
      );
      setUiState("error");
      return;
    }

    try {
      const result = await uploadImage(file);
      setJob(result);
      if (result.status === "failed") {
        setError(result.error_message || "استخراج متن ناموفق بود.");
        setUiState("error");
        return;
      }
      setUiState("ready");
      void fetchHealth().then(setHealth).catch(() => undefined);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "خطای ناشناخته";
      setError(msg.includes("fetch") || msg.includes("aborted") ? "زمان OCR تمام شد؛ دوباره تلاش کنید." : msg);
      setUiState("error");
      void fetchHealth().then(setHealth).catch(() => undefined);
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) void processFile(file);
    event.target.value = "";
  }

  function onDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragOver(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void processFile(file);
  }

  const words = (job?.words || []).filter((word) =>
    Boolean((word.text || "").trim()),
  );
  const sentences = (job?.sentences || []).filter((s) => Boolean(s.trim()));

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
          <button type="button" className="btn ghost" onClick={() => void onLogout()}>
            خروج
          </button>
          <button
            type="button"
            className="btn ghost"
            onClick={() => inputRef.current?.click()}
            disabled={uiState === "uploading"}
          >
            انتخاب تصویر
          </button>
          <button
            type="button"
            className="btn ghost"
            disabled={job?.status !== "completed" || exporting != null}
            onClick={() => {
              if (!job || job.status !== "completed") return;
              setExporting("word");
              void downloadWord(job)
                .catch((err) =>
                  setError(
                    err instanceof Error
                      ? err.message
                      : "دانلود ورد ناموفق بود.",
                  ),
                )
                .finally(() => setExporting(null));
            }}
          >
            {exporting === "word" ? "…" : "دانلود ورد"}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={job?.status !== "completed" || exporting != null}
            onClick={() => {
              if (!job || job.status !== "completed") return;
              setExporting("excel");
              void downloadExcel(job)
                .catch((err) =>
                  setError(
                    err instanceof Error
                      ? err.message
                      : "دانلود اکسل ناموفق بود.",
                  ),
                )
                .finally(() => setExporting(null));
            }}
          >
            {exporting === "excel" ? "…" : "دانلود اکسل"}
          </button>
        </div>
      </header>

      <div
        className={`cursor-status ${health?.cursor_connected ? "is-on" : healthError ? "is-warn" : "is-off"}`}
        role="status"
        aria-live="polite"
      >
        <span className="cursor-status-dot" aria-hidden="true" />
        <span className="cursor-status-text">
          {healthError
            ? healthError
            : health?.cursor_connected
              ? `Cursor متصل · ${health.cursor_model}${health.cursor_auth_via === "api_key" ? " · API" : " · CLI"}`
              : health?.details?.init_error
                ? `Cursor قطع · ${health.details.init_error}`
                : "در حال بررسی Cursor…"}
        </span>
        <button type="button" className="cursor-status-refresh" onClick={() => void fetchHealth().then(setHealth)}>
          بروزرسانی
        </button>
      </div>

      <main className="sheet">
        <div className="title-row">
          <div>
            <h1>خوانش دقیق با هوش مصنوعی</h1>
            <p className="lede">
              تصویر را بفرستید؛ مدل‌های AI کلمات و جملات را عیناً از تصویر
              استخراج می‌کنند.
            </p>
          </div>
          {job?.confidence != null && (
            <div className="confidence" aria-label="میانگین اطمینان">
              <span className="confidence-label">اطمینان</span>
              <span className="confidence-value num">
                {confidenceLabel(job.confidence)}
              </span>
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
            className={`dropzone ${dragOver ? "is-over" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                inputRef.current?.click();
              }
            }}
          >
            <p className="drop-title">تصویر را اینجا رها کنید</p>
            <p className="drop-hint">
              هر محتوایی — خروجی همان متن واقعی تصویر است
            </p>
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
                  disabled={uiState === "uploading"}
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

              {uiState === "uploading" && (
                <div className="state-block" aria-live="polite">
                  <div className="pulse" />
                  <p>در حال استخراج دقیق کلمات و جملات با AI…</p>
                </div>
              )}

              {uiState === "error" && (
                <div className="state-block error" role="alert">
                  <p>{error}</p>
                  <button
                    type="button"
                    className="btn ghost"
                    onClick={() => inputRef.current?.click()}
                  >
                    تلاش دوباره
                  </button>
                </div>
              )}

              {uiState === "ready" && job && (
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
                            <span className="num similar-pct">
                              {confidenceLabel(line.confidence)}
                            </span>
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
                        {words.map((word) => word.text).join("، ")}
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
  );
}

export default App;
