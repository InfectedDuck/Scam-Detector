/**
 * Static registry over the generated fixtures, so the bundler can see every
 * import and nothing is loaded by a computed path at runtime.
 *
 * Regenerate with `npm run fixtures` after editing build-fixtures.mjs.
 */

import type { Band, Lang, Verdict } from "@/lib/types";

import bankCall from "./verdict.json";
import parcelFee from "./verdict.parcel.json";
import jobOffer from "./verdict.unsure.json";
import realNotification from "./verdict.safe.json";
import policeImpersonation from "./verdict.police.json";
import samples from "./samples.json";

/**
 * JSON imports widen to `string`, so the enum-ish fields have to be asserted.
 * build-fixtures.mjs is what actually guarantees these are valid; this cast
 * only tells TypeScript what that script already checked.
 */
const asVerdict = (v: unknown) => v as Verdict;

export interface Sample {
  id: string;
  lang: Lang;
  file: string;
  /** The raw message, exactly as it was fed to the generator. */
  text: string;
  band: Band;
}

export const SAMPLES = samples as Sample[];

export const FIXTURES: Record<string, Verdict> = {
  bank_call: asVerdict(bankCall),
  parcel_fee: asVerdict(parcelFee),
  job_offer: asVerdict(jobOffer),
  real_notification: asVerdict(realNotification),
  police_impersonation: asVerdict(policeImpersonation),
};

/** The fixture named in the task: a `scam` verdict with six evidence spans. */
export const CANONICAL_FIXTURE = FIXTURES.bank_call;

export function getSample(id: string): Sample | undefined {
  return SAMPLES.find((s) => s.id === id);
}
