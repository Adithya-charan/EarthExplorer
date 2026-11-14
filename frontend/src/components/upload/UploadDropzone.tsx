"use client";

import { useRef, useState } from "react";
import { FileUp } from "lucide-react";
import { MAX_UPLOAD_MB, validateUploadFile } from "@/lib/upload";
import { cx } from "@/components/ui/primitives";

/** Keyboard-accessible CSV picker with drag-and-drop and immediate client-side validation. */
export function UploadDropzone({
  onFile,
  disabled,
}: {
  onFile: (file: File) => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  function accept(file: File | undefined) {
    if (!file) return;
    const problem = validateUploadFile(file);
    setError(problem);
    if (!problem) onFile(file);
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!disabled) accept(e.dataTransfer.files?.[0]);
        }}
        className={cx(
          "flex flex-col items-center rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
          dragging ? "border-accent bg-accent-soft" : "border-line-strong bg-surface-muted",
        )}
      >
        <FileUp aria-hidden="true" size={28} className="text-muted" />
        <p className="mt-2 text-sm font-medium text-ink">Drop a CSV file here</p>
        <p className="mt-0.5 text-xs text-muted">
          .csv only, up to {MAX_UPLOAD_MB} MB. The file is profiled before anything is imported.
        </p>
        <label
          htmlFor="csv-file"
          className={cx(
            "mt-4 inline-flex min-h-9 cursor-pointer items-center rounded-md border border-accent bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-strong focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent",
            disabled && "pointer-events-none opacity-60",
          )}
        >
          Choose CSV file
        </label>
        <input
          ref={inputRef}
          id="csv-file"
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          disabled={disabled}
          aria-describedby={error ? "csv-file-error" : undefined}
          onChange={(e) => {
            accept(e.target.files?.[0]);
            e.target.value = ""; // allow re-selecting the same file after fixing it
          }}
        />
      </div>
      {error ? (
        <p id="csv-file-error" role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
