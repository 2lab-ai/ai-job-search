---
name: job-application-assistant
description: >
  Assists with job applications: evaluating job postings, tailoring CVs, writing cover letters,
  and preparing for interviews. Triggers on keywords like: job posting, job application, CV,
  cover letter, resume, interview prep, job fit, career, application, apply, ansøgning, stilling
allowed-tools: Read, Glob, Grep, WebFetch, WebSearch, Bash, Edit, Write, AskUserQuestion
framework_version: 1.5.0
---

# Job Application Assistant

---

## Workflow

When the user provides a job posting (URL or text), follow this workflow:

### Step 1: Research & Evaluate Fit
- Fetch the job posting content (use WebFetch for URLs). **A 403 is not a dead end** - follow the escalation order in `09-web-research.md` before concluding a page is unavailable, and prefer the employer's own careers posting over an aggregator listing
- Keep the **full posting text verbatim** for Step 3b to archive - never a summary
- Analyze the posting for required competencies, keywords, and priorities
- Research the company (website, LinkedIn, mission, recent news), per `09-web-research.md`
- Score the posting against the candidate's profile using the framework in `04-job-evaluation.md`
- Present the evaluation table and verdict
- Suggest whether the candidate should call the employer before applying (see `04-job-evaluation.md` for guidance)
- Ask the user if they want to proceed with an application

### Step 2: Tailor CV
- Before writing either document, derive `<company>_<role>` once by the **Subfolder naming** rule in `documents/README.md`; reuse that exact value for the CV, cover letter, and Step 3b archive path. If the rule says to stop because the derived name is empty, stop before creating any file.
- **Run `/apply` Step 2's opening policy here, do not re-derive it:** resolve the active template (`<CV_EXT>`/`<COVER_EXT>` and the compile commands from the `ACTIVE-TEMPLATE` block) *and* the document languages. An application is a bundle of **English plus the language the user actually asked in**, never a language read off the posting:
  ```bash
  python3 tools/document_bundle.py languages --requested "<explicit request, if any>" \
    --request-language "<language their request is written in>" \
    --request-text "<the user's own words>" --profile-language "<CV language: from CLAUDE.md>" \
    --posting-language "<language the ad is written in>" \
    --required-language "<language the ad requires documents in, if it says>"
  python3 tools/document_bundle.py plan --company "<Company>" --role "<Role>" \
    --languages "<ko,en>" --cv-ext "<CV_EXT>" --cover-ext "<COVER_EXT>" --write
  ```
  Pass the resolved extensions: they default to `.tex`, so omitting them under a custom template records filenames its compile command never produces. The `plan --write` call records every variant's exact path in `documents/applications/<company>_<role>/document_bundle.json`. Read the profile's `CV language:` as a fallback; never rewrite it.
- Read the most relevant existing CV variant from `cv/` as a starting point
- Follow the guidelines in `05-cv-templates.md`
- Create `cv/main_<company>_<role>_<lang><CV_EXT>` with tailored content, one per bundle language, at the exact paths the manifest lists
- Adjust: profile statement, skills section, experience bullet emphasis, section order

### Step 3: Write Cover Letter
- **Resolve the language first**, even when the user asked only for a letter: run the Step 2 language policy above (it is the same resolution, and it is cheap) before writing a word. A letter drafted in whatever language felt right is the failure this policy exists to prevent.
- Follow the writing style rules in `03-writing-style.md` (critical: no em-dashes, no cliches)
- Follow the template structure in `06-cover-letter-templates.md`
- Create `cover_letters/cover_<company>_<role>_<lang><COVER_EXT>`, one per bundle language, at the exact paths the manifest lists
- Ensure the letter connects specific experience to the role requirements

### Step 3a: Review, Compile and Verify (before recording)
- Run **`/apply` Steps 3 to 5** on what Steps 2 and 3 just wrote, then `/apply` Step 6's report. They are stated once in `.claude/commands/apply.md`; follow them there rather than working from a summary here. In short: one reviewer agent **per bundle language**, the drafter applies the feedback, then per variant compile with the resolved command, `verify_layout.py`, a visual Read, and the ATS text-layer extraction - including a positive `verify_pdf.py --contains` check on any non-Latin variant, where a clean parse is not proof.
- A document that was never compiled is a file the user cannot send, so this runs **before** Step 3b, not after it.

### Step 3b: Record the Application
- Run this once both documents exist - every language's pair, when the bundle has more than one - and have compiled cleanly per Step 3a. A CV or cover letter drafted alone is not yet an application.
- Follow **`/apply` Step 6b** (`.claude/commands/apply.md`) exactly: same header, same match-then-update rule, same `drafted` row, same posting archive, same prohibition on touching `job_scraper/seen_jobs.json`. It is stated there once so the two paths cannot drift. Four of its values are named in `/apply`'s own terms: `cv_file`/`cover_letter_file` are the **primary language's** pair from the paths written in Steps 2 and 3 here (one path each, never a list - the full set stays in `document_bundle.json`), `source` is the posting URL from Step 1, `deadline` is the application deadline from the posting text Step 1 keeps verbatim (empty when the posting states none - never guess one), and the posting text item 7 archives is the one Step 1 read.
- This step exists here because `/scrape` Step 5 routes straight into this skill. Without it, that path writes two documents and records nothing.

### Step 4: Interview Preparation
- Follow the framework in `07-interview-prep.md`
- Prepare STAR-format answers for likely questions
- Identify role-specific talking points
- Draft questions the candidate should ask the interviewer

---

## Reference Files

| File | Purpose |
|------|---------|
| `01-candidate-profile.md` | Education, experience, skills, publications, awards |
| `02-behavioral-profile.md` | Behavioral assessment, strengths, ideal environments |
| `03-writing-style.md` | Tone, structure, do's and don'ts |
| `04-job-evaluation.md` | Scoring framework for job fit |
| `05-cv-templates.md` | LaTeX CV structure and tailoring rules |
| `06-cover-letter-templates.md` | LaTeX cover letter structure and tailoring rules |
| `07-interview-prep.md` | STAR examples, tough questions, roleplay guidelines |
| `08-application-forms.md` | Portal free-text fields: self-introduction, project entries, character-limited pitches |
| `09-web-research.md` | Fetching postings and company pages: trust boundary, the WebFetch 403 fallback, escalation order, claim verification |

---

## Quick Commands

The user may also ask for individual steps without the full workflow:
- "Evaluate this job posting" - Step 1 only
- "Write a CV for [company]" - Step 2 only, including its language and active-template resolution
- "Write a cover letter for [role] at [company]" - Step 3 only, and Step 3's first bullet still applies: resolve the language before drafting
- "Help me prepare for an interview at [company]" - Step 4 only
- "What jobs should I look for?" - Career strategy discussion using profile + evaluation framework
