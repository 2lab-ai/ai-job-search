"""Tests for tools/rank_state.py - /rank's state helper (#395).

/rank used to pull the whole of seen_jobs.json through the model's context to
select candidates, then emit it back to record scores. That cost the whole
backlog per run no matter how few jobs were being scored, and it grew for the
life of the workspace. These pin the behaviour the three subcommands took
over: selection matches Step 1's existing rules, the sweep matches rule 6
exactly (including its two defensive-parse edge cases), and the write-back
matches Step 4's existing rules exactly - the location_verdict legacy
migration, the deadline null-is-not-a-correction rule, and verbatim
strengths/gaps persistence.
"""
import json
import subprocess
import sys
import unicodedata
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "rank_state.py"

TODAY = "2026-09-03"


def entry(**over):
    base = {
        "title": "SOC Analyst",
        "company": "Acme",
        "url": "https://example.com/job",
        "first_seen": "2026-08-30",
        "deadline": None,
        "status": "new",
        "portal": "linkedin-search",
    }
    base.update(over)
    return base


class RankStateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state = self.tmp / "seen_jobs.json"
        self.addCleanup(self._tmp.cleanup)

    def write_state(self, seen):
        self.state.write_text(json.dumps({"seen": seen}), encoding="utf-8")

    def run_tool(self, *args, expect=0):
        proc = subprocess.run(
            [sys.executable, str(TOOL), *args, "--state", str(self.state), "--today", TODAY],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, expect, proc.stderr)
        return json.loads(proc.stdout)

    def read_state(self):
        return json.loads(self.state.read_text(encoding="utf-8"))["seen"]


