import { Fragment } from "react";

import type { Highlighted } from "@/lib/highlight";
import type { T } from "@/i18n";

/**
 * The message, with the evidence drawn on it.
 *
 * Rendered from the NORMALIZED text, never from the raw paste, because the
 * offsets index the normalized string. lib/highlight.ts has already flattened
 * the overlaps and verified every offset, so this file only has to paint.
 */
export function HighlightedMessage({
  highlighted,
  t,
  id,
}: {
  highlighted: Highlighted;
  t: T;
  id: string;
}) {
  return (
    <p className="msg text-[1.0625rem] text-ink" id={id}>
      {highlighted.segments.map((segment) => {
        if (segment.spans.length === 0) {
          return <Fragment key={segment.start}>{segment.text}</Fragment>;
        }

        // A span can straddle several segments where another span overlaps it.
        // Its number belongs at the point the span actually ends, once.
        const ending = segment.spans.filter((s) => s.end === segment.end);
        const label = segment.spans
          .map((s) => t(`indicator.${s.indicator_id}`))
          .join(" · ");

        return (
          <mark
            key={segment.start}
            id={ending.length === 1 ? `mark-${ending[0].n}` : undefined}
            className="mark"
            data-severity={segment.severity ?? "low"}
            data-overlap={segment.spans.length > 1 ? "true" : undefined}
            title={label}
          >
            {segment.text}
            {ending.map((s) => (
              <sup key={s.n} className="mark-n" aria-hidden="true">
                {s.n}
              </sup>
            ))}
          </mark>
        );
      })}
    </p>
  );
}
