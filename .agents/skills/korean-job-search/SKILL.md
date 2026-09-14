---
name: korean-job-search
version: 0.1.0
description: >
  Use this skill to find job postings in the South Korean market (Saramin,
  JobKorea, Wanted, Jumpit, Work24/고용24, LinkedIn Korea; Remember optional) with
  WebSearch and WebFetch. There is no CLI: it is a documented set of public entry
  points and query shapes, not a scraper. Trigger phrases: 한국 채용 공고, 국내 채용,
  사람인, 잡코리아, 원티드, 점핏, 고용24, 워크넷, Korean job search, jobs in Seoul,
  find korean developer jobs, 신입 개발자 채용, 경력 개발자 공고.
context: fork
mechanism: websearch  # no CLI by declaration - /scrape Step 1b routes this to Step 1c
market: KR
enabled: true  # set to false to keep this skill installed but have /scrape skip it
allowed-tools: WebSearch, WebFetch
---

# Korean Job Search (websearch-only)

A market skill with **no CLI**. `/scrape` Step 1b discovers it like any other
`.agents/skills/*/SKILL.md`, reads `mechanism: websearch`, and routes it to Step 1c's
WebSearch path — the missing `cli/` directory is the declaration, not a breakage, so
it is never probed by the Step 4.75 health check and never reported as broken.

**Nothing here was scraped, logged into, or applied through.** Every URL below was
fetched as a public page on **2026-09-14**; the apply routes and file-format rules
come from each portal's own help pages, quoted in `url-reference.md` with an explicit
`unknown` wherever the research could not confirm something. Do not fill an unknown
in from experience — re-check the portal and record what you saw.

## How to use it

1. Read `url-reference.md` (this directory) for the entry points, what each portal's
   search surface exposes, and the apply route per portal.
2. Build queries from `.claude/skills/job-scraper/korean-portals.md` — Korean role
   terms first, then the English variant, combined with a region or seniority term.
3. Run `WebSearch` scoped to one portal's entry point at a time (`site:` on the host
   from `url-reference.md`), then `WebFetch` the individual posting URLs the search
   returns. On a 403, follow the escalation order in
   `.claude/skills/job-application-assistant/09-web-research.md` — a 403 is a rejected
   client, not a closed service.
4. Feed results into `/scrape` Step 2 with the same fields every portal CLI emits
   (title, company, location, date, url) so dedup and `/rank` work unchanged. Tag them
   `source: websearch`.
5. Record the posting's own language and stated place for `/rank`'s `posting_language`
   / `market` / `location_verified`. A Hangul title is not proof of a Korean-language
   posting, and `kr.linkedin.com` is a localized domain that lists jobs worldwide —
   read the posting.

## Rules

- **No invented interfaces.** No API endpoints, no CLI, no auth flow. If a portal's
  public search is not reachable with WebSearch/WebFetch, report that and move on.
- **No automatic submission.** This skill finds and reports postings. Applying is the
  user's action: report the apply route (`즉시 지원` / 홈페이지 지원 / Easy Apply /
  고용24 입사지원) and the documented required files when a posting states them, or
  `unknown` when it does not. Never upload, never submit, never log in.
- **No login is assumed or performed.** Several of these portals gate parts of their
  flow behind an account; the research did not sign in, so any statement about the
  logged-in experience is marked unknown rather than guessed.
- **Searching in Korean is not a claim about the user.** This skill never touches the
  Languages table or `04-job-evaluation.md`'s Language Gate.
- **Respect `enabled: false`** — a fork can install this and sit out a run.
