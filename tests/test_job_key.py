"""Tests for tools/job_key.py - the canonical seen_jobs.json key function.

/scrape's key rule was prose only, so runs slugified inconsistently and the
state file accumulated two failures: keys carrying "/", "," and "&" that break
the archive-folder path `/apply`/`/outcome` derive from company+role, and the
same job stored twice under two different truncations of a long title. These
pin the fix - a pure, deterministic function of company+title(+url) - and the
audit that finds both failure classes in an existing file.
"""
import json
import subprocess
import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from job_key import is_canonical, is_legacy_shape, make_key, slugify  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "job_key.py"


class Slugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Acme Corp"), "acme-corp")

    def test_strips_punctuation_that_breaks_paths(self):
        self.assertEqual(slugify("Ops Consulting, LLC"), "ops-consulting-llc")
        self.assertEqual(slugify("Penetration Tester / Red Teamer"), "penetration-tester-red-teamer")
        self.assertEqual(slugify("Junior Cybersecurity Analyst (OT/IoT)"), "junior-cybersecurity-analyst-ot-iot")

    def test_non_latin_script_reduces_to_empty(self):
        self.assertEqual(slugify("시큐리온"), "")
        self.assertEqual(slugify("Код Безопасности"), "")


class MakeKey(unittest.TestCase):
    def test_shape(self):
        key = make_key("Acme Corp", "SOC Analyst (L2)")
        self.assertEqual(key, "acme-corp_soc-analyst-l2")
        self.assertTrue(is_canonical(key))

    def test_deterministic_across_calls(self):
        title = "Cyber Intelligence Center Security Analyst with an unusually long title"
        self.assertEqual(make_key("Deloitte", title), make_key("Deloitte", title))

    def test_long_titles_never_collide_after_truncation(self):
        """The bug that produced two Deloitte entries for one posting: two
        runs truncated the same long title at different points. A hash of the
        full slug makes truncation deterministic instead of lossy."""
        a = make_key("Deloitte", "Cyber Intelligence Center Security Analyst with trailing text A")
        b = make_key("Deloitte", "Cyber Intelligence Center Security Analyst with trailing text B")
        self.assertNotEqual(a, b)

    def test_non_latin_title_falls_back_to_the_portal_job_id(self):
        key = make_key(
            "SecuriON",
            "안드로이드 앱(악성코드) 분석가 채용",
            url="https://kr.linkedin.com/jobs/view/x-4461771225",
        )
        self.assertEqual(key, "securion_4461771225")

    def test_non_latin_title_with_no_url_id_still_produces_a_canonical_key(self):
        key = make_key("SecuriON", "안드로이드 앱 분석가", url="")
        self.assertTrue(is_canonical(key))
        self.assertNotEqual(key, "securion_")

    def test_non_latin_company_falls_back_without_producing_a_bare_prefix(self):
        key = make_key("Код Безопасности", "Malware Analytic", url="")
        self.assertTrue(is_canonical(key))
        self.assertFalse(key.startswith("_"))


