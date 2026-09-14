# Korean portals - entry points and apply routes

**Checked 2026-09-14** against each portal's public pages and official help centre.
Public pages only: **no login or account was performed**, no application was
submitted, and no CAPTCHA challenge was tested. Every row says where it came from,
and says `unknown` where the research could not confirm it — an unknown here is a
fact about our evidence, not an invitation to fill it in from memory.

`/scrape` uses this file through `mechanism: websearch` (see `SKILL.md`): WebSearch
scoped to these hosts, then WebFetch on individual postings. There is no API and no
CLI for any of these portals, and none may be invented.

## Core entry points

| Portal | Search entry point | Verified on 2026-09-14 |
|---|---|---|
| Saramin | https://www.saramin.co.kr/zf_user/jobs/list/domestic | public domestic listing page; search UI supports exclusion keywords |
| JobKorea | https://www.jobkorea.co.kr/Search/ | public search; each result labelled `즉시 지원` (immediate) or `홈페이지 지원` (employer site) |
| Wanted | https://www.wanted.co.kr/wdlist | public listing page |
| Jumpit | https://jumpit.saramin.co.kr/positions?sort=popular | public listing; filters by tech-stack tags |
| Work24 (고용24) | https://www.work24.go.kr/wk/a/b/1200/retriveDtlEmpSrchList.do | public search; exposes a `고용24 입사지원 가능` direct-apply filter |
| LinkedIn Korea | https://kr.linkedin.com/jobs | localized LinkedIn domain — **lists jobs worldwide, so it is not evidence of the Korean market**; also covered by the `linkedin-search` CLI |
| Remember (optional) | https://career.rememberapp.co.kr/job/postings | public page; filters by role, salary, location, experience, company, industry; `간편 지원만 보기` toggle; includes headhunter listings |

Live examples fetched during the research, kept as proof the detail pages are
readable without an account:

- JobKorea immediate-apply posting: https://www.jobkorea.co.kr/Recruit/GI_Read/49987891 (open 2026-09-14 – 2026-10-14)
- JobKorea employer-site posting: https://www.jobkorea.co.kr/Recruit/GI_Read/49987879 (open 2026-09-14 – 2026-09-28)
- Work24 direct-apply posting: https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo=K141222609140006&infoTypeCd=VALIDATION&infoTypeGroup=tb_workinfoworknet — states `고용24 입사지원`, required documents 이력서 / 자기소개서 / 졸업증명서, deadline 2026-10-02 14:00

Neither apply button was followed. A posting's detail page does **not** generally
reveal the documents an employer will require — read each posting.

## Apply route, method and required documents

**`/scrape` and `/rank` never submit an application.** They report the route below so
the user can decide; submission is the user's own action, performed by hand.

| Portal | Route | Method (per official help) | Required documents |
|---|---|---|---|
| Saramin | platform apply, or employer's own site | internal/Saramin-hosted apply needs login + a registered application; the external-site flow is separate — https://www.saramin.co.kr/zf_user/help/help-word/main?memberCode=1638&inquiryCode=1641 | free-format-eligible postings accept a standalone file or URL resume, and the Saramin-authored resume is *not* sent alongside it. File resume: PDF/PNG/JPG/JPEG/GIF, one file ≤10MB, Office formats to be converted to PDF — https://www.saramin.co.kr/zf_user/help/help-word/view?idx=871. These limits belong to that resume feature, **not** to every attachment slot; per-posting requirements unknown |
| JobKorea | `즉시 지원` (on-platform) vs `홈페이지 지원` (employer site), labelled per result | unknown — not followed | unknown; upload rules not documented in the public pages fetched |
| Wanted | unknown — the application flow was not exercised | unknown | resume builder + PDF/DOCX upload with conversion to Wanted's own format exists at https://www.wanted.co.kr/cv/list; **that is a resume feature, not proof of how an application is submitted**. Help centre https://help.wanted.co.kr/hc/ko/ returned HTTP 403, so nothing further is confirmed |
| Jumpit | on-platform | login is Saramin's integrated login (observed on the homepage); a resume can be imported from Saramin with consent — https://team.jumpit.co.kr/fff2defd-6806-810b-b2eb-e97dbd6fddb2. Edits made after applying do not update an already-submitted application — https://team.jumpit.co.kr/fff2defd-6806-8148-a8d7-fbc94cfe019b | minimum resume = personal info + education + attachment, **or** personal info + education + tech stack + work experience; juniors may use an attachment or a portfolio URL — https://team.jumpit.co.kr/fff2defd-6806-81ff-940f-e0490e60ef20. File formats and size limits **unknown** — do not assume PDF |
| Work24 (고용24) | `고용24 입사지원` where the ad offers it, else the employer's route | unknown beyond the ad's own statement; no saved-resume or 구직신청 prerequisite was proven (the login prompts seen were for benefit services, not applications) | per advertisement — the live example above lists 이력서 / 자기소개서 / 졸업증명서 |
| LinkedIn Korea | Easy Apply (on-platform) vs Apply (employer or job-board redirect) — https://www.linkedin.com/help/linkedin/answer/a512388 | help text says signed in; wording differs between help pages, so treat login as path-dependent and verify live | Word or PDF, under 2MB *recommended* (not stated as a hard ceiling) — https://www.linkedin.com/help/linkedin/answer/a510363 |
| Remember | `간편 지원` toggle exists on the public listing | unknown | unknown — whether it submits a profile or a PDF was not established |

## Unverified, deliberately not concluded

| Portal | What happened on 2026-09-14 | What it does **not** prove |
|---|---|---|
| Programmers | https://career.programmers.co.kr/job — DNS ENOTFOUND from this network, on the root host and the job paths alike | unverified, nothing more. A DNS failure from one network is not evidence the service ended; re-check before adding or dropping it |
| RocketPunch | https://www.rocketpunch.com/jobs — HTTP 403 on the jobs path and the root | unverified. A 403 is a rejected client; no CAPTCHA and no login wall were observed, so do not describe it as either |

Both stay out of the core set until a later check reaches them. Record the date and
the observation when it happens, the same way this file does.
