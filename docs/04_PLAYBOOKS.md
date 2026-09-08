# SaqBol — Playbook set v1

Thirteen playbooks. Ten Kazakhstan, three for foreign students in China. This is the closed label set for KazScam v0.1 and the closed choice set handed to the LLM.

Write all of them in Russian first. Kazakh translation is a week-2 task for the co-annotators. Chinese needs native-speaker review before it goes live, because the China playbooks restate official guidance and a mistranslation there is a real harm.

**Before writing any `sources` entry, find the official warning.** Every playbook needs at least one link to a police, National Bank, eGov, bank, or Ministry of Public Security page. That is what separates this from a blog post, and it is what the datasheet reviewer will check.

---

## Label set

```
kz.bank_security_call
kz.egov_1414_code
kz.delivery_link
kz.marketplace_safe_deal
kz.mule_account_rental
kz.investment_deepfake
kz.hijacked_account_relative
kz.apk_install
kz.fake_store
kz.remote_access_loan
cn.fake_police_deposit
cn.currency_exchange
cn.part_time_task_job
```

Plus `none` for legitimate messages and `other_scam` for scams that match no playbook. Keep `other_scam`: without it, annotators force-fit rows and the dataset degrades. Track its share; if it exceeds roughly a sixth of scam rows, the playbook set is incomplete and v0.2 needs another entry.

---

## Kazakhstan playbooks

### 1. `kz.bank_security_call`
**Fake bank security service call.** The highest-volume script in Kazakhstan.

- **Contact**: unexpected call, increasingly a WhatsApp call, from an unknown number.
- **Hook**: "Someone is attempting a transfer from your account."
- **Trust**: caller states the victim's real full name, transfers them to an "investigator", may send a photo of an ID card.
- **Pressure**: stay on the line, this is a confidential investigation, tell no one.
- **Extraction**: the SMS code, full card details, or a transfer to a "safe account".
- **Expected indicators**: `C1`, `A1`, `E1`, `B1`, `B4`, `D3`, `J1`
- **Action**: hang up, call the bank on the number printed on the card, never a number given by the caller.
- **Hotline**: bank number, plus `1414` and `102`.
- **Red flags to show**: a real bank never asks for a code. There is no such thing as a safe account. "Do not hang up" exists to stop you getting a second opinion.

### 2. `kz.egov_1414_code`
**eGov / 1414 code phishing, usually toward a loan taken in the victim's name.**

- **Hook**: an SMS code arrives that the victim did not request, then a call explaining it away.
- **Extraction**: the eGov confirmation code, which authorizes a digital signature or a loan application.
- **Expected indicators**: `C3`, `A1`, `A4`, `E3`, `B1`
- **Action**: give the code to no one, then check active applications and loans in eGov and at the credit bureau.
- **Hotline**: `1414`.
- **Careful**: legitimate 1414 messages exist in volume. This playbook must fire on the *request for the code*, not on the code's arrival. Put a genuine 1414 SMS in the hard-negative set.

### 3. `kz.delivery_link`
**Fake parcel, post, or customs payment link.**

- **Hook**: a parcel is held, a small customs or redelivery fee is due.
- **Extraction**: card details entered on a lookalike payment page.
- **Expected indicators**: `C6`, `G1`, `G3`, `G5`, `B1`, `E7`
- **Action**: do not open the link, check the tracking number on the carrier's own site.

### 4. `kz.marketplace_safe_deal`
**OLX and Instagram "safe deal" link.** The buyer or seller moves the conversation to a messenger and sends a payment link.

- **Hook**: "I already paid, collect your money through this link."
- **Extraction**: entering card details, including the CVV, on a page that debits rather than credits.
- **Expected indicators**: `D2`, `D1`, `G1`, `G5`, `A2`
- **Action**: complete deals only inside the platform. A link is never needed to *receive* money.

### 5. `kz.mule_account_rental`
**Recruiting the victim as a money mule.** Offers to rent a Kaspi card or account, often aimed at students.

- **Hook**: easy money, just let transfers pass through your card.
- **Expected indicators**: `E5`, `H4`, `D1`
- **Action**: refuse. Explain the consequence plainly: the account holder is the one prosecuted, and the account gets frozen.
- **Tone note**: this is the one playbook where the user may be a willing participant rather than a victim. Write the advice as consequence information, not as an accusation.

### 6. `kz.investment_deepfake`
**Deepfake or fabricated endorsement investment ad, funnelling into a "personal manager".**

- **Hook**: a video or ad in which a recognizable public figure or a bank appears to promote a platform.
- **Trust**: a personal manager, a dashboard showing fake growth, a small successful withdrawal early on.
- **Extraction**: escalating deposits, then a "tax" or "commission" required before withdrawal.
- **Expected indicators**: `H1`, `H2`, `E4`, `E7`, `D1`
- **Action**: verify with the institution directly, and treat a blocked withdrawal that requires a further payment as conclusive.