class NonLatinKeysStayDistinctAndStable(unittest.TestCase):
    """A non-Latin posting must still get a key of its own.

    `slugify` drops every non-ASCII character, so before this fix two different
    Korean employers collapsed onto the same key: make_key("카카오", "개발자",
    <url with id 123456>) and make_key("네이버", "개발자", <same id>) both
    produced "unknown-company_123456" - one entry for two companies, which is
    the exact dedup failure the key function exists to prevent.

    The key itself stays ASCII: it doubles as the archive folder stem that
    `/apply` and `/outcome` derive, so Hangul never enters it. Distinctness
    comes from a hash of the NFC-normalized original text instead.
    """

    def test_two_korean_companies_do_not_collapse_onto_one_key(self):
        kakao = make_key("카카오", "개발자", url="https://kr.example.com/jobs/123456")
        naver = make_key("네이버", "개발자", url="https://kr.example.com/jobs/123456")
        self.assertNotEqual(kakao, naver)
        self.assertTrue(is_canonical(kakao) and is_canonical(naver))
        self.assertNotIn("unknown-company", kakao)

    def test_two_korean_titles_at_one_company_do_not_collapse(self):
        a = make_key("카카오", "백엔드 개발자", url="")
        b = make_key("카카오", "프론트엔드 개발자", url="")
        self.assertNotEqual(a, b)

    def test_a_key_survives_nfc_nfd_normalization_differences(self):
        """Portals ship both forms of Hangul; the same posting must key the
        same way whichever form this run happened to receive."""
        composed_company = unicodedata.normalize("NFC", "카카오")
        decomposed_company = unicodedata.normalize("NFD", "카카오")
        composed_title = unicodedata.normalize("NFC", "백엔드 개발자")
        decomposed_title = unicodedata.normalize("NFD", "백엔드 개발자")
        self.assertNotEqual(decomposed_company, composed_company)
        self.assertEqual(
            make_key(composed_company, composed_title),
            make_key(decomposed_company, decomposed_title),
        )

    def test_mixed_script_names_keep_their_non_latin_differentiator(self):
        """The sharper form of the same bug: a *surviving* Latin remnant hid it.

        slugify("회사A") is "a", not "", so the empty-slug fallback never fired
        and make_key("회사A", ...) and make_key("다른A", ...) both produced
        "a_123456" - two companies, one key again. Whenever transliteration
        drops non-Latin characters, the slug is disambiguated by a hash of the
        original text, so what the ASCII slug cannot carry is still in the key.
        """
        url = "https://example.test/jobs/123456"
        a = make_key("회사A", "백엔드 개발자", url)
        b = make_key("다른A", "백엔드 개발자", url)
        self.assertNotEqual(a, b)
        self.assertTrue(is_canonical(a) and is_canonical(b))
        self.assertTrue(a.startswith("a-"), f"the readable Latin remnant is kept, not discarded: {a}")

    def test_mixed_script_titles_stay_distinct_too(self):
        a = make_key("Acme", "백엔드 개발자 (Backend)")
        b = make_key("Acme", "프론트엔드 개발자 (Backend)")
        self.assertNotEqual(a, b)
        self.assertTrue(is_canonical(a))

    def test_mixed_script_keys_are_stable_across_nfc_and_nfd(self):
        for company, title in (("회사A", "백엔드 개발자 (Backend)"), ("Acme", "개발자 Developer")):
            composed = make_key(unicodedata.normalize("NFC", company), unicodedata.normalize("NFC", title))
            decomposed = make_key(unicodedata.normalize("NFD", company), unicodedata.normalize("NFD", title))
            self.assertEqual(composed, decomposed, f"{company}/{title} keyed differently by normal form")

    def test_compatibility_forms_the_slug_already_carries_are_not_lost(self):
        """The differentiator test has to use the same normal form the slug does.

        `slugify` runs NFKD, which turns ＮＨＮ into "NHN" and Ⅲ into "III", so
        nothing is lost - but the test ran NFC, saw characters named FULLWIDTH…
        and ROMAN NUMERAL…, judged them non-Latin and appended a hash. One
        employer then keyed two ways depending on which form the portal emitted:
        "nhn-4ee04c_backend-engineer" vs "nhn_backend-engineer".
        """
        self.assertEqual(make_key("ＮＨＮ", "Backend Engineer"), make_key("NHN", "Backend Engineer"))
        self.assertEqual(make_key("Acme", "Engineer Ⅲ"), make_key("Acme", "Engineer III"))
        self.assertEqual(make_key("NHN", "Backend Engineer"), "nhn_backend-engineer")

    def test_compatibility_folding_does_not_flatten_the_hangul_distinction(self):
        """The fix must not weaken the mixed-script case it sits next to."""
        self.assertNotEqual(make_key("회사A", "개발자"), make_key("다른A", "개발자"))
        self.assertNotEqual(
            make_key("㈜카카오", "Backend Engineer"),
            make_key("Acme", "Backend Engineer"),
            "NFKC expands ㈜ to (주), which is still Hangul and still a differentiator",
        )

    def test_latin_script_diacritics_are_not_a_lost_differentiator(self):
        """ø, ß and é are Latin script: they already transliterate, and hashing
        them would change the key of every existing Danish and German entry."""
        self.assertEqual(make_key("Søborg Data", "Udvikler"), "sborg-data_udvikler")
        self.assertEqual(make_key("Straße GmbH", "Entwickler"), "strae-gmbh_entwickler")
        self.assertEqual(make_key("Café Nord", "Barista"), "cafe-nord_barista")

    def test_the_key_stays_ascii_and_path_safe(self):
        for company, title in (("카카오", "백엔드 개발자"), ("회사A", "백엔드 개발자 (Backend)")):
            key = make_key(company, title, url="")
            self.assertEqual(key, key.encode("ascii", "ignore").decode("ascii"))

    def test_latin_keys_are_byte_for_byte_what_they_were(self):
        """Backward compatibility: an existing state file must keep matching."""
        self.assertEqual(make_key("Acme Corp", "SOC Analyst (L2)"), "acme-corp_soc-analyst-l2")
        self.assertEqual(make_key("Ops Consulting, LLC", "Malware Analyst"), "ops-consulting-llc_malware-analyst")
        self.assertEqual(
            make_key("SecuriON", "안드로이드 앱(악성코드) 분석가 채용",
                     url="https://kr.linkedin.com/jobs/view/x-4461771225"),
            "securion_4461771225",
        )
        self.assertEqual(make_key("", "Malware Analyst"), "unknown-company_malware-analyst")


