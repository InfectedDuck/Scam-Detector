"use client";

import { useEffect, useId, useRef, useState, type DragEvent } from "react";

import { IMAGE_TYPES, MAX_IMAGE_BYTES } from "@/lib/types";

/**
 * A screenshot picker that is still a plain <input type="file"> underneath.
 *
 * The input is the field the form submits, with or without JavaScript: the
 * label opens the native picker on its own, and a dropped file is written back
 * into the input's `files` so the form posts it like any other. Everything
 * else here is feedback: the drag state, the thumbnail, the size check with a
 * human sentence instead of a silent failure, and the remove button.
 *
 * To reduce upload size, a file above `RE_ENCODE_ABOVE` is redrawn on a canvas
 * and re-encoded as a JPEG under that size before it is submitted. Without
 * JavaScript the server action accepts uploads up to the 5 MB image cap.
 */

const ACCEPT = IMAGE_TYPES.join(",");
const RE_ENCODE_ABOVE = 700 * 1024;
const MAX_EDGE = 1600;

export interface ImageDropZoneStrings {
  label: string;
  hint: string;
  browse: string;
  preview: string;
  remove: string;
  preparing: string;
  tooLarge: string;
  wrongType: string;
}

export function ImageDropZone({
  strings,
  onBusy,
}: {
  strings: ImageDropZoneStrings;
  /** Reports while a file is being prepared, so the submit button can wait. */
  onBusy?: (busy: boolean) => void;
}) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const selectionRef = useRef(0);
  const previewRef = useRef<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);

  useEffect(() => {
    return () => {
      selectionRef.current += 1;
      if (previewRef.current) URL.revokeObjectURL(previewRef.current);
      previewRef.current = null;
    };
  }, []);

  function updatePreview(next: string | null) {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    previewRef.current = next;
    setPreview(next);
  }

  function clear() {
    selectionRef.current += 1;
    if (inputRef.current) inputRef.current.value = "";
    setFile(null);
    updatePreview(null);
    setError(null);
    setBusy(false);
    onBusy?.(false);
  }

  async function accept(candidate: File | null | undefined) {
    // A later selection, removal, or unmount owns the field from that point on.
    const selection = ++selectionRef.current;
    const isCurrent = () => selection === selectionRef.current;
    setError(null);
    if (!candidate) {
      clear();
      return;
    }
    if (!(IMAGE_TYPES as readonly string[]).includes(candidate.type)) {
      clear();
      setError(strings.wrongType);
      return;
    }
    if (candidate.size > MAX_IMAGE_BYTES) {
      clear();
      setError(strings.tooLarge);
      return;
    }

    setBusy(true);
    onBusy?.(true);
    try {
      const prepared = candidate.size > RE_ENCODE_ABOVE ? await shrink(candidate) : candidate;
      if (!isCurrent()) return;
      const input = inputRef.current;
      if (input && (prepared !== candidate || input.files?.[0] !== candidate)) {
        const transfer = new DataTransfer();
        transfer.items.add(prepared);
        input.files = transfer.files;
      }
      setFile(prepared);
      updatePreview(URL.createObjectURL(prepared));
    } catch {
      if (!isCurrent()) return;
      // Could not decode or could not get it small enough. Either way the
      // honest advice is the same as for an oversized file.
      clear();
      setError(strings.tooLarge);
    } finally {
      if (isCurrent()) {
        setBusy(false);
        onBusy?.(false);
      }
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setOver(false);
    void accept(event.dataTransfer.files?.[0]);
  }

  function onDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (!over) setOver(true);
  }

  return (
    <div className="mt-5">
      <p id={`${id}-label`} className="text-sm font-medium text-ink">
        {strings.label}
      </p>

      <div
        role="group"
        aria-labelledby={`${id}-label`}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={() => setOver(false)}
        className={
          "mt-2 rounded-xl border border-dashed px-4 py-3.5 transition-colors " +
          (over ? "border-accent bg-raised" : "border-line bg-surface")
        }
      >
        {/* The input stays mounted whatever is shown, or the form would lose the file. */}
        <div className={file ? "sr-only" : "flex flex-wrap items-center gap-x-4 gap-y-2"}>
          <label
            htmlFor={id}
            className="inline-flex min-h-9 cursor-pointer items-center rounded-lg border border-line bg-raised px-3 py-1.5 text-sm font-medium text-ink"
          >
            {strings.browse}
          </label>
          <input
            ref={inputRef}
            id={id}
            name="image"
            type="file"
            accept={ACCEPT}
            aria-describedby={`${id}-hint`}
            className="sr-only"
            onChange={(event) => void accept(event.target.files?.[0])}
          />
          <span id={`${id}-hint`} className="text-[0.8125rem] text-muted">
            {busy ? strings.preparing : strings.hint}
          </span>
        </div>

        {file && preview && (
          <div className="flex items-center gap-4">
            <img
              src={preview}
              alt={strings.preview}
              className="h-16 w-16 shrink-0 rounded-lg border border-line object-cover"
            />
            <div className="min-w-0 flex-1 text-[0.8125rem] leading-snug">
              <p className="truncate text-ink">{file.name}</p>
              <p className="text-muted">{formatSize(file.size)}</p>
            </div>
            <button
              type="button"
              onClick={clear}
              className="inline-flex min-h-9 items-center rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink"
            >
              {strings.remove}
            </button>
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="mt-2 text-[0.8125rem] text-muted">
          {error}
        </p>
      )}
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** Redraw at most `MAX_EDGE` px on the long side and re-encode until it fits. */
async function shrink(file: File): Promise<File> {
  const bitmap = await createImageBitmap(file);
  try {
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("canvas");
    // JPEG has no alpha; a transparent screenshot background becomes white.
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

    for (const quality of [0.85, 0.72, 0.6]) {
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/jpeg", quality),
      );
      if (blob && blob.size <= RE_ENCODE_ABOVE) {
        const name = file.name.replace(/\.[^.]+$/, "") || "screenshot";
        return new File([blob], `${name}.jpg`, { type: "image/jpeg" });
      }
    }
    throw new Error("too large");
  } finally {
    bitmap.close();
  }
}
