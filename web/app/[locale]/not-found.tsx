import Link from "next/link";

import { DEFAULT_LOCALE } from "@/i18n";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-2xl flex-col justify-center px-4 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">404</h1>
      <p className="mt-2 text-muted">This page does not exist.</p>
      <Link href={`/${DEFAULT_LOCALE}`} className="mt-4 text-accent">
        SaqBol
      </Link>
    </main>
  );
}
