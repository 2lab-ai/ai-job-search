"""Tests for tools/search_locale.py - the shared per-run locale helper.

A run that targets Korea has to say so explicitly. Inferring it from the
candidate's profile is what this helper exists to avoid: the profile's
Languages table is a statement of *professional proficiency*, and the request
language ("search Korean jobs for me") says nothing about proficiency at all.
So the language of a run is an argument, never a deduction from the profile,
and it never touches `04-job-evaluation.md`'s Language Gate.

Pinned here:
  * language and market aliases normalize to one canonical short tag, in ASCII
    names, ISO codes and the language's own script
  * an explicit market always beats the market inferred from the language
  * preference is a *grouping*, stable within each group, never a score change
  * text folding keeps Hangul (and every other script) instead of deleting it
"""
import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import search_locale  # noqa: E402


class NormalizeLanguage(unittest.TestCase):
    def test_iso_codes_and_english_names(self):
        for value in ("ko", "KO", "kor", "ko-KR", "ko_KR", "Korean", " korean "):
            self.assertEqual(search_locale.normalize_language(value), "ko", value)
        for value in ("en", "EN", "eng", "en-US", "English"):
            self.assertEqual(search_locale.normalize_language(value), "en", value)

    def test_names_written_in_the_language_itself(self):
        self.assertEqual(search_locale.normalize_language("한국어"), "ko")
        self.assertEqual(search_locale.normalize_language("영어"), "en")
        self.assertEqual(search_locale.normalize_language("dansk"), "da")

    def test_decomposed_hangul_normalizes_the_same_as_composed(self):
        self.assertEqual(
            search_locale.normalize_language(unicodedata.normalize("NFD", "한국어")),
            "ko",
        )

    def test_an_unknown_two_letter_tag_passes_through_lowercased(self):
        """A small alias table must not become the list of allowed languages."""
        self.assertEqual(search_locale.normalize_language("JA"), "ja")

    def test_unrecognized_values_are_none_never_guessed(self):
        for value in (None, "", "   ", "not a language", "kore4n"):
            self.assertIsNone(search_locale.normalize_language(value), value)


class NormalizeMarket(unittest.TestCase):
    def test_codes_and_names(self):
        for value in ("kr", "KR", "Korea", "South Korea", "Republic of Korea", "한국", "대한민국"):
            self.assertEqual(search_locale.normalize_market(value), "KR", value)
        self.assertEqual(search_locale.normalize_market("Denmark"), "DK")

    def test_unknown_two_letter_code_passes_through_uppercased(self):
        self.assertEqual(search_locale.normalize_market("jp"), "JP")

    def test_unrecognized_values_are_none(self):
        for value in (None, "", "somewhere"):
            self.assertIsNone(search_locale.normalize_market(value), value)


class ResolveLocale(unittest.TestCase):
    def test_korean_request_implies_the_korean_market(self):
        locale = search_locale.resolve_locale(request_language="Korean")
        self.assertEqual(locale["language"], "ko")
        self.assertEqual(locale["market"], "KR")
        self.assertEqual(locale["market_source"], "inferred")
        self.assertTrue(search_locale.is_active(locale))

    def test_an_explicit_market_beats_the_inferred_one(self):
        locale = search_locale.resolve_locale(request_language="ko", market="us")
        self.assertEqual(locale["language"], "ko")
        self.assertEqual(locale["market"], "US")
        self.assertEqual(locale["market_source"], "explicit")

    def test_a_market_alone_is_a_valid_locale(self):
        locale = search_locale.resolve_locale(market="KR")
        self.assertIsNone(locale["language"])
        self.assertEqual(locale["market"], "KR")
        self.assertTrue(search_locale.is_active(locale))

    def test_no_arguments_is_an_inactive_locale(self):
        locale = search_locale.resolve_locale()
        self.assertFalse(search_locale.is_active(locale))
        self.assertIsNone(locale["language"])
        self.assertIsNone(locale["market"])

    def test_an_unrecognized_request_language_raises_rather_than_defaulting(self):
        with self.assertRaises(ValueError):
            search_locale.resolve_locale(request_language="kore4n")

    def test_a_market_passed_as_the_language_is_rejected_with_the_right_flag(self):
        """`--request-language KR` used to resolve to the language "kr" with no
        market, which silently put *every* posting in the bottom group - a
        typo that looked like a working run. A country name or code is refused,
        naming the flag that takes it."""
        for value in ("KR", "Korea", "대한민국", "dk", "USA"):
            with self.assertRaises(ValueError, msg=value) as caught:
                search_locale.resolve_locale(request_language=value)
            self.assertIn("--market", str(caught.exception), value)

    def test_language_codes_that_are_not_known_markets_still_pass_through(self):
        """The rejection is for recognized markets only - it must not become a
        whitelist of languages."""
        self.assertEqual(search_locale.resolve_locale(request_language="ja")["language"], "ja")
        self.assertEqual(search_locale.resolve_locale(request_language="da")["language"], "da")

    def test_a_locale_never_carries_a_proficiency_claim(self):
        """The request language is a search instruction, not a CV statement."""
        locale = search_locale.resolve_locale(request_language="ko")
        self.assertEqual(
            set(locale),
            {"language", "market", "market_source"},
            "a locale carries what to search, never how well the user speaks it",
        )