class Candidates(RankStateCase):
    def test_selects_only_new_entries_and_projects_a_compact_row(self):
        self.write_state(
            {
                "a": entry(),
                "b": entry(status="ranked", rank_score=70),
                "c": entry(status="skipped"),
                "d": entry(status="expired"),
            }
        )
        out = self.run_tool("candidates", "--tracker", str(self.tmp / "none.csv"))
        self.assertEqual([row["key"] for row in out["selected"]], ["a"])
        self.assertEqual(
            set(out["selected"][0]),
            {"key", "title", "company", "url", "portal", "deadline", "posted_date"},
            "the projection is the point: strengths/gaps and every other stored field "
            "stay on disk rather than entering the conversation",
        )

    def test_limit_defers_the_rest_and_reports_the_count(self):
        self.write_state({f"k{i}": entry(title=f"Role {i}") for i in range(25)})
        out = self.run_tool("candidates", "--limit", "10", "--tracker", str(self.tmp / "none.csv"))
        self.assertEqual(len(out["selected"]), 10)
        self.assertEqual(out["eligible"], 25)
        self.assertEqual(
            out["deferred"],
            15,
            "a backlog larger than the batch limit must be reported, not silently truncated - "
            "the user has to know a re-run continues it",
        )

    def test_limit_zero_means_no_cap(self):
        self.write_state({f"k{i}": entry(title=f"Role {i}") for i in range(15)})
        out = self.run_tool("candidates", "--limit", "0", "--tracker", str(self.tmp / "none.csv"))
        self.assertEqual(len(out["selected"]), 15)
        self.assertEqual(out["deferred"], 0)

    def test_tracker_pairs_are_excluded(self):
        self.write_state({"a": entry(company="Acme", title="SOC Analyst"), "b": entry(company="Other")})
        tracker = self.tmp / "tracker.csv"
        tracker.write_text("date,company,role\n2026-08-01,ACME,soc analyst\n", encoding="utf-8")
        out = self.run_tool("candidates", "--tracker", str(tracker))
        self.assertEqual([row["key"] for row in out["selected"]], ["b"])
        self.assertEqual(out["excluded_by_tracker"], 1)

    def test_focus_filters_on_title_company_and_stored_fit_notes(self):
        self.write_state(
            {
                "a": entry(title="Data Scientist"),
                "b": entry(title="SOC Analyst"),
                "c": entry(title="Engineer", strengths=["strong data science match"]),
            }
        )
        out = self.run_tool("candidates", "--focus", "data scien", "--tracker", str(self.tmp / "n.csv"))
        self.assertEqual(sorted(row["key"] for row in out["selected"]), ["a", "c"])

    def test_all_flag_includes_every_status_but_skipped(self):
        self.write_state(
            {
                "a": entry(status="ranked"),
                "b": entry(status="expired"),
                "c": entry(status="skipped"),
                "d": entry(status="new"),
            }
        )
        out = self.run_tool("candidates", "--all", "--tracker", str(self.tmp / "n.csv"))
        self.assertEqual(sorted(row["key"] for row in out["selected"]), ["a", "b", "d"])

    def test_missing_state_file_exits_nonzero(self):
        proc = subprocess.run(
            [sys.executable, str(TOOL), "candidates", "--state", str(self.tmp / "nope.json"),
             "--tracker", str(self.tmp / "n.csv")],
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not found", proc.stderr + proc.stdout)


class UnicodeMatching(RankStateCase):
    """Tracker exclusion folded text to ASCII, which deletes Hangul entirely.

    `norm()` kept only [a-z0-9], so every Korean company and every Korean role
    normalized to the empty string: one Korean row in job_search_tracker.csv
    excluded *every* Korean candidate from the run, and two different Korean
    employers were indistinguishable to the matcher.
    """

    def test_korean_tracker_rows_exclude_only_their_own_company(self):
        self.write_state(
            {
                "kakao": entry(company="카카오", title="백엔드 개발자"),
                "naver": entry(company="네이버", title="백엔드 개발자"),
            }
        )
        tracker = self.tmp / "tracker.csv"
        tracker.write_text("date,company,role\n2026-08-01,카카오,백엔드 개발자\n", encoding="utf-8")
        out = self.run_tool("candidates", "--tracker", str(tracker))
        self.assertEqual([row["key"] for row in out["selected"]], ["naver"])
        self.assertEqual(out["excluded_by_tracker"], 1)

    def test_focus_matches_korean_text_across_normal_forms(self):
        """`--focus` folded with .lower() only, so a composed 개발자 needle
        missed a decomposed 개발자 title: the filter silently returned nothing
        on exactly the postings it was pointed at."""
        self.write_state(
            {
                "dev": entry(company="카카오", title=unicodedata.normalize("NFD", "백엔드 개발자")),
                "design": entry(company="네이버", title="프로덕트 디자이너"),
            }
        )
        out = self.run_tool(
            "candidates", "--focus", unicodedata.normalize("NFC", "개발자"),
            "--tracker", str(self.tmp / "n.csv"),
        )
        self.assertEqual([row["key"] for row in out["selected"]], ["dev"])

    def test_decomposed_hangul_still_matches_the_composed_tracker_row(self):
        self.write_state({"kakao": entry(company=unicodedata.normalize("NFD", "카카오"), title="개발자")})
        tracker = self.tmp / "tracker.csv"
        tracker.write_text("date,company,role\n2026-08-01,카카오,개발자\n", encoding="utf-8")
        out = self.run_tool("candidates", "--tracker", str(tracker))
        self.assertEqual(out["selected"], [])
        self.assertEqual(out["excluded_by_tracker"], 1)


class RequestLocale(RankStateCase):
    """`--request-language` / `--market`: an explicit, per-run search locale.

    Korean-first ordering is a *grouping* applied before `--limit`, so the
    batch that gets scored is the Korean one rather than whatever the state
    file happened to list first. Nothing about it touches fit thresholds, the
    Language Gate, or the vetoes.
    """

    def korean_state(self):
        self.write_state(
            {
                "dk1": entry(company="Acme", title="Backend Developer", location="Aarhus, Denmark"),
                "ko1": entry(company="카카오", title="백엔드 개발자", location="서울"),
                "kr-en": entry(company="Coupang", title="Backend Developer", location="Seoul, South Korea"),
                "dk2": entry(company="Beta", title="Frontend Developer", location="Copenhagen, Denmark"),
                "ko2": entry(company="네이버", title="프론트엔드 개발자", location="성남"),
            }
        )

    def test_korean_postings_come_first_and_the_limit_cuts_the_rest(self):
        self.korean_state()
        out = self.run_tool(
            "candidates", "--request-language", "Korean", "--limit", "3",
            "--tracker", str(self.tmp / "n.csv"),
        )
        self.assertEqual(
            [row["key"] for row in out["selected"]],
            ["ko1", "ko2", "kr-en"],
            "preference must be applied BEFORE --limit, or the limit decides the batch",
        )
        self.assertEqual(out["eligible"], 5)
        self.assertEqual(out["deferred"], 2)
        self.assertEqual(out["locale"], {"language": "ko", "market": "KR", "market_source": "inferred"})

    def test_the_selected_rows_say_which_group_they_landed_in(self):
        self.korean_state()
        out = self.run_tool(
            "candidates", "--request-language", "ko", "--limit", "0",
            "--tracker", str(self.tmp / "n.csv"),
        )
        tiers = {row["key"]: row["preference_tier"] for row in out["selected"]}
        self.assertEqual(tiers["ko1"], 0)
        self.assertEqual(tiers["kr-en"], 1)
        self.assertEqual(tiers["dk1"], 2)
        self.assertEqual(
            set(out["selected"][0]) - {"preference_tier"},
            {"key", "title", "company", "url", "portal", "deadline", "posted_date"},
            "the locale adds exactly one field to the projection, nothing else",
        )

    def test_an_explicit_market_leads_over_the_requested_language(self):
        """A Korean-speaking user searching Denmark must not get Korean jobs
        first: the market was stated outright, the language only says which
        postings to prefer inside it."""
        self.korean_state()
        out = self.run_tool(
            "candidates", "--request-language", "ko", "--market", "DK", "--limit", "0",
            "--tracker", str(self.tmp / "n.csv"),
        )
        self.assertEqual(out["locale"], {"language": "ko", "market": "DK", "market_source": "explicit"})
        self.assertEqual(
            [row["key"] for row in out["selected"]][:2],
            ["dk1", "dk2"],
            "an explicit market decides the first group",
        )
        tiers = {row["key"]: row["preference_tier"] for row in out["selected"]}
        self.assertEqual(tiers["dk1"], 0)
        self.assertEqual(tiers["ko1"], 1)
        self.assertEqual(tiers["kr-en"], 2)

    def test_a_korean_posting_advertised_overseas_is_not_a_korean_market_hit(self):
        """Korean boards advertise overseas roles. The place the posting names
        beats the domain it was found on, so a Seoul-portal job in San Jose
        ranks as US - not as a Korean-market hit."""
        self.write_state(
            {
                "kr": entry(company="Coupang", title="Backend Developer", location="Seoul, South Korea",
                            url="https://www.saramin.co.kr/zf_user/jobs/1"),
                "us": entry(company="Coupang", title="Backend Developer", location="San Jose, United States",
                            url="https://www.saramin.co.kr/zf_user/jobs/2"),
            }
        )
        out = self.run_tool(
            "candidates", "--market", "US", "--limit", "0", "--tracker", str(self.tmp / "n.csv")
        )
        tiers = {row["key"]: row["preference_tier"] for row in out["selected"]}
        self.assertEqual(tiers["us"], 0)
        self.assertEqual(tiers["kr"], 2)

    def test_without_a_locale_selection_is_byte_for_byte_what_it_was(self):
        self.korean_state()
        out = self.run_tool("candidates", "--limit", "0", "--tracker", str(self.tmp / "n.csv"))
        self.assertEqual(
            [row["key"] for row in out["selected"]],
            ["dk1", "ko1", "kr-en", "dk2", "ko2"],
            "a generic run keeps state-file order - no locale, no reordering",
        )
        self.assertNotIn("preference_tier", out["selected"][0])
        self.assertIsNone(out["locale"]["language"])

    def test_an_unrecognized_request_language_fails_loudly(self):
        self.write_state({"a": entry()})
        proc = subprocess.run(
            [sys.executable, str(TOOL), "candidates", "--request-language", "kore4n",
             "--state", str(self.state), "--tracker", str(self.tmp / "n.csv")],
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("kore4n", proc.stderr + proc.stdout)


class Sweep(RankStateCase):
    def test_retires_past_deadlines_and_flags_the_closing_ones(self):
        self.write_state(
            {
                "past": entry(status="ranked", deadline="2026-09-01"),
                "soon": entry(status="ranked", deadline="2026-09-07"),
                "later": entry(status="ranked", deadline="2026-12-01"),
            }
        )
        out = self.run_tool("sweep", "--write")
        self.assertEqual([r["key"] for r in out["newly_expired"]], ["past"])
        self.assertEqual([r["key"] for r in out["closing_soon"]], ["soon"])
        self.assertEqual(self.read_state()["past"]["status"], "expired")
        self.assertEqual(self.read_state()["soon"]["status"], "ranked")

    def test_entries_without_a_deadline_are_left_alone(self):
        """The majority case. Inferring one from first_seen would retire jobs
        on a date nobody set."""
        self.write_state({"a": entry(status="ranked", deadline=None), "b": entry(status="ranked")})
        out = self.run_tool("sweep", "--write")
        self.assertEqual(out["newly_expired"], [])
        self.assertTrue(all(e["status"] == "ranked" for e in self.read_state().values()))

    def test_non_iso_deadlines_are_reported_not_compared(self):
        """Portals have shipped "ASAP", DD.MM.YYYY and free text into this field."""
        self.write_state(
            {
                "asap": entry(status="ranked", deadline="ASAP", portal="jobindex-search"),
                "euro": entry(status="ranked", deadline="31.08.2026", portal="jobbank-search"),
            }
        )
        out = self.run_tool("sweep", "--write")
        self.assertEqual(out["newly_expired"], [])
        self.assertEqual(
            sorted(r["portal"] for r in out["unparseable_deadlines"]),
            ["jobbank-search", "jobindex-search"],
            "a bad stored value is traced back to the portal that wrote it",
        )
        self.assertTrue(all(e["status"] == "ranked" for e in self.read_state().values()))

    def test_only_ranked_entries_are_swept_and_excluded_keys_are_skipped(self):
        self.write_state(
            {
                "new_past": entry(status="new", deadline="2026-09-01"),
                "rescored": entry(status="ranked", deadline="2026-09-01"),
                "other": entry(status="ranked", deadline="2026-09-01"),
            }
        )
        out = self.run_tool("sweep", "--write", "--exclude", "rescored")
        self.assertEqual([r["key"] for r in out["newly_expired"]], ["other"])
        self.assertEqual(out["swept"], 1)
        self.assertEqual(self.read_state()["new_past"]["status"], "new")

    def test_without_write_nothing_is_persisted(self):
        self.write_state({"past": entry(status="ranked", deadline="2026-09-01")})
        out = self.run_tool("sweep")
        self.assertEqual([r["key"] for r in out["newly_expired"]], ["past"])
        self.assertFalse(out["written"])
        self.assertEqual(self.read_state()["past"]["status"], "ranked")


class Apply(RankStateCase):
    def results(self, payload):
        path = self.tmp / "results.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def test_weights_bands_and_persisted_fields(self):
        self.write_state({"a": entry()})
        out = self.run_tool(
            "apply",
            "--results",
            self.results(
                [
                    {
                        "key": "a",
                        "status": "scored",
                        "scores": {"technical": 80, "experience": 60, "behavioral": 70, "career": 75},
                        "location_verdict": "PASS",
                        "language_gate": "PASS",
                        "deadline": "2026-09-05",
                        "strengths": ["s1", "s2"],
                        "gaps": ["g1"],
                    }
                ]
            ),
        )
        stored = self.read_state()["a"]
        # 80*.30 + 60*.25 + 70*.15 + 75*.30 = 72
        self.assertEqual(stored["rank_score"], 72)
        self.assertEqual(stored["rank_verdict"], "Good Fit")
        self.assertEqual(stored["status"], "ranked")
        self.assertEqual(stored["rank_date"], TODAY)
        self.assertEqual(stored["strengths"], ["s1", "s2"])
        self.assertEqual(stored["gaps"], ["g1"])
        self.assertEqual(stored["deadline"], "2026-09-05")
        self.assertTrue(out["ranked"][0]["urgent"], "a deadline inside 7 days carries the urgency marker")

    def test_expired_status_is_written_through(self):
        self.write_state({"a": entry()})
        out = self.run_tool("apply", "--results", self.results([{"key": "a", "status": "expired"}]))
        self.assertEqual(self.read_state()["a"]["status"], "expired")
        self.assertEqual([r["key"] for r in out["expired"]], ["a"])

    def test_null_deadline_does_not_erase_a_stored_one(self):
        """Absence is not a correction: a fetch that degraded to a listing page
        returns no deadline, and blanking the stored date would also put the
        entry out of the sweep's reach forever."""
        self.write_state({"a": entry(deadline="2026-10-01")})
        self.run_tool(
            "apply",
            "--results",
            self.results(
                [
                    {
                        "key": "a",
                        "status": "scored",
                        "scores": {"technical": 50, "experience": 50, "behavioral": 50, "career": 50},
                        "deadline": None,
                    }
                ]
            ),
        )
        self.assertEqual(self.read_state()["a"]["deadline"], "2026-10-01")

    def test_legacy_verdict_stored_under_location_is_migrated(self):
        self.write_state({"a": entry(location="FLAG")})
        self.run_tool(
            "apply",
            "--results",
            self.results(
                [
                    {
                        "key": "a",
                        "status": "scored",
                        "scores": {"technical": 50, "experience": 50, "behavioral": 50, "career": 50},
                    }
                ]
            ),
        )
        stored = self.read_state()["a"]
        self.assertEqual(stored["location_verdict"], "FLAG")
        self.assertNotIn("location", stored, "a legacy verdict is moved, never left to read as a place")

    def test_a_real_place_in_location_survives(self):
        self.write_state({"a": entry(location="Athens, Greece")})
        self.run_tool(
            "apply",
            "--results",
            self.results(
                [
                    {
                        "key": "a",
                        "status": "scored",
                        "scores": {"technical": 50, "experience": 50, "behavioral": 50, "career": 50},
                        "location_verdict": "PASS",
                    }
                ]
            ),
        )
        self.assertEqual(self.read_state()["a"]["location"], "Athens, Greece")

    def test_vetoed_rows_are_separated_from_the_ranking(self):
        self.write_state({"a": entry(), "b": entry(), "c": entry()})
        scores = {"technical": 90, "experience": 90, "behavioral": 90, "career": 90}
        out = self.run_tool(
            "apply",
            "--results",
            self.results(
                [
                    {"key": "a", "status": "scored", "scores": scores, "location_verdict": "FAIL"},
                    {"key": "b", "status": "scored", "scores": scores, "language_gate": "FAIL",
                     "language_note": "requires fluent Polish"},
                    {"key": "c", "status": "scored", "scores": {"technical": 40, "experience": 40,
                                                                "behavioral": 40, "career": 40}},
                ]
            ),
        )
        self.assertEqual(sorted(r["key"] for r in out["vetoed"]), ["a", "b"])
        self.assertEqual([r["key"] for r in out["ranked"]], ["c"])
        self.assertEqual(self.read_state()["b"]["language_note"], "requires fluent Polish")

    def test_language_note_is_dropped_when_gate_passes(self):
        self.write_state({"a": entry(language_note="stale note from a prior run")})
        self.run_tool(
            "apply",
            "--results",
            self.results(
                [
                    {
                        "key": "a",
                        "status": "scored",
                        "scores": {"technical": 50, "experience": 50, "behavioral": 50, "career": 50},
                        "language_gate": "PASS",
                    }
                ]
            ),
        )
        self.assertNotIn("language_note", self.read_state()["a"])

    def test_strengths_and_gaps_are_capped_and_stored_verbatim(self):
        self.write_state({"a": entry()})
        self.run_tool(
            "apply",
            "--results",
            self.results(
                [
                    {
                        "key": "a",
                        "status": "scored",
                        "scores": {"technical": 50, "experience": 50, "behavioral": 50, "career": 50},
                        "strengths": ["one", "two", "three", "four"],
                        "gaps": ["<script>not sanitized on purpose, stored as plain data</script>"],
                    }
                ]
            ),
        )
        stored = self.read_state()["a"]
        self.assertEqual(len(stored["strengths"]), 3, "at most 3 bullets, matching the spec")
        self.assertEqual(
            stored["gaps"],
            ["<script>not sanitized on purpose, stored as plain data</script>"],
            "gaps are stored verbatim - untrusted data, never reformatted",
        )

    def test_all_replaces_rather_than_accumulates_arrays(self):
        self.write_state({"a": entry(status="ranked", strengths=["old strength"], gaps=["old gap"])})
        self.run_tool(
            "apply",
            "--results",
            self.results(
                [
                    {
                        "key": "a",
                        "status": "scored",
                        "scores": {"technical": 50, "experience": 50, "behavioral": 50, "career": 50},
                        "strengths": ["new strength"],
                        "gaps": ["new gap"],
                    }
                ]
            ),
        )
        stored = self.read_state()["a"]
        self.assertEqual(stored["strengths"], ["new strength"])
        self.assertEqual(stored["gaps"], ["new gap"])

    def test_unknown_key_is_an_error_not_a_silent_drop(self):
        self.write_state({"a": entry()})
        out = self.run_tool(
            "apply", "--results", self.results([{"key": "ghost", "status": "scored", "scores": {}}]), expect=1
        )
        self.assertEqual(out["errors"][0]["key"], "ghost")

    def test_missing_score_dimension_is_an_error(self):
        self.write_state({"a": entry()})
        out = self.run_tool(
            "apply",
            "--results",
            self.results([{"key": "a", "status": "scored", "scores": {"technical": 80}}]),
            expect=1,
        )
        self.assertIn("experience", out["errors"][0]["error"])
        self.assertEqual(self.read_state()["a"]["status"], "new", "a rejected result never half-writes an entry")

    def test_dry_run_prints_but_never_writes(self):
        self.write_state({"a": entry()})
        self.run_tool(
            "apply",
            "--results",
            self.results(
                [{"key": "a", "status": "scored",
                  "scores": {"technical": 50, "experience": 50, "behavioral": 50, "career": 50}}]
            ),
            "--dry-run",
        )
        self.assertEqual(self.read_state()["a"]["status"], "new")

    def test_posting_language_and_verified_place_are_persisted_apart_from_the_gate(self):
        """Three different facts that used to be one field or no field at all:
        what language the posting is written in, which market it is in, and
        where the scoring agent actually read the job to be - none of which is
        the Language Gate's PASS/FAIL verdict about the candidate."""
        self.write_state({"a": entry()})
        out = self.run_tool(
            "apply",
            "--results",
            self.results(
                [
                    {
                        "key": "a",
                        "status": "scored",
                        "scores": {"technical": 50, "experience": 50, "behavioral": 50, "career": 50},
                        "language": "Korean",
                        "market": "South Korea",
                        "location_verified": "서울 강남구",
                        "language_gate": "FLAG",
                        "language_note": "posting asks for business-level English",
                    }
                ]
            ),
        )
        stored = self.read_state()["a"]
        self.assertEqual(stored["posting_language"], "ko", "normalized to a canonical short tag")
        self.assertEqual(stored["market"], "KR")
        self.assertEqual(stored["location_verified"], "서울 강남구")
        self.assertEqual(stored["language_gate"], "FLAG", "the gate is the agent's, untouched")
        self.assertEqual(out["ranked"][0]["posting_language"], "ko")
        self.assertEqual(out["ranked"][0]["market"], "KR")

    def test_an_absent_posting_language_is_never_guessed(self):
        self.write_state({"a": entry()})
        self.run_tool(
            "apply",
            "--results",
            self.results(
                [{"key": "a", "status": "scored",
                  "scores": {"technical": 50, "experience": 50, "behavioral": 50, "career": 50}}]
            ),
        )
        stored = self.read_state()["a"]
        for field in ("posting_language", "market", "location_verified"):
            self.assertNotIn(field, stored, f"{field} must stay absent rather than be inferred")

    def test_the_request_language_never_becomes_a_proficiency_claim(self):
        """Asking for Korean postings says nothing about the candidate's Korean.
        A `--request-language ko` run must leave the Language Gate exactly as
        the scoring agent returned it, and write no proficiency field."""
        self.write_state({"a": entry()})
        self.run_tool(
            "apply",
            "--request-language", "ko",
            "--results",
            self.results(
                [{"key": "a", "status": "scored", "language": "ko",
                  "scores": {"technical": 50, "experience": 50, "behavioral": 50, "career": 50},
                  "language_gate": "FAIL", "language_note": "requires native Korean"}]
            ),
        )
        stored = self.read_state()["a"]
        self.assertEqual(stored["language_gate"], "FAIL")
        self.assertEqual(stored["language_note"], "requires native Korean")
        self.assertFalse(
            [k for k in stored if "proficiency" in k or k == "language_level"],
            "the run's request language is a search instruction, never a declared level",
        )

    def test_korean_rows_are_grouped_first_not_merely_tie_broken(self):
        """A lower-scoring Korean posting outranks a higher-scoring foreign one
        in a Korean run - grouping, not a tiebreak - while the score, the band
        and the vetoes are untouched."""
        self.write_state(
            {
                "ko-low": entry(company="카카오", title="백엔드 개발자", location="서울"),
                "dk-high": entry(company="Acme", title="Backend Developer", location="Aarhus, Denmark"),
                "ko-vetoed": entry(company="네이버", title="프론트엔드 개발자", location="성남"),
            }
        )
        low = {"technical": 40, "experience": 40, "behavioral": 40, "career": 40}
        high = {"technical": 90, "experience": 90, "behavioral": 90, "career": 90}
        out = self.run_tool(
            "apply",
            "--request-language", "ko",
            "--results",
            self.results(
                [
                    {"key": "ko-low", "status": "scored", "scores": low, "language": "ko"},
                    {"key": "dk-high", "status": "scored", "scores": high},
                    {"key": "ko-vetoed", "status": "scored", "scores": high, "language": "ko",
                     "location_verdict": "FAIL"},
                ]
            ),
        )
        self.assertEqual([r["key"] for r in out["ranked"]], ["ko-low", "dk-high"])
        self.assertEqual(out["ranked"][0]["score"], 40, "grouping never edits the score")
        self.assertEqual(out["ranked"][1]["verdict"], "Strong Fit", "bands are untouched")
        self.assertEqual([r["key"] for r in out["vetoed"]], ["ko-vetoed"],
                         "a veto still wins over the preferred group")
        self.assertEqual(out["locale"]["market"], "KR")

    def test_without_a_locale_the_ranking_is_still_sorted_by_score_alone(self):
        self.write_state({"ko": entry(company="카카오", title="백엔드 개발자"), "dk": entry()})
        low = {"technical": 40, "experience": 40, "behavioral": 40, "career": 40}
        high = {"technical": 90, "experience": 90, "behavioral": 90, "career": 90}
        out = self.run_tool(
            "apply",
            "--results",
            self.results(
                [
                    {"key": "ko", "status": "scored", "scores": low},
                    {"key": "dk", "status": "scored", "scores": high},
                ]
            ),
        )
        self.assertEqual([r["key"] for r in out["ranked"]], ["dk", "ko"])

    def test_re_scoring_an_already_ranked_job_is_idempotent(self):
        """Re-running /rank never re-scores an already-ranked job unless --all
        says so (Step 4), but if it does score one again, apply must produce
        the same result deterministically rather than accumulating state."""
        self.write_state({"a": entry(status="ranked", rank_score=40, strengths=["old"])})
        scores = {"technical": 90, "experience": 90, "behavioral": 90, "career": 90}
        self.run_tool(
            "apply", "--results",
            self.results([{"key": "a", "status": "scored", "scores": scores, "strengths": ["new"]}]),
        )
        stored = self.read_state()["a"]
        self.assertEqual(stored["rank_score"], 90)
        self.assertEqual(stored["strengths"], ["new"])


if __name__ == "__main__":
    unittest.main()
