"""Contract tests for the websearch-only Korean portal skill.

`/scrape` Step 1b discovers every `.agents/skills/*/SKILL.md` and runs its CLI.
A market can be covered without one: the Korean portals were researched from
their official pages on 2026-09-14, no CLI was written for them, and nothing was
logged into or submitted. So the failure this pins is fabrication - a skill that
documents a scraping endpoint nobody verified, or claims an application flow
nobody tested, would be indistinguishable from a working portal to every later
run.

Three guards:
  * the skill declares itself websearch-only, so discovery routes it to Step 1c
    instead of reporting a missing CLI as a broken portal
  * every URL it names is one that was actually fetched during the research
  * everything unverified (apply mechanism, file formats, the two portals that
    did not respond) is written down as unknown rather than guessed at
"""
import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / ".agents" / "skills" / "korean-job-search"
SKILL = SKILL_DIR / "SKILL.md"
URL_REFERENCE = SKILL_DIR / "url-reference.md"
SCRAPER_SKILL = REPO / ".claude" / "skills" / "job-scraper" / "SKILL.md"
KOREAN_PORTALS = REPO / ".claude" / "skills" / "job-scraper" / "korean-portals.md"

# The pages the 2026-09-14 research actually fetched. A URL outside this set in
# the shipped skill is an invented endpoint, which is the whole failure mode.
RESEARCHED_URLS = {
    "https://www.saramin.co.kr/zf_user/jobs/list/domestic",
    "https://www.saramin.co.kr/zf_user/help/help-word/main?memberCode=1638&inquiryCode=1641",
    "https://www.saramin.co.kr/zf_user/help/help-word/view?idx=871",
    "https://www.jobkorea.co.kr/Search/",
    "https://www.jobkorea.co.kr/Recruit/GI_Read/49987891",
    "https://www.jobkorea.co.kr/Recruit/GI_Read/49987879",
    "https://www.wanted.co.kr/wdlist",
    "https://www.wanted.co.kr/cv/list",
    "https://help.wanted.co.kr/hc/ko/",  # fetched, returned HTTP 403
    "https://jumpit.saramin.co.kr/positions?sort=popular",
    "https://team.jumpit.co.kr/fff2defd-6806-81ff-940f-e0490e60ef20",
    "https://team.jumpit.co.kr/fff2defd-6806-810b-b2eb-e97dbd6fddb2",
    "https://team.jumpit.co.kr/fff2defd-6806-8148-a8d7-fbc94cfe019b",
    "https://www.work24.go.kr/wk/a/b/1200/retriveDtlEmpSrchList.do",
    "https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo=K141222609140006&infoTypeCd=VALIDATION&infoTypeGroup=tb_workinfoworknet",
    "https://kr.linkedin.com/jobs",
    "https://www.linkedin.com/help/linkedin/answer/a512388",
    "https://www.linkedin.com/help/linkedin/answer/a510363",
    "https://career.rememberapp.co.kr/job/postings",
    "https://career.programmers.co.kr/job",
    "https://www.rocketpunch.com/jobs",
}

_URL = re.compile(r"https?://[^\s)\]\"'>,]+")


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    return yaml.safe_load(text[4 : text.find("\n---", 4)])


class WebsearchOnlySkill(unittest.TestCase):
    def test_the_skill_declares_itself_websearch_only_with_no_cli(self):
        data = frontmatter(SKILL)
        self.assertEqual(data["mechanism"], "websearch")
        self.assertEqual(data["market"], "KR")
        self.assertNotIn(
            "bun run",
            str(data.get("allowed-tools", "")),
            "a websearch-only skill must not claim a CLI it does not ship",
        )
        self.assertFalse(
            list(SKILL_DIR.glob("cli/**/*.ts")),
            "no CLI files: the skill is a search-and-fetch recipe, not a scraper",
        )

    def test_the_enabled_toggle_is_present_so_a_fork_can_sit_it_out(self):
        self.assertIs(frontmatter(SKILL)["enabled"], True)

    def test_the_scraper_routes_a_websearch_only_skill_to_the_fallback(self):
        """Step 1b assumed every installed skill has a CLI, so a directory
        without one read as a broken portal for the health check to chase."""
        text = SCRAPER_SKILL.read_text(encoding="utf-8")
        self.assertIn("mechanism: websearch", text)
        self.assertRegex(
            text,
            r"never (a failure|treated as a failure|reported as broken)",
            "a declared websearch-only skill is a configuration, not a CLI failure",
        )


class NoInventedEndpoints(unittest.TestCase):
    def urls_in(self, path: Path) -> set[str]:
        return {u.rstrip(".,;") for u in _URL.findall(path.read_text(encoding="utf-8"))}

    def test_every_url_in_the_korean_skill_was_actually_fetched(self):
        for path in (SKILL, URL_REFERENCE, KOREAN_PORTALS):
            extra = sorted(self.urls_in(path) - RESEARCHED_URLS)
            self.assertEqual([], extra, f"{path.name} names URLs the research never fetched: {extra}")

    def test_the_entrypoints_that_were_verified_are_all_present(self):
        text = URL_REFERENCE.read_text(encoding="utf-8")
        for url in (
            "https://www.saramin.co.kr/zf_user/jobs/list/domestic",
            "https://www.jobkorea.co.kr/Search/",
            "https://www.wanted.co.kr/wdlist",
            "https://jumpit.saramin.co.kr/positions?sort=popular",
            "https://www.work24.go.kr/wk/a/b/1200/retriveDtlEmpSrchList.do",
            "https://kr.linkedin.com/jobs",
        ):
            self.assertIn(url, text)


class UnknownsAreWrittenDown(unittest.TestCase):
    def setUp(self):
        self.text = URL_REFERENCE.read_text(encoding="utf-8")

    def test_the_research_date_is_recorded(self):
        self.assertIn("2026-09-14", self.text, "a portal fact with no as-of date rots silently")

    def test_unverified_portals_are_not_declared_dead(self):
        for name in ("Programmers", "RocketPunch"):
            self.assertIn(name, self.text)
        self.assertIn("unverified", self.text.lower())
        self.assertNotRegex(
            self.text,
            r"(?i)(service (is )?closed|shut down|no longer exists)",
            "DNS failure and HTTP 403 are not evidence a service ended",
        )

    def test_apply_route_rows_carry_an_explicit_unknown(self):
        self.assertRegex(self.text, r"(?i)\bunknown\b")
        self.assertRegex(
            self.text,
            r"(?i)never submit|no automatic submission|submission is the user",
            "the skill finds and reports postings; it never applies to one",
        )

    def test_no_login_or_submission_is_claimed_as_tested(self):
        self.assertRegex(self.text, r"(?i)no (login|account).*(tested|performed)|not logged in")


if __name__ == "__main__":
    unittest.main()