class FoldText(unittest.TestCase):
    def test_hangul_survives_instead_of_being_deleted(self):
        self.assertEqual(search_locale.fold_text("카카오"), "카카오")
        self.assertNotEqual(search_locale.fold_text("카카오"), search_locale.fold_text("네이버"))

    def test_decomposed_and_composed_hangul_fold_to_the_same_value(self):
        self.assertEqual(
            search_locale.fold_text(unicodedata.normalize("NFD", "개발자")),
            search_locale.fold_text(unicodedata.normalize("NFC", "개발자")),
        )

    def test_ascii_folding_is_unchanged(self):
        self.assertEqual(search_locale.fold_text("Acme Corp, LLC"), "acmecorpllc")
        self.assertEqual(search_locale.fold_text(None), "")


class DetectSignals(unittest.TestCase):
    def test_hangul_text_reads_as_korean(self):
        self.assertEqual(search_locale.script_language("백엔드 개발자"), "ko")
        self.assertEqual(search_locale.script_language("안드로이드 앱(악성코드) 분석가"), "ko")

    def test_latin_text_is_not_guessed_at(self):
        """Latin script spans dozens of languages - guessing one would be a
        fabricated signal, so the helper returns nothing."""
        self.assertIsNone(search_locale.script_language("Backend Developer"))
        self.assertIsNone(search_locale.script_language(""))

    def test_entry_language_prefers_the_stored_value_over_the_script(self):
        self.assertEqual(
            search_locale.entry_language({"posting_language": "en", "title": "백엔드 개발자"}),
            "en",
        )
        self.assertEqual(search_locale.entry_language({"title": "백엔드 개발자"}), "ko")
        self.assertIsNone(search_locale.entry_language({"title": "Backend Developer"}))

    def test_entry_market_prefers_a_verified_value_then_place_text_then_the_host(self):
        self.assertEqual(search_locale.entry_market({"market": "korea"}), "KR")
        self.assertEqual(search_locale.entry_market({"location_verified": "서울 강남구"}), "KR")
        self.assertEqual(search_locale.entry_market({"location": "Seoul, South Korea"}), "KR")
        self.assertEqual(search_locale.entry_market({"location": "서울, 대한민국"}), "KR")
        self.assertEqual(
            search_locale.entry_market({"url": "https://www.saramin.co.kr/zf_user/jobs/x"}),
            "KR",
            "a ccTLD is the last-resort hint when the entry carries no place at all",
        )
        self.assertIsNone(search_locale.entry_market({"location": "Athens, Greece"}))

    def test_a_localized_portal_host_is_never_evidence_of_the_market(self):
        """kr.linkedin.com is a localized *domain*, not a market: it serves
        postings worldwide. Reading a market off it would file a Berlin job
        under Korea."""
        self.assertIsNone(search_locale.entry_market({"url": "https://kr.linkedin.com/jobs/view/1"}))

    def test_a_work_arrangement_is_not_a_place(self):
        """"Remote" answers a different question than "where".

        An entry with location_verified="Remote" and location="Seoul, South
        Korea" read as "a stated place that is not Korea" and dropped out of
        the Korean group entirely. Work-arrangement markers are skipped so the
        next field is consulted; they are evidence of a market either way.
        """
        self.assertEqual(
            search_locale.entry_market(
                {"location_verified": "Remote", "location": "Seoul, South Korea",
                 "url": "https://www.saramin.co.kr/zf_user/jobs/x"}
            ),
            "KR",
        )
        self.assertEqual(search_locale.entry_market({"location_verified": "재택근무", "location": "서울"}), "KR")
        self.assertEqual(search_locale.entry_market({"location_verified": "Remote (Seoul)"}), "KR")

    def test_an_unknown_real_place_still_stops_the_search(self):
        """The skip is for work arrangements only. A real place that maps to no
        known market must not fall through to the host - that is how a Berlin
        job on a .kr board would be filed under Korea."""
        self.assertIsNone(
            search_locale.entry_market(
                {"location": "Berlin, Germany", "url": "https://www.saramin.co.kr/zf_user/jobs/x"}
            )
        )

    def test_a_stated_place_overrides_the_portals_own_country(self):
        """Korean boards advertise overseas roles; the place the posting names
        wins over the domain it was found on."""
        self.assertEqual(
            search_locale.entry_market(
                {"url": "https://www.saramin.co.kr/zf_user/jobs/x", "location": "San Jose, United States"}
            ),
            "US",
        )
        self.assertEqual(
            search_locale.entry_market(
                {"url": "https://www.saramin.co.kr/zf_user/jobs/x",
                 "location": "Seoul",
                 "location_verified": "San Jose, United States"},
            ),
            "US",
            "the verified place the scoring agent read beats the scraped one",
        )


