"use client";

import { useActionState, useState, type ReactNode } from "react";

import { MAX_TEXT_CHARS } from "@/lib/types";

/**
 * The only client component in the app.
 *
 * It owns a textarea, a character counter and a pending state, and nothing
 * else. The verdict it displays is built on the server and arrives as an RSC
 * payload, so none of the highlighting logic or the dictionaries are in this
 * bundle.
 *
 * `fallback` is the server-rendered card for a `?sample=` link, shown until the
 * action produces one of its own. Without JavaScript, the form still posts and
 * the server still answers.
 */
export function AnalyzeForm({
  action,
  strings,
  defaultValue = "",
  fallback,
}: {
  action: (previous: ReactNode, formData: FormData) => Promise<ReactNode>;
  /**
   * Plain strings only. Everything crossing this boundary is serialized, so
   * the counter arrives as a "{n} / {max}" template rather than a formatter.
   */
  strings: {
    label: string;
    placeholder: string;
    submit: string;
    submitting: string;
    counter: string;
  };
  defaultValue?: string;
  fallback?: ReactNode;
}) {
  const [result, formAction, pending] = useActionState<ReactNode, FormData>(action, null);
  const [length, setLength] = useState(defaultValue.length);

  return (
    <>
      <form action={formAction} className="mt-6">
        <label htmlFor="text" className="block text-sm font-medium text-ink">
          {strings.label}
        </label>

        <textarea
          id="text"
          name="text"
          rows={7}
          maxLength={MAX_TEXT_CHARS}
          defaultValue={defaultValue}
          onChange={(event) => setLength(event.target.value.length)}
          placeholder={strings.placeholder}
          className="mt-2 block w-full resize-y rounded-xl border border-line bg-surface px-4 py-3 text-[1rem] leading-relaxed text-ink placeholder:text-muted"
          // The message may be in any of four languages, and often a mix of two.
          spellCheck={false}
          autoComplete="off"
        />

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={pending}
            className="inline-flex min-h-11 items-center rounded-xl bg-ink px-5 py-2.5 text-base font-semibold text-bg disabled:opacity-60"
          >
            {pending ? strings.submitting : strings.submit}
          </button>
          <span className="ml-auto tabular-nums text-[0.8125rem] text-muted">
            {strings.counter
              .replace("{n}", String(length))
              .replace("{max}", String(MAX_TEXT_CHARS))}
          </span>
        </div>
      </form>

      <div className="mt-6" aria-live="polite" aria-busy={pending}>
        {result ?? fallback}
      </div>
    </>
  );
}
