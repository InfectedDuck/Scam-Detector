# KazScam — annotation guideline

The instruction sheet for everyone who labelled a row in KazScam, and the
reference for anyone auditing the release. It ships with the datasheet because a
label set is only as legible as the rules that produced it.

**Labelling happens in two questions, and the second one is optional.** Every
annotator answers question one: *is this a scam?* Only if the answer is **Scam**
does the tool ask question two: *which script is it?* If you are helping for an
evening and would rather not learn thirteen categories, answer question one,
press **I don't know which**, and stop. Those rows are complete and usable: they
carry the binary label most of the evaluation runs on. The rest of this document
exists for question two.

Read each message as its recipient saw it: on a phone, with no time to research,
and without looking up the domain or the number. Names, cards and phone numbers
are replaced by placeholders such as `<NAME>`; a placeholder is not evidence.

---

## 1. The label set

**Question one** — three answers, recorded as the row's `label`:

| Button | In the data | Means |
|---|---|---|
| Scam | `scam` | An attempt to defraud the recipient. |
| Legitimate | `legit` | A real message, including alarming real ones — a genuine 1414 code, a login alert, an ordinary marketplace chat. |
| Not sure | `ambiguous` | See section 3. |

**Question two** — the closed set of thirteen playbooks plus `other_scam`,
recorded as `playbook_id`. Asked only when question one is `scam`, and it may be
left blank.

---

## 2. One example per playbook

One compressed message per label. The corpus is Russian and Kazakh; these are
glossed into English for readers of the release.

| Playbook | A message that gets this label |
|---|---|
| `kz.bank_security_call` | "Kaspi security service. Someone is transferring 480,000 ₸ from your account. Do not hang up, I'll connect you to an investigator." |
| `kz.egov_1414_code` | An unrequested 1414 code arrives, then a caller: "the system glitched, read me the code and I'll cancel it." The label is the *request*, never the code itself. |
| `kz.delivery_link` | "Your parcel is held at customs. Pay 1,150 ₸ within 24 hours: kazpost-dostavka[.]top/pay" |
| `kz.marketplace_safe_deal` | "I already paid for the sofa through the app — collect your money at this link." A link is never needed to *receive* money. |
| `kz.mule_account_rental` | "Students with a Kaspi card wanted. 30,000 ₸ a week, transfers just pass through your account." |
| `kz.investment_deepfake` | A video in which a National Bank official appears to endorse a platform; write to a personal manager to start. |
| `kz.hijacked_account_relative` | From a cousin's WhatsApp: "I'm in trouble, send 150,000 to this card, I'll explain later, don't call." |
| `kz.apk_install` | "Halyk security update — install the attached `Halyk_update.apk`." |
| `kz.fake_store` | An Instagram shop, three weeks old, comments off, 100% prepayment to a personal card. |
| `kz.remote_access_loan` | "To protect your account, install AnyDesk and read me the number on the screen." |
| `cn.fake_police_deposit` | "Shanghai police. A parcel in your name held forged documents." A case number and warrant arrive by messenger; a guarantee deposit is demanded. |
| `cn.currency_exchange` | "RMB for tenge, better than the bank rate, I'm a student too — you transfer first." |
| `cn.part_time_task_job` | "Rate hotel listings, 30 ¥ a task, paid instantly." Later a 900 ¥ "order" is required to continue. |
| `other_scam` | "You won a car in a draw. Pay the 15,000 ₸ registration fee to receive it." Plainly a scam, no playbook fits. |

---

## 3. Choose "Not sure" over a guess

Answer **Not sure** whenever you could not defend either answer to the other
annotator. Typically: the text is a fragment; it turns on context you do not
have, such as whether the sender really is known to the recipient; or the wording
is one that real institutions and scammers both use.

`ambiguous` is a result, not a gap: those rows stay in the dataset and are
reported, because genuine ambiguity is a property of the domain worth measuring.
A guess is worse than an abstention. Every row is double-annotated and we report
Cohen's kappa per class, so invented confidence quietly corrupts both the
headline number and the ground truth under it.

Not sure is not the same as skipping. **Skip** is for a row you are not labelling
at all, and **Problem with this text** is for a row that is broken, truncated, or
should not be in the corpus.

---

## 4. `other_scam` versus a named playbook

Name a playbook only if the message would go on to follow that script *and* its
advice is what you would want shown to the recipient. If you are picking a
category because it is the closest of thirteen, the answer is `other_scam`.

`other_scam` is a positive claim: this is a scam, and none of the thirteen
describe it. It is different from **I don't know which**, which leaves
`playbook_id` empty and means you think one of the thirteen fits but cannot tell
which. Use the blank when you are unqualified; use `other_scam` when the set is.

For an auditor: the `other_scam` share of scam rows is a health metric. Above
roughly one sixth, the playbook set is incomplete and the next version owes it an
entry.

---

## 5. The stage rule

`stage` records where inside the script the victim is — `contact`, `hook`,
`trust`, `pressure`, `extraction`, `cashout` — and it is a property of a
conversation, not of a message.

**Label it only on multi-message threads, and leave it empty everywhere else.**
Single messages, which are most of the corpus, get an empty `stage`; so do threads
whose stage you cannot name from what is shown, and every `legit` or `ambiguous`
row. Where a thread does get one, it is the furthest stage reached by the last
message.

The labelling tool never asks for stage. It is added afterwards by the two core
annotators, on thread rows only, so an empty `stage` in the release is the normal
case and not missing data.

---

## 6. When two playbooks both fit

Apply these in order.

1. **Label what the message is doing now, not where it will end up.** A fake bank
   call that has not yet named a remote-access program is
   `kz.bank_security_call`; the moment it asks the recipient to install AnyDesk
   or TeamViewer it is `kz.remote_access_loan`. This pair is the known confusable
   one, and we report its kappa rather than hide it.
2. **The payload beats the pretext.** An `.apk` attached to a "court document" is
   `kz.apk_install`. A payment page behind a parcel notice is
   `kz.delivery_link`.
3. **Label the row, not the thread.** Consecutive messages in one thread may
   honestly take different playbooks.
4. **If none of these separate them,** pick the one whose advice serves the
   recipient better and move on. Do not confer with the other annotator: a
   disagreement here is exactly what per-class kappa exists to catch, and
   adjudication happens later, on the record.
