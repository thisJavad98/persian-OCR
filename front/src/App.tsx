import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import {
  clearHandwriting,
  downloadExcel,
  downloadWord,
  fetchHandwritingStatus,
  fetchHealth,
  trainHandwriting,
  uploadImage,
  type HandwritingStatus,
  type HealthStatus,
  type OcrJob,
} from "./api";
import { parseTable, tableColCount, type OcrTable } from "./table";
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
  const [hwStatus, setHwStatus] = useState<HandwritingStatus | null>(null);
  const [hwModalOpen, setHwModalOpen] = useState(false);
  const [hwTraining, setHwTraining] = useState(false);
  const [hwError, setHwError] = useState<string | null>(null);
  const [hwSample, setHwSample] = useState<File | null>(null);
  const [hwExcel, setHwExcel] = useState<File | null>(null);
  const [hwSamplePreview, setHwSamplePreview] = useState<string | null>(null);
  const hwSampleRef = useRef<HTMLInputElement>(null);
  const hwExcelRef = useRef<HTMLInputElement>(null);

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

  useEffect(() => {
    let alive = true;
    void fetchHandwritingStatus()
      .then((data) => {
        if (alive) setHwStatus(data);
      })
      .catch(() => {
        if (alive) setHwStatus(null);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!hwSample) {
      setHwSamplePreview(null);
      return;
    }
    const url = URL.createObjectURL(hwSample);
    setHwSamplePreview(url);
    return () => URL.revokeObjectURL(url);
  }, [hwSample]);

  useEffect(() => {
    if (!hwModalOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !hwTraining) setHwModalOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [hwModalOpen, hwTraining]);

  function openHwModal() {
    setHwError(null);
    setHwSample(null);
    setHwExcel(null);
    if (hwSampleRef.current) hwSampleRef.current.value = "";
    if (hwExcelRef.current) hwExcelRef.current.value = "";
    setHwModalOpen(true);
  }

  async function submitHwTraining() {
    if (!hwSample || !hwExcel) {
      setHwError("هم تصویر نمونه و هم اکسل مرجع را انتخاب کنید.");
      return;
    }
    setHwTraining(true);
    setHwError(null);
    try {
      const result = await trainHandwriting(hwSample, hwExcel);
      if (!result.ok) {
        setHwError(result.error || "شناسایی دست‌خط ناموفق بود.");
        return;
      }
      if (result.status) setHwStatus(result.status);
      else {
        const fresh = await fetchHandwritingStatus();
        setHwStatus(fresh);
      }
      setHwModalOpen(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "خطای ناشناخته";
      setHwError(
        msg.includes("aborted") ? "زمان شناسایی تمام شد؛ دوباره تلاش کنید." : msg,
      );
    } finally {
      setHwTraining(false);
    }
  }

  async function onClearHw() {
    setHwError(null);
    try {
      await clearHandwriting();
      setHwStatus({ active: false });
    } catch (err) {
      setHwError(err instanceof Error ? err.message : "حذف نمونه ناموفق بود.");
    }
  }

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
  const table: OcrTable | null = job ? parseTable(job.table) : null;

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
            {exporting === "excel" ? "…" : table ? "دانلود اکسل جدول" : "دانلود اکسل"}
          </button>
        </div>
      </header>

      <div className="status-stack">
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

        {hwStatus?.active && (
          <div className="hw-banner" role="status" aria-live="polite">
            <span className="hw-banner-dot" aria-hidden="true" />
            <p className="hw-banner-line">
              <span className="hw-banner-tag">دست‌خط فعال</span>
              <span className="hw-banner-sep" aria-hidden="true">
                ·
              </span>
              <span className="hw-banner-text">
                {hwStatus.message || "استخراج‌های بعدی با نمونهٔ ثبت‌شده دقیق‌تر می‌شوند."}
              </span>
              {(hwStatus.sample_filename || hwStatus.excel_filename) && (
                <>
                  <span className="hw-banner-sep" aria-hidden="true">
                    ·
                  </span>
                  <span className="hw-banner-files" dir="ltr">
                    {[hwStatus.sample_filename, hwStatus.excel_filename].filter(Boolean).join(" · ")}
                  </span>
                </>
              )}
            </p>
            <button type="button" className="hw-banner-action" onClick={() => openHwModal()}>
              مدیریت نمونه
            </button>
          </div>
        )}
      </div>

      <main className="sheet">
        <div className="title-row">
          <div className="title-main">
            <h1>خوانش دقیق با هوش مصنوعی</h1>
            <p className="lede">
              تصویر را بفرستید؛ مدل‌های AI کلمات و جملات را عیناً از تصویر
              استخراج می‌کنند.
            </p>
          </div>
          <div className="title-row-side">
            <button type="button" className="btn primary btn-hw-title" onClick={() => openHwModal()}>
              آموزش دست‌خط
            </button>
            {job?.confidence != null && (
              <div className="confidence" aria-label="میانگین اطمینان">
                <span className="confidence-label">اطمینان</span>
                <span className="confidence-value num">
                  {confidenceLabel(job.confidence)}
                </span>
              </div>
            )}
          </div>
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
                    <div className="state-block warn" role="status">
                      <p>{job.warning}</p>
                    </div>
                  )}

                  {table && (
                    <div className="similar-box" data-ui="table-view">
                      <div className="lines-head">
                        <span>جدول استخراج‌شده</span>
                        <span className="num">
                          {table.rows.length}×{tableColCount(table)}
                        </span>
                      </div>
                      <div className="table-scroll">
                        <table className="ocr-data-table" dir="rtl" lang="fa">
                          {table.headers && table.headers.length > 0 && (
                            <thead>
                              <tr>
                                {table.headers.map((h, i) => (
                                  <th key={`h-${i}`} scope="col">
                                    {h}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                          )}
                          <tbody>
                            {table.rows.map((row, ri) => (
                              <tr key={`r-${ri}`}>
                                {row.map((cell, ci) => (
                                  <td key={`c-${ri}-${ci}`}>{cell}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
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

      {hwModalOpen && (
        <div
          className="hw-backdrop"
          data-ui="hw-modal"
          role="presentation"
          onClick={() => !hwTraining && setHwModalOpen(false)}
        >
          <div
            className="hw-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="hw-modal-title"
            aria-describedby="hw-modal-desc"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="hw-modal-mark" aria-hidden="true">
              <span className="hw-modal-glyph">خ</span>
            </div>

            <header className="hw-modal-head">
              <p className="hw-modal-kicker">کالیبراسیون</p>
              <h2 id="hw-modal-title">آموزش دست‌خط</h2>
              <p id="hw-modal-desc" className="hw-modal-lede">
                یک صفحهٔ واقعی از دست‌خط خودتان و اکسلِ استخراج درست همان صفحه را بدهید؛
                خط‌خوان شکل حروف و چیدمان جدول را برای آپلودهای بعدی حفظ می‌کند.
              </p>
              <button
                type="button"
                className="hw-modal-close"
                disabled={hwTraining}
                aria-label="بستن"
                onClick={() => setHwModalOpen(false)}
              >
                ×
              </button>
            </header>

            <ol className="hw-steps" aria-label="مراحل">
              <li
                className={
                  hwSample ? "is-done" : hwTraining ? "" : "is-current"
                }
              >
                <span className="hw-step-num num">۱</span>
                <span className="hw-step-label">تصویر نمونه</span>
              </li>
              <li
                className={
                  hwSample && hwExcel
                    ? "is-done"
                    : hwSample && !hwTraining
                      ? "is-current"
                      : ""
                }
              >
                <span className="hw-step-num num">۲</span>
                <span className="hw-step-label">اکسل مرجع</span>
              </li>
              <li
                className={
                  hwSample && hwExcel && !hwTraining ? "is-current" : hwTraining ? "is-current" : ""
                }
              >
                <span className="hw-step-num num">۳</span>
                <span className="hw-step-label">شناسایی سبک</span>
              </li>
            </ol>

            <div className="hw-modal-body">
              {hwStatus?.active && (
                <div className="hw-profile">
                  <div className="hw-profile-copy">
                    <span className="hw-profile-tag">نمونهٔ فعال</span>
                    <p className="hw-profile-names" dir="ltr">
                      <span className="mono">{hwStatus.sample_filename || "—"}</span>
                      <span className="hw-profile-sep" aria-hidden="true">
                        /
                      </span>
                      <span className="mono">{hwStatus.excel_filename || "—"}</span>
                    </p>
                  </div>
                  <button
                    type="button"
                    className="btn ghost compact hw-profile-clear"
                    disabled={hwTraining}
                    onClick={() => void onClearHw()}
                  >
                    حذف نمونه
                  </button>
                </div>
              )}

              <div className="hw-picks">
                <div className="hw-pick">
                  <span className="hw-pick-label">تصویر نمونه دست‌خط</span>
                  <button
                    type="button"
                    className={`hw-pick-panel${hwSample ? " has-file" : ""}`}
                    disabled={hwTraining}
                    onClick={() => hwSampleRef.current?.click()}
                  >
                    {hwSamplePreview ? (
                      <img
                        className="hw-pick-thumb"
                        src={hwSamplePreview}
                        alt=""
                      />
                    ) : (
                      <span className="hw-pick-empty">
                        <span className="hw-pick-empty-title">انتخاب یا رها کردن تصویر</span>
                        <span className="hw-pick-empty-hint">PNG، JPG یا اسکن فرم</span>
                      </span>
                    )}
                    <span className="hw-pick-filename" dir="ltr">
                      {hwSample?.name || "هنوز فایلی نیست"}
                    </span>
                  </button>
                  <input
                    ref={hwSampleRef}
                    className="sr-only"
                    type="file"
                    accept="image/*"
                    disabled={hwTraining}
                    tabIndex={-1}
                    onChange={(event) => setHwSample(event.target.files?.[0] ?? null)}
                  />
                </div>

                <div className="hw-pick">
                  <span className="hw-pick-label">اکسل مرجع (.xlsx)</span>
                  <button
                    type="button"
                    className={`hw-pick-panel hw-pick-panel--sheet${hwExcel ? " has-file" : ""}`}
                    disabled={hwTraining}
                    onClick={() => hwExcelRef.current?.click()}
                  >
                    <span className="hw-sheet-glyph num" aria-hidden="true">
                      xlsx
                    </span>
                    <span className="hw-pick-empty">
                      <span className="hw-pick-empty-title">فایل استخراج درست</span>
                      <span className="hw-pick-empty-hint">همان داده‌ای که از نمونه انتظار دارید</span>
                    </span>
                    <span className="hw-pick-filename" dir="ltr">
                      {hwExcel?.name || "هنوز فایلی نیست"}
                    </span>
                  </button>
                  <input
                    ref={hwExcelRef}
                    className="sr-only"
                    type="file"
                    accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    disabled={hwTraining}
                    tabIndex={-1}
                    onChange={(event) => setHwExcel(event.target.files?.[0] ?? null)}
                  />
                </div>
              </div>

              {hwError && (
                <p className="hw-inline-error" role="alert">
                  {hwError}
                </p>
              )}

              {hwTraining && (
                <div className="hw-training" aria-live="polite">
                  <span className="pulse" aria-hidden="true" />
                  <div>
                    <p className="hw-training-title">در حال شناسایی دست‌خط</p>
                    <p className="hw-training-hint">
                      تصویر با اکسل مرجع هم‌تراز می‌شود؛ ممکن است چند دقیقه طول بکشد.
                    </p>
                  </div>
                </div>
              )}
            </div>

            <footer className="hw-modal-foot">
              <button
                type="button"
                className="btn ghost"
                disabled={hwTraining}
                onClick={() => setHwModalOpen(false)}
              >
                انصراف
              </button>
              <button
                type="button"
                className="btn primary"
                disabled={hwTraining || !hwSample || !hwExcel}
                onClick={() => void submitHwTraining()}
              >
                {hwTraining ? "در حال شناسایی…" : "شناسایی و ذخیره"}
              </button>
            </footer>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