class PreferenceOrdering(unittest.TestCase):
    KO = {"title": "백엔드 개발자", "location": "서울", "url": "https://www.saramin.co.kr/x"}
    KR_EN = {"title": "Backend Developer", "location": "Seoul, South Korea", "url": "https://x/1"}
    OTHER = {"title": "Backend Developer", "location": "Aarhus, Denmark", "url": "https://x/2"}

    US = {"title": "Backend Developer", "location": "San Jose, United States",
          "url": "https://www.saramin.co.kr/zf_user/jobs/x"}

    def test_language_match_outranks_market_match_outranks_the_rest(self):
        locale = search_locale.resolve_locale(request_language="ko")
        self.assertEqual(search_locale.preference_tier(self.KO, locale), 0)
        self.assertEqual(search_locale.preference_tier(self.KR_EN, locale), 1)
        self.assertEqual(search_locale.preference_tier(self.OTHER, locale), 2)

    def test_an_explicit_market_outranks_the_requested_language(self):
        """A Korean speaker searching the US market wants US postings first.
        The market was stated; the language was only a search instruction, so
        an explicit market leads and the language orders what is left."""
        locale = search_locale.resolve_locale(request_language="ko", market="US")
        self.assertEqual(search_locale.preference_tier(self.US, locale), 0)
        self.assertEqual(search_locale.preference_tier(self.KO, locale), 1)
        self.assertEqual(search_locale.preference_tier(self.OTHER, locale), 2)

    def test_an_inactive_locale_puts_everything_in_one_group(self):
        locale = search_locale.resolve_locale()
        for entry in (self.KO, self.KR_EN, self.OTHER):
            self.assertEqual(search_locale.preference_tier(entry, locale), 0)

    def test_sorting_is_stable_within_a_group(self):
        locale = search_locale.resolve_locale(request_language="ko")
        rows = [
            {"id": "other-1", **self.OTHER},
            {"id": "ko-1", **self.KO},
            {"id": "other-2", **self.OTHER},
            {"id": "kr-en", **self.KR_EN},
            {"id": "ko-2", **self.KO},
        ]
        ordered = search_locale.sort_by_preference(rows, locale)
        self.assertEqual(
            [row["id"] for row in ordered],
            ["ko-1", "ko-2", "kr-en", "other-1", "other-2"],
            "preference regroups rows; it never reorders within a group",
        )

    def test_an_inactive_locale_leaves_the_order_untouched(self):
        locale = search_locale.resolve_locale()
        rows = [{"id": "a", **self.OTHER}, {"id": "b", **self.KO}]
        self.assertEqual([r["id"] for r in search_locale.sort_by_preference(rows, locale)], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