class CanonicalAndLegacyShape(unittest.TestCase):
    def test_canonical_accepts_company_underscore_title(self):
        self.assertTrue(is_canonical("acme-corp_soc-analyst"))

    def test_canonical_rejects_path_breaking_characters(self):
        for bad in ("deloitte_junior-cybersecurity-analyst-(ot/iot)",
                    "neverhack-estonia_penetration-tester-/-red-teamer",
                    "ops-consulting,-llc_malware-analyst",
                    "",
                    "securion_"):
            self.assertFalse(is_canonical(bad), f"{bad!r} should not be canonical")

    def test_legacy_three_part_shape_is_flagged_separately_from_malformed(self):
        self.assertTrue(is_legacy_shape("nviso-security_soc-analyst_athens"))
        self.assertFalse(is_canonical("nviso-security_soc-analyst_athens"))
        # A malformed key (bad characters) is never also reported as legacy shape.
        self.assertFalse(is_legacy_shape("deloitte_junior-cybersecurity-analyst-(ot/iot)"))


class AuditCLI(unittest.TestCase):
    def run_audit(self, seen: dict) -> tuple[dict, int]:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"seen": seen}, fh)
            path = fh.name
        proc = subprocess.run(
            [sys.executable, str(TOOL), "--audit", path], capture_output=True, text=True
        )
        return json.loads(proc.stdout), proc.returncode

    def test_clean_state_exits_zero(self):
        report, code = self.run_audit({"acme_soc-analyst": {"company": "Acme", "title": "SOC Analyst"}})
        self.assertEqual(code, 0)
        self.assertEqual(report["malformed_keys"], [])
        self.assertEqual(report["duplicate_urls"], {})

    def test_malformed_key_exits_nonzero(self):
        report, code = self.run_audit(
            {"deloitte_junior-cybersecurity-analyst-(ot/iot)": {"company": "Deloitte", "title": "x"}}
        )
        self.assertEqual(code, 1)
        self.assertIn("deloitte_junior-cybersecurity-analyst-(ot/iot)", report["malformed_keys"])

    def test_duplicate_url_exits_nonzero(self):
        report, code = self.run_audit(
            {
                "a": {"company": "Acme", "title": "x", "url": "https://x/1"},
                "b": {"company": "Acme", "title": "y", "url": "https://x/1"},
            }
        )
        self.assertEqual(code, 1)
        self.assertIn("https://x/1", report["duplicate_urls"])

    def test_legacy_shape_alone_does_not_fail_the_audit(self):
        """Harmless drift, not damage - the sweep-worthy rewrite is a decision
        the maintainer makes, not something the audit enforces."""
        report, code = self.run_audit({"acme_soc-analyst_athens": {"company": "Acme", "title": "x"}})
        self.assertEqual(code, 0)
        self.assertIn("acme_soc-analyst_athens", report["legacy_three_part_keys"])


if __name__ == "__main__":
    unittest.main()