### 7. `kz.hijacked_account_relative`
**A friend's or relative's hijacked WhatsApp or Telegram account asking for an urgent transfer.**

- **Expected indicators**: `J3`, `J2`, `B1`, `I4`, `E2`
- **Action**: call the person on their known number, or ask a question only they could answer. Never verify inside the same chat.

### 8. `kz.apk_install`
**An Android package sent in chat.** Framed as a banking app update, a court document viewer, or a delivery tracker.

- **Expected indicators**: `F2`, `F3`, `F4`, `C1` or `C2` or `C6`
- **Action**: do not install. Install banking apps only from the official store. If already installed, disconnect the network and call the bank.

### 9. `kz.fake_store`
**Fake online shop or Instagram storefront.** Prepayment, then silence.

- **Expected indicators**: `G6`, `G1`, `E7`, `H3`
- **Action**: pay on delivery, check the domain age and the legal entity details, search the account name plus the word for "scam".

### 10. `kz.remote_access_loan`
**Remote-access takeover ending in a loan.** Often the second half of playbook 1.

- **Extraction**: AnyDesk or TeamViewer installed "to protect the account", the operator then drives the banking app themselves.
- **Expected indicators**: `F1`, `F3`, `C1`, `E3`, `D3`
- **Action**: end the session, turn off mobile data, call the bank from another device, then file a police report.

---

## China playbooks (foreign-student mode)

These three exist because China's national anti-fraud app requires a national ID number and a face scan and is Chinese-only, so the roughly 380,000 international students in the country cannot use it. **Every one of these must route to 96110 first and cite the official guidance it restates.** SaqBol translates and contextualizes official advice. It does not replace it.

### 11. `cn.fake_police_deposit`
**Fake police, prosecutor, embassy, or immigration officer.** The dominant scam against foreign students in China.

- **Hook**: your parcel contained contraband, your visa is being cancelled, your identity is implicated in money laundering.
- **Trust**: a spoofed caller ID, a "case number", a fake warrant sent over a messenger, a video call with a uniform and a staged office.
- **Pressure**: secrecy, threat of deportation or arrest, insistence on staying on the call.
- **Extraction**: a "guarantee deposit" wired to a "safe account" for verification.
- **Expected indicators**: `C2`, `C5`, `B3`, `E6`, `E1`, `J1`, `D3`, `I1`
- **Action**: hang up and dial 96110. Chinese police never take deposits by phone and never conduct case business over a messenger. Contact your embassy and your university's international office independently.
- **Hotline**: `96110`, then the university international office and the embassy.

### 12. `cn.currency_exchange`
**Private currency exchange over a messenger.** Two distinct harms: the money is simply taken, or the incoming funds are criminal proceeds and the student's bank card is frozen in an investigation.

- **Expected indicators**: `D1`, `H1`, `E2`
- **Action**: exchange only through a bank or a licensed operator. Explain the frozen-card risk explicitly, because it is the consequence students underestimate.
- **Hotline**: `96110`, plus the issuing bank.

### 13. `cn.part_time_task_job`
**Task-commission and fake part-time work, and the related exam-answer or "alumni" approach.**

- **Hook**: small tasks paid immediately, larger prepaid tasks later.
- **Extraction**: the victim funds increasingly large "orders" and cannot withdraw.
- **Expected indicators**: `H4`, `E7`, `D1`, `H1`
- **Action**: no legitimate employer requires you to pay to work. Report to 96110 and the university.

---

## Writing rules for the YAML files

1. **Advice comes from the playbook, never from the model.** Phone numbers in particular must be literal strings in YAML, verified against an official page.
2. **`retrieval_phrases` are for embeddings only** and are never displayed. Ten to twenty short phrases per playbook, in Russian and Kazakh, plus Chinese for the China set.
3. **Keep `summary` under 200 characters.** It is shown on the verdict card.
4. **Every stage description is one sentence.** The card shows the current stage and the next one, which is the feature users find uncanny and share.
5. **Two red flags minimum, three ideally.** These are the educational payload and the reason someone forwards the bot to a parent.
6. **Bump `version` on any text change** and record the version in the verdict, so a dataset row can be traced to the exact advice that was shown.

---

## Deferred to v0.2

Named as future work in the report. Do not build these now.

- Voice-note transcription and voice-clone detection, which is the natural iDES-lab continuation.
- Android package static analysis.
- Romance and long-con detection over multi-day threads.
- Russian Federation, Uzbek, and Kyrgyz regional variants.
- A local Kazakh OCR model to replace the hosted vision call.
