# SaqBol — remaining roadmap

Reviewed 15 September 2026. This is the current execution plan; the T identifiers refer to tasks in the original build plan.

## Outcome

Deliver a usable scam checker, a human-reviewed KazScam dataset, and reproducible evaluation results. The main remaining work is validating and releasing what exists, collecting credible data, and measuring quality.

## What the review established

| Area | Evidence in the workspace | Planning consequence |
|---|---|---|
| Core, bot, API, web | Implementations and tests exist under `src/saqbol`, `tests`, and `web`; Compose and CI exist | Verify and repair gaps; do not rebuild scaffolds |
| Local validation | `.venv/Scripts/python.exe -m pytest -m 'not network and not llm'` failed before collection: configured Python 3.12 executable is missing; no `python` or `py` command was found | Repair the environment first. The old 1,328-test count is historical, not a newly verified result |
| Work in progress | Existing uncommitted changes cover CI, web forms/tests, translations and all 13 playbooks | Review and preserve those changes before starting overlapping edits |
| Corpus | `data/kazscam_v0.1/manifest.json` says provisional: 126 collected rows, 50 excluded fragments, 76 eligible rows | Collection count is not release-ready dataset size |
| Splits | Manifest: 30 calibration, 46 test_press, zero test_donated, zero train_synthetic | An empty split cannot support a result; synthetic training data is optional |
| Contamination | `DESIGN_DECISIONS.md` section 4 records that all provisional test rows were inspected during development | Treat exposed data as development data; collect fresh held-out rows. Reshuffling existing rows does not restore independence |
| Annotation | Guideline and tool exist; pilot file contains synthetic seeds; prior plan says annotators are still needed | Verify tool export and independent labeling, then use real sourced rows for the measured pilot |
| Localization | Current edits add localized playbook content | Audit coverage and obtain native review instead of scheduling all translations from scratch |
| Stale contract note | `web/README.md` says normalized text is missing, but `api/schemas.py` defines `AnalyzeOut.normalized_text` and `web/lib/api.ts` consumes it | Verify the endpoint and repair documentation; do not blindly add the same field again |
| Live evidence | Existing plan records provider runs, deployment and China checks as pending; no live verification performed in this review | Track them as unverified until dated evidence exists, rather than assuming accounts are absent |

This was a repository and planning review. It did not validate a live deployment, call paid providers, or establish dataset novelty.

## Execution order

Task details and recommended models are in [11_CODEX_MINI_PLANS.md](11_CODEX_MINI_PLANS.md).

| Priority | Mini-plan | Original work | Depends on | Deliverable |
|---|---|---|---|---|
| Now | P01 environment and baseline | T101, T507 | — | Reproducible checks and failure inventory |
| Now, owner track | P02 external blockers | M0 | — | Confirmed accounts, volunteers, production access and dates |
| Next | P03 finish existing UI/localization changes | T109, T114, T301–305 | P01 | Reviewed patch with regressions checked |
| Next | P04 production readiness | T206, T207, T307 | P01 | Tested container/persistence/privacy runbook |
| Next | P05 provider validation and replay | T111, T115, T203, refusal probe | P01, provider access from P02 | Real call evidence and offline cassettes |
| Start early | P06 corpus and holdout design | T403–405, T408 | P01; reviewer from P02 | Collection inventory and frozen allocation rules |
| Start early | P07 annotation pilot | T402, T406 | P06; annotators from P02 | Real pilot, exports, agreement and revised guideline |
| Then | P08 live pilot and reachability | T207, T306 | P03, P04; host/token from P02 | Dated web/bot and mainland-network checks |
| Then | P09 collect and annotate batches | T403, T404, T407 | P07 | Reviewed messages, labels, adjudication and provenance |
| Then | P10 final splits | T408 | P09 | Frozen, hashed dataset with leakage checks |
| Then | P11 calibrate and freeze | T505 | P05, P10 | Versioned thresholds and model/prompt configuration |
| Then | P12 benchmark and ablations | T503, T504, T506 | P11 | Results, manifest, intervals and generated leaderboard |
| Then | P13 dataset release package | T409 | P10 | Complete, reviewable publication bundle |
| Then | P14 report and demo | T601, T603–606 | P08, P12, P13 | Report, one-pager and offline demo |
| Ongoing after live pilot | P15 feedback and evidence | T304, distribution plan | P08 | Dated usage evidence, reviewed feedback and outreach drafts |

P08 may launch with an explicitly rules-only text experience while P05 is pending; hybrid/screenshot claims require P05. Dataset work can progress alongside launch preparation, without concurrent agents or shared-file edits. P13 packaging can start while evaluation runs; publish only the frozen reviewed version.

## Revised milestones

Dates are proposed working targets, not promises. Human availability and corpus quality govern the research schedule.

| Window | Gate | If blocked |
|---|---|---|
| September 15–17 | P01 baseline; P02 owners and access recorded; P06 allocation policy agreed | Continue offline preparation and recruitment; record the specific dependency |
| September 18–21 | Local release checks, provider smoke/replay where accessible, real annotation pilot | Publish no model-quality claims; postpone public launch if operational checks fail |
| September 22–28 | Small live pilot; ongoing collection and double annotation | Narrow supported scope; report real sample size instead of padding it |
| September 29–October 5 | Freeze reviewed dataset, calibrate, run evaluation, prepare dataset bundle | Move research publication rather than using contaminated test data |
| October 6–12 | Report, reviewable release artifacts, tested offline demo | Cut optional experiments and visual polish |
| October 15 | Review project readiness with the owner | Use actual artifacts to decide timing |
| October 20 | Dated evidence snapshot | Show actual usage and missing evidence transparently |

## Scope and release gates

**Keep:** hard negatives, human annotation and agreement, provenance/PII review, clean test data, confidence intervals, rules-only baseline, datasheet, accessible demo and honest limitations.

**Defer first:** extra benchmark providers beyond two verified ones; human-translation ablation if translations are unavailable; dense-retrieval experiments; new stage-detection work; cosmetic polishing. Keep already working web/library/localization features unless a concrete maintenance problem warrants a cut.

**After v0.1:** larger donated corpus, fine-tuning, voice notes, APK analysis and longer conversations. Each needs a new evaluation question and success criterion before implementation.

Public-service gate: real API connection (no accidental mock mode), consent, persistence, retention scheduling, abuse controls, useful failure states, correct evidence highlighting, and dated deployment/reachability evidence.

Research gate: independent human labels, logged adjudication, release rights and scrub review, clean held-out rows, calibration-only tuning, a frozen run configuration, intervals and explicit skipped/unsupported cells. If data is too small, label the release a pilot and narrow conclusions. Do not lower annotation standards to reach 300–400 scam messages or 100–140 hard negatives.

Outreach and publication are future actions, not performed by this planning update.

## Keeping the plan current

Use `ready`, `in progress`, `blocked: <specific dependency>`, or `done: <evidence link>` per mini-plan. Check in a result note containing the scope, changed paths, checks, limitations and next task. Preserve original T identifiers in notes. Update this roadmap when a gate changes; leave historical snapshots clearly dated.
