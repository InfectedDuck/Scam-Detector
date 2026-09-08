import type { Messages } from "@/i18n";
import { shareLinks } from "@/lib/share";
import type { Verdict } from "@/lib/types";

/**
 * The row under the advice: warn someone over WhatsApp or Telegram, or copy a
 * link to the public page for this scenario.
 *
 * A server component. The two chat links are plain anchors into the apps'
 * click-to-chat URLs. The copy control is also an anchor, to the share page
 * itself, so that without JavaScript it still leads somewhere the link can be
 * copied from; with JavaScript, `CopyLinkScript` below intercepts the click,
 * writes the URL to the clipboard and flips the label for a moment.
 *
 * Nothing here contains the message that was checked.
 */
export function ShareBar({
  verdict,
  messages,
  origin,
}: {
  verdict: Verdict;
  messages: Messages;
  origin: string;
}) {
  const { locale, t } = messages;
  const playbookName = verdict.playbook_id
    ? messages.playbookName(verdict.playbook_id)?.text
    : undefined;
  const links = shareLinks({ origin, locale, verdict, playbookName, t });

  const pill =
    "inline-flex min-h-10 items-center gap-1.5 rounded-full border border-line bg-surface px-3.5 py-1.5 text-[0.875rem] font-medium text-ink no-underline";

  return (
    <div className="border-t border-line px-5 py-4 sm:px-6">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">
        {t("share.title")}
      </h3>
      <div className="mt-2.5 flex flex-wrap gap-2">
        <a href={links.whatsapp} target="_blank" rel="noopener noreferrer" className={pill}>
          <WhatsAppMark />
          WhatsApp
        </a>
        <a href={links.telegram} target="_blank" rel="noopener noreferrer" className={pill}>
          <TelegramMark />
          Telegram
        </a>
        <a
          href={links.copy}
          data-copy={links.copy}
          data-copied={t("share.copied")}
          className={`copy-link ${pill}`}
        >
          <LinkMark />
          <span data-label>{t("share.copy")}</span>
        </a>
      </div>
    </div>
  );
}

/**
 * Delegated click handler for every `[data-copy]` on the page, present or
 * future. Inline and rendered once by the page, so the card that arrives later
 * from the server action needs no client component of its own. If the
 * clipboard is unavailable (an insecure origin, an old browser) or refuses,
 * the anchor does what it does without the script: it opens the share page.
 */
export function CopyLinkScript() {
  const script = `document.addEventListener("click",function(e){var a=e.target&&e.target.closest&&e.target.closest("[data-copy]");if(!a||!navigator.clipboard)return;e.preventDefault();navigator.clipboard.writeText(a.getAttribute("data-copy")).then(function(){var l=a.querySelector("[data-label]"),o=l&&l.textContent;if(l)l.textContent=a.getAttribute("data-copied");a.setAttribute("data-state","copied");setTimeout(function(){if(l)l.textContent=o;a.removeAttribute("data-state")},2000)},function(){location.href=a.href})});`;
  return <script dangerouslySetInnerHTML={{ __html: script }} />;
}

function WhatsAppMark() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="currentColor">
      <path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm0 1.8a8.2 8.2 0 1 1-4.2 15.3l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 0 1 12 3.8Zm-3 4.3c-.2 0-.5.1-.7.3-.3.3-.9.9-.9 2.1s.9 2.4 1 2.6c.2.2 1.8 2.8 4.4 3.8 2.2.9 2.6.7 3.1.6.5 0 1.5-.6 1.7-1.2.2-.6.2-1.1.2-1.2l-.5-.3-1.7-.8c-.2-.1-.4-.1-.6.1l-.8 1c-.2.2-.3.2-.5.1-.3-.1-1.1-.4-2-1.2a7 7 0 0 1-1.4-1.8c-.1-.2 0-.4.1-.5l.4-.5.3-.4v-.5l-.8-1.8c-.2-.4-.4-.4-.6-.4H9Z" />
    </svg>
  );
}

function TelegramMark() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="currentColor">
      <path d="M21.9 4.3 18.7 19.5c-.2 1-.9 1.3-1.7.8l-4.8-3.5-2.3 2.2c-.3.3-.5.5-1 .5l.4-4.9 8.9-8c.4-.3-.1-.5-.6-.2L6.6 13.3l-4.7-1.5c-1-.3-1-1 .2-1.5l18.4-7.1c.9-.3 1.6.2 1.4 1.1Z" />
    </svg>
  );
}

function LinkMark() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    >
      <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.5 1.5" />
      <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.5-1.5" />
    </svg>
  );
}
