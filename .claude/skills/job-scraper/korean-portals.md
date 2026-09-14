# Korean Search Vocabulary and Portals

Used by `/scrape` Step 1 when the run names a Korean locale ("/scrape korean jobs",
`--request-language ko`, `--market KR`). Nothing here is a claim about the user's
Korean: the CLAUDE.md Languages table and `04-job-evaluation.md`'s Language Gate
remain the only sources for that.

The portal facts - entry points, what was and was not verified, and the apply route
of each - live in `.agents/skills/korean-job-search/url-reference.md`, checked
2026-09-14. Read that file before searching; do not restate its URLs from memory,
and never invent an endpoint or an API for a portal that has neither.

## Portals (websearch-only, no CLI)

`.agents/skills/korean-job-search/` declares `mechanism: websearch`, so Step 1b
routes it to Step 1c and reports it on the `websearch-only:` line rather than as a
failed CLI. Core set: Saramin, JobKorea, Wanted, Jumpit, Work24, LinkedIn Korea;
Remember optional.

`linkedin-search` and `freehire-search` are country-agnostic CLIs and still run on a
Korean run, scoped through their own documented country/region flags. Portals scoped
to another single market (the Danish demos) are skipped and reported on the
`skipped (market):` line.

## Role keywords (query in Korean first, then the English variant)

| Function | Korean query terms | English variants |
|---|---|---|
| Backend | 백엔드, 서버 개발, 서버 개발자 | Backend, Server Engineer |
| Frontend / Fullstack | 프론트엔드, 웹 개발, 풀스택 | Frontend, Fullstack |
| AI / ML | AI 엔지니어, 머신러닝, 인공지능 | ML Engineer, AI Engineer |
| Data | 데이터 엔지니어, 데이터 분석 | Data Engineer, Data Analyst |
| Infra | DevOps, SRE, 클라우드, 인프라 | DevOps, SRE, Cloud |

Seniority terms: 신입 (entry), 경력 (experienced), 경력무관 (any), 인턴 (intern).
Region terms: 서울, 경기, 판교, 성남, 부산; remote: 재택근무, 원격근무.

Combine one role term with one region or seniority term per query, exactly as the
generic categories in `search-queries.md` do - the category cap is unchanged, a
Korean run just spends it on Korean queries.

## Portal-specific query notes (observed on the public search pages, 2026-09-14)

- **Saramin** supports exclusion keywords in its search UI.
- **Jumpit** filters by tech-stack tags rather than free text.
- **JobKorea** labels each result's apply method (`즉시 지원` vs `홈페이지 지원`).
- **Work24** exposes a direct-apply filter (`고용24 입사지원 가능`).

Discovery and application capability are separate questions: a portal being
searchable says nothing about whether an application can be submitted through it.
`/scrape` never applies to anything - it reports the apply route the posting itself
documents, and "unknown" when it does not.
