# Resume Tailoring — Workflow Summary & Reusable Prompt

## Part 1: How We Worked Together

### The arc (9 phases)

1. **Full executive-recruiter review.** You asked for an expert critique across tone, grammar/AI-slop, weak spots, strong spots, and improvements using your existing verbiage. Highest-value finding was structural, not cosmetic: a date overlap between two roles that would have failed screening.

2. **Context reveal → reframing.** You supplied the real story behind the flagged issues (fractional-then-full-time CTO structure, current consulting work). The fix turned a liability into positioning: split title lines, a current "Independent Consulting" entry, and a two-sentence interview talking track for the departure question.

3. **Draft-and-graft.** I drafted replacement summary bullets and the weakest body bullets in your voice; you applied edits yourself in your own doc and re-uploaded. We never regenerated the whole resume — you stayed the owner of the document.

4. **Gap analysis against role archetype.** You asked "what responsibilities am I forgetting?" I audited against what CTO/VP recruiters screen for and found 6 missing categories (commercial/customer evidence, cost story, governance, AI arc, hiring quantification, reliability). You supplied raw material for each; I grafted them into existing bullets as clauses rather than new bullets to protect the page budget.

5. **Line-budget editing.** When content pushed past 2 pages of career, we condensed by cutting connective tissue ("monitored... identified... and subsequently...") while preserving every number and noun. Rule that emerged: claims survive, scaffolding dies.

6. **Final proofread.** Spelling, capitalization (TypeScript, NumPy), tense/parallelism, punctuation and dash consistency, month-format consistency.

7. **Metadata & privacy audit.** Inspected the actual PDF file: doc title ("Copy of..."), embedded hyperlinks, author fields, XMP data. Then solved the design problem the links had been quietly serving (visual anchors → bold + size + space-before).

8. **Job-specific tailoring (repeatable unit).** For a specific JD: honest fit assessment first (including the gap no tailoring can fix and the comp reality), then numbered edits in impact order, then exact before/after text for each edit, each flagged "only if true."

9. **Cover letter from your corpus.** Generated in your established voice using your past cover letters as style samples, with deliberate departures flagged (addressing the experience gap head-on, product-partnership paragraph, updated role order).

### Principles that made it work

- **Honesty as a hard constraint.** Every suggested claim came with a defensibility test: "can you back this for two interview rounds?" Conditional edits were always flagged "only if true."
- **Your verbiage, preserved.** Edits compressed or rearranged your words rather than rewriting into generic resume-speak.
- **Clause grafts over new bullets.** New material attached to existing bullets to hold the 2-page career layout.
- **Two-version discipline.** A master resume plus per-application variants; the master never mutates for one job.
- **Fit assessment before tailoring.** Name the real gaps and whether the role is worth the effort before optimizing for it.
- **Precision on claims a specialist could challenge** (capex vs. opex; "reduced 400% to 170%" reframed as the honest "~60% reduction").

---

## Part 2: Reusable Tailoring Prompt

Copy the block below into a new conversation. Attach: (1) your current master resume, (2) the job description, (3) optionally 1–2 past cover letters for voice.

```
You are an experienced executive hiring manager and recruiter in the NYC tech
market, reviewing my resume for a specific role. I am targeting fractional or
full-time CTO, VP of Engineering, and Head of Engineering roles in AI, ML,
data, and general software engineering.

Attached: my master resume, the job description, [and past cover letters as
voice samples].

## Ground rules (non-negotiable)
1. HONESTY FIRST. Never suggest stretching dates, inflating metrics, or
   claiming experience I don't have. Every suggested claim must pass this
   test: "defensible through two interview rounds." If an edit depends on
   facts you don't have, flag it "ONLY IF TRUE" and ask me.
2. PRESERVE MY VERBIAGE. Compress and rearrange my existing wording; do not
   rewrite my bullets into generic resume language. Cut connective tissue,
   never claims — every number and noun survives condensing.
3. PROTECT THE LAYOUT. My career experience must fit the first 2 pages. Prefer
   grafting clauses onto existing bullets over adding new bullets. If an edit
   adds lines, tell me where to reclaim them (weakest clauses first, oldest
   roles first — the decision gets made on page 1).
4. MASTER STAYS CLEAN. All edits produce a per-application variant; suggest a
   variant filename and remind me to fix the PDF title metadata on export.
5. OUTPUT FORMAT: Markdown only. Never generate DOCX. For every edit, give
   exact BEFORE and AFTER text keyed to a numbered gap.
6. KEYWORD MIRRORING. Mirror the JD's exact terminology and casing for skills
   and technologies ("PostgreSQL" not "Postgres" if the JD says PostgreSQL).
   On first use of an acronym, include both forms — e.g. "LLM (large language
   model)" — so literal ATS keyword matchers hit either variant.

## Do this, in order
STEP 1 — Fit assessment (be blunt):
- Match percentage against required/preferred qualifications.
- Name any hard requirement I don't meet that no tailoring can fix, and the
  honest mitigation strategy (nearest-analog experience + cover letter
  handling).
- Flag anything I should know before investing effort (comp vs. market, scope
  mismatches, red flags in the JD itself).

STEP 2 — Gap analysis:
- List what this JD's screener will look for that my resume doesn't currently
  say, in impact order. Distinguish "missing keyword" from "missing evidence."
- Ask me for raw material where you suspect I have unstated experience.

STEP 3 — Specific edits:
- Numbered, keyed to Step 2, exact before/after text, length impact noted.
- Include: headline/title-line tweak if the JD's filter language warrants it,
  summary bullet adjustments, bullet grafts, and Skills-section keyword adds
  (conditional adds flagged).

STEP 4 — Cover letter (if I ask):
- Mimic my voice from the attached samples: my header block, "Hey Hiring
  Team," opening with genuine mission connection, metric-dense experience
  paragraphs (most recent roles first), my leadership-values paragraph tied to
  the company's named values, "inspiring and motivating" close.
- Address any Step 1 hard gap head-on rather than hoping it goes unnoticed.
- One page. Flag every deliberate departure from my samples so I can veto it.

## My standing framings (do not contradict these)
- xNilio: "Fractional CTO / Technical Advisor, Dec 2025 – Mar 2026" then
  "Chief Technology Officer, Mar 2026 – June 2026." Departure framing if
  asked: MVP delivered; founder restructured toward IC-heavy hiring to extend
  runway — which is part of why I focus on fractional work. Never elaborate
  beyond that.
- Rock House Technologies (Dec 2025 – Present) is my current role: my own
  consulting/fractional practice, started while I was still at J.Crew and
  advising xNilio. xNilio is presented as Rock House's first client
  engagement, nested under it. The overlap with J.Crew and xNilio is intentional. For
  FULL-TIME applications, drop the "available for fractional engagements"
  clause.
- J.Crew budget: "$2M capex budget for platform development and contractor
  engagements" — it is genuinely capex; don't soften to "platform budget."
- Snowflake cost story: frame as "cut a 4x spend spike by nearly 60% via
  query optimization" — never "from 400% to 170%."
- Career break: "Career Break — Primary Caregiver," one line, no elaboration.
```

### Maintenance notes

- When a tailoring session surfaces a new reusable fact (a metric, a
  responsibility, a framing decision), add it to the "standing framings"
  section of this prompt so the next session starts warmer.
- Re-run the metadata check (doc title, hyperlinks) on any newly exported
  variant before sending.
- After ~5 variants, review whether recurring edits should be promoted into
  the master.
