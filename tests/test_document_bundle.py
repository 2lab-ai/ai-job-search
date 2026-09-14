"""Tests for tools/document_bundle.py and the multi-language document contract.

An application is no longer one CV and one cover letter. It is a *bundle*:
English plus whichever language the user actually asked in, each variant a
separate file with a language suffix. Three things break silently if that is
not pinned:

- **Language drift.** The set must be derived by one documented precedence
  (explicit request -> the language of the user's own request text -> the
  profile CV language -> English), never from the quoted posting, which is
  untrusted third-party text. A posting written in Korean does not mean the
  user wants Korean documents, and an English-only request must still cost
  two PDFs, not four.
- **Submitted vs generated.** The tracker holds one `cv_file` path, so a
  bundle forces a choice. Whichever variant the user actually sent is a fact
  only the user has; guessing it is how /outcome archives the wrong file as
  "what was submitted" and /interview then preps the user off a document the
  interviewer never read (the #443 failure, one level up).
- **Manifest as an untrusted read.** The manifest lives under
  `documents/applications/`, a folder the user edits by hand. If commands
  follow whatever path string it holds, a typo (or a pasted path) turns a
  document lookup into an arbitrary file read.

The command-file classes at the bottom follow the convention in
test_apply_records_application.py: assertions are scoped to the section that
owns the rule, because a whole-file `assertIn` for a word as common as
`language` passes on any unrelated mention and guards nothing.
"""
import fnmatch
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "document_bundle.py"
COMMANDS = REPO / ".claude" / "commands"
APPLY = COMMANDS / "apply.md"
OUTCOME = COMMANDS / "outcome.md"
INTERVIEW = COMMANDS / "interview.md"
HTML_REPORT = COMMANDS / "html-report.md"
SKILL = REPO / ".claude" / "skills" / "job-application-assistant" / "SKILL.md"
DOCS_README = REPO / "documents" / "README.md"

TODAY = "2026-09-14"

# Exit codes the commands branch on. 2 is not a failure - it is the tool
# saying "only the user knows this", which is what stops a guess.
EXIT_ERROR = 1
EXIT_NEEDS_USER = 2


def section(path, heading):
    """The body of one markdown section, up to the next heading of any depth."""
    text = path.read_text(encoding="utf-8")
    start = text.index(heading) + len(heading)
    rest = text[start:]
    end = re.search(r"^#{1,4} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


class ToolCase(unittest.TestCase):
    """Every subcommand is exercised through the real CLI, as in
    test_rank_state.py - the commands call it that way, so that is the
    surface worth pinning."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def run_tool(self, *args, expect=0, root=True):
        argv = [sys.executable, str(TOOL), *args]
        if root:
            argv += ["--root", str(self.root)]
        proc = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(
            proc.returncode, expect, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def languages(self, *args, expect=0):
        return self.run_tool("languages", *args, expect=expect)

    def plan(self, *args, expect=0):
        return self.run_tool(
            "plan", "--company", "Acme", "--role", "ML Engineer", *args, expect=expect
        )

    def manifest_path(self, stem="acme_ml_engineer"):
        return self.root / "documents" / "applications" / stem / "document_bundle.json"

    def draft_files(self, stem="acme_ml_engineer", languages=("ko", "en"), ext=".tex"):
        """What Step 5 leaves on disk. `mark-submitted` refuses a language
        whose documents were never written, so every submission test needs
        this first."""
        for language in languages:
            for folder, prefix in (("cv", "main"), ("cover_letters", "cover")):
                path = self.root / folder / f"{prefix}_{stem}_{language}{ext}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{folder} {language}", encoding="utf-8")

    def write_manifest(self, doc, stem="acme_ml_engineer"):
        path = self.manifest_path(stem)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path


class LanguageSetIsDerivedNotGuessed(ToolCase):
    """The precedence chain, one case per rung."""

    def test_explicit_request_is_honoured_and_english_is_always_added(self):
        out = self.languages("--requested", "Korean")
        self.assertEqual(out["languages"], ["ko", "en"])
        self.assertEqual(out["language_source"], "explicit")

    def test_any_explicit_language_is_honoured_not_just_korean(self):
        out = self.languages("--requested", "de")
        self.assertEqual(out["languages"], ["de", "en"])

    def test_english_request_does_not_produce_a_duplicate_variant(self):
        """en is deduped: 2 PDFs, not 4. The bundle is a set, not a pair."""
        out = self.languages("--requested", "English")
        self.assertEqual(out["languages"], ["en"])
        self.assertEqual(out["pdf_count"], 2)

    def test_a_non_english_request_costs_four_pdfs(self):
        self.assertEqual(self.languages("--requested", "ko")["pdf_count"], 4)

    def test_the_users_own_request_text_decides_when_nothing_is_explicit(self):
        out = self.languages("--request-text", "이 공고에 지원해줘")
        self.assertEqual(out["languages"], ["ko", "en"])
        self.assertEqual(out["language_source"], "request-text")

    def test_a_latin_request_falls_through_to_the_profile_cv_language(self):
        """Latin script cannot distinguish English from Danish, so the tool
        must decline to guess rather than label every Latin request English."""
        out = self.languages(
            "--request-text", "Please apply for this one", "--profile-language", "Danish"
        )
        self.assertEqual(out["languages"], ["da", "en"])
        self.assertEqual(out["language_source"], "profile")

    def test_english_is_the_last_resort(self):
        out = self.languages()
        self.assertEqual(out["languages"], ["en"])
        self.assertEqual(out["language_source"], "default")

    def test_the_posting_language_never_enters_the_generated_set(self):
        """apply.md Step 0's posting text is untrusted third-party data; a
        Korean posting is not a request for Korean documents."""
        out = self.languages("--posting-language", "ko")
        self.assertEqual(out["languages"], ["en"])

    def test_a_posting_language_outside_the_bundle_forces_a_confirmation(self):
        out = self.languages("--requested", "en", "--posting-language", "ko")
        self.assertTrue(out["confirm_before_submission"])
        self.assertIsNone(out["primary_language"])
        self.assertTrue(any("ko" in note for note in out["notes"]))

    def test_the_ad_language_only_suggests_it_never_confirms(self):
        """A Korean ad routinely asks for an English CV. The language the ad
        is written in is a hint about which variant to propose, never a
        statement of what the employer requires."""
        out = self.languages("--requested", "ko", "--posting-language", "ko")
        self.assertIsNone(out["primary_language"])
        self.assertEqual(out["suggested_language"], "ko")
        self.assertEqual(out["suggested_source"], "posting")
        self.assertTrue(out["confirm_before_submission"])

    def test_a_stated_document_requirement_outranks_the_ad_language(self):
        """"Please submit your CV in English" in a Korean ad is an explicit
        requirement, and it wins over the language the ad is written in."""
        out = self.languages(
            "--requested", "ko", "--posting-language", "ko", "--required-language", "en"
        )
        self.assertEqual(out["primary_language"], "en")
        self.assertEqual(out["primary_source"], "employer-requirement")
        self.assertFalse(out["confirm_before_submission"])

    def test_a_requirement_outside_the_bundle_is_disclosed_not_silently_met(self):
        out = self.languages("--requested", "ko", "--required-language", "da")
        self.assertIsNone(out["primary_language"])
        self.assertTrue(out["confirm_before_submission"])
        self.assertTrue(any("da" in note for note in out["notes"]))

    def test_the_users_submission_choice_outranks_everything(self):
        out = self.languages(
            "--requested", "ko", "--posting-language", "ko",
            "--required-language", "ko", "--submission-language", "en",
        )
        self.assertEqual(out["primary_language"], "en")
        self.assertEqual(out["primary_source"], "submission-choice")

    def test_an_unknown_posting_language_leaves_the_primary_unconfirmed(self):
        """Generated is not submitted: with two variants and nothing saying
        which the employer wants, the user has to be asked."""
        out = self.languages("--requested", "ko")
        self.assertIsNone(out["primary_language"])
        self.assertTrue(out["confirm_before_submission"])

    def test_a_single_language_bundle_needs_no_confirmation(self):
        out = self.languages("--requested", "en")
        self.assertEqual(out["primary_language"], "en")
        self.assertFalse(out["confirm_before_submission"])

    def test_an_unrecognised_language_fails_loudly(self):
        """Silently dropping an explicit request would generate English only
        and never say so."""
        self.run_tool("languages", "--requested", "Klingon", expect=EXIT_ERROR)

    def test_a_language_token_cannot_smuggle_a_path(self):
        self.run_tool("languages", "--requested", "../../etc", expect=EXIT_ERROR)


class LanguageTagsComeFromTheSharedLocaleTable(ToolCase):
    """Alias handling lives in tools/search_locale.py and is shared with the
    search side. A second table here would drift, and the two halves of the
    repo would disagree about what `ko-KR` means."""

    ALIASES = [
        ("en-US", ["en"]),
        ("eng", ["en"]),
        ("ko-KR", ["ko", "en"]),
        ("ko_KR", ["ko", "en"]),
        # NFD: the same word decomposed, as a Korean IME or a macOS filename
        # hands it over. Byte comparison against the composed form fails.
        ("\u1112\u1161\u11ab\u1100\u116e\u11a8\u110b\u1165", ["ko", "en"]),
    ]

    def test_aliases_fold_to_one_tag(self):
        for token, expected in self.ALIASES:
            with self.subTest(token=token):
                self.assertEqual(self.languages("--requested", token)["languages"], expected)


class RequestLanguageIsStatedNotInferred(ToolCase):
    """An English request must not fall through to a Danish profile.

    Latin script cannot be attributed, so the caller states the language of
    the user's own request instead. That is a reading of the user's message,
    not a character-range guess, and it sits above the profile fallback.
    """

    def test_a_stated_english_request_beats_the_profile(self):
        out = self.languages("--request-language", "en", "--profile-language", "Danish")
        self.assertEqual(out["languages"], ["en"])
        self.assertEqual(out["language_source"], "request-language")

    def test_an_explicit_document_request_still_outranks_it(self):
        out = self.languages("--requested", "ko", "--request-language", "en")
        self.assertEqual(out["languages"], ["ko", "en"])
        self.assertEqual(out["language_source"], "explicit")

    def test_script_detection_is_limited_to_what_a_script_proves(self):
        """Hangul means Korean. Cyrillic does not mean Russian - it is shared
        by Ukrainian, Bulgarian, Serbian and more - so the tool must decline
        and say so rather than label the bundle."""
        out = self.languages("--request-text", "\u041f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430", "--profile-language", "Danish")
        self.assertEqual(out["languages"], ["da", "en"])
        self.assertEqual(out["language_source"], "profile")
        self.assertTrue(
            any("--request-language" in note for note in out["notes"]),
            "an unattributable non-Latin script must send the caller to the "
            "explicit argument, not silently fall through",
        )

    def test_hangul_is_still_attributed(self):
        out = self.languages("--request-text", "\uc774 \uacf5\uace0\uc5d0 \uc9c0\uc6d0\ud574\uc918")
        self.assertEqual(out["languages"], ["ko", "en"])
        self.assertEqual(out["language_source"], "request-text")


class RedraftNeverForgetsASubmission(ToolCase):
    """Re-running `plan --write` is normal (a redraft, a corrected role).
    Overwriting the manifest wholesale would blank `submitted_language`, and
    /outcome would then be back to guessing which variant was sent."""

    def setUp(self):
        super().setUp()
        self.plan("--languages", "ko,en", "--primary-language", "ko", "--write")
        self.draft_files()
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer", "--language", "ko", "--date", TODAY
        )

    def manifest(self):
        return json.loads(self.manifest_path().read_text(encoding="utf-8"))

    def test_a_compatible_redraft_keeps_the_submission(self):
        out = self.plan("--languages", "ko,en", "--same-application", "--write")
        self.assertEqual(out["submitted_language"], "ko")
        self.assertEqual(out["submitted_at"], TODAY)
        self.assertEqual(self.manifest()["submitted_language"], "ko")

    def test_a_compatible_redraft_keeps_the_confirmed_primary(self):
        """The user already chose; omitting --primary-language on a redraft is
        not a retraction of that choice."""
        self.plan("--languages", "ko,en", "--same-application", "--write")
        self.assertEqual(self.manifest()["primary_language"], "ko")
        self.assertEqual(self.manifest()["primary_status"], "confirmed")

    def test_dropping_the_submitted_language_is_rejected(self):
        self.plan("--languages", "en", "--same-application", "--write", expect=EXIT_ERROR)
        self.assertEqual(self.manifest()["languages"], ["ko", "en"])
        self.assertEqual(self.manifest()["submitted_language"], "ko")

    def test_moving_the_submitted_file_is_rejected(self):
        """A new extension renames the submitted source. The archived copy is
        what was sent; a manifest pointing at a filename that never existed
        when it was sent is worse than a stale one."""
        self.plan(
            "--languages", "ko,en", "--cv-ext", ".typ", "--same-application",
            "--write", expect=EXIT_ERROR,
        )
        self.assertEqual(self.manifest()["cv_ext"], ".tex")


class SafetyRegressions(ToolCase):
    """Five holes a review found in the first cut. Each one produced a
    plausible-looking manifest or copy plan while saying something untrue."""

    def test_english_is_mandatory_in_every_bundle(self):
        """`--languages ko` used to produce a Korean-only bundle, quietly
        dropping the one variant the workflow promises is always there."""
        self.plan("--languages", "ko", expect=EXIT_ERROR)

    def test_a_manifest_without_english_is_rejected_on_read(self):
        self.plan("--languages", "ko,en", "--write")
        doc = json.loads(self.manifest_path().read_text(encoding="utf-8"))
        doc["languages"] = ["ko"]
        doc["variants"].pop("en")
        doc["primary_language"] = "ko"
        self.write_manifest(doc)
        self.run_tool("resolve", "--stem", "acme_ml_engineer", expect=EXIT_ERROR)

    def test_dates_are_validated_on_input(self):
        self.plan("--languages", "ko,en", "--write")
        self.draft_files()
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer", "--language", "ko",
            "--date", "not-a-date", expect=EXIT_ERROR,
        )
        doc = json.loads(self.manifest_path().read_text(encoding="utf-8"))
        self.assertIsNone(doc["submitted_language"])

    def test_dates_are_validated_on_read(self):
        self.plan("--languages", "ko,en", "--write")
        doc = json.loads(self.manifest_path().read_text(encoding="utf-8"))
        doc["generated"] = "14/09/2026"
        self.write_manifest(doc)
        self.run_tool("resolve", "--stem", "acme_ml_engineer", expect=EXIT_ERROR)

    def test_a_submission_needs_the_files_to_exist(self):
        """Nothing was compiled, nothing was sent. Recording a submission for
        a variant that was never written puts a file in the archive record
        that no employer could have received."""
        self.plan("--languages", "ko,en", "--write")
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer", "--language", "ko",
            "--date", TODAY, expect=EXIT_ERROR,
        )

    def test_a_reapplication_is_not_silently_inherited(self):
        """Same company, same role, a year later: the stem collides. Carrying
        the old submission forward would date the new application with the
        old one's record."""
        self.plan("--languages", "ko,en", "--write")
        self.draft_files()
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer", "--language", "ko", "--date", TODAY
        )
        out = self.plan("--languages", "ko,en", "--write", expect=EXIT_NEEDS_USER)
        self.assertEqual(out["error"], "existing_submission")
        self.assertEqual(out["submitted_language"], "ko")
        self.assertEqual(
            json.loads(self.manifest_path().read_text(encoding="utf-8"))["submitted_at"], TODAY
        )

    def test_a_legacy_archive_from_another_variant_is_flagged_not_called_exists(self):
        """`cv_draft.tex` already holding the English CV, while the user says
        they sent the Korean one, is a contradiction - not a satisfied copy."""
        self.plan("--languages", "ko,en", "--write")
        self.draft_files()
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer", "--language", "ko", "--date", TODAY
        )
        folder = self.root / "documents/applications/acme_ml_engineer"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "cv_draft.tex").write_text("cv en", encoding="utf-8")
        plan = self.run_tool("archive-plan", "--stem", "acme_ml_engineer")
        legacy = [c for c in plan["copies"] if c["destination"].endswith("/cv_draft.tex")]
        self.assertTrue(legacy)
        self.assertTrue(all(c["skip"] for c in legacy), "never overwrite what is archived")
        self.assertEqual(legacy[0]["reason"], "exists-other-variant")

    def test_resolve_does_not_vouch_for_a_mismatched_legacy_pair(self):
        self.plan("--languages", "ko,en", "--write")
        self.draft_files()
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer", "--language", "ko", "--date", TODAY
        )
        folder = self.root / "documents/applications/acme_ml_engineer"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "cv_draft.tex").write_text("cv en", encoding="utf-8")
        out = self.run_tool("resolve", "--stem", "acme_ml_engineer")
        self.assertFalse(out["archive"]["legacy_pair_matches_submitted"])
        self.assertEqual(
            out["archive"]["cv_variant"],
            "documents/applications/acme_ml_engineer/cv_draft_ko.tex",
            "the language-suffixed copy is the one that is always right",
        )


class ContainmentIsCheckedBeforeEveryTouch(ToolCase):
    """Recomputing paths proves the *string* is ours. A symlinked directory
    makes the same string land anywhere, so containment is re-checked at the
    moment of every read, write and copy destination."""

    def escape_target(self):
        outside = Path(self._tmp.name).parent / f"outside-{Path(self._tmp.name).name}"
        outside.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        return outside

    def test_a_symlinked_archive_dir_stops_the_write(self):
        outside = self.escape_target()
        (self.root / "documents" / "applications").mkdir(parents=True)
        (self.root / "documents" / "applications" / "acme_ml_engineer").symlink_to(outside)
        self.plan("--languages", "ko,en", "--write", expect=EXIT_ERROR)
        self.assertEqual(list(outside.iterdir()), [], "the manifest was written outside the workspace")

    def test_a_symlinked_document_dir_stops_the_archive_plan(self):
        outside = self.escape_target()
        self.plan("--languages", "en", "--write")
        (self.root / "cv").symlink_to(outside)
        self.run_tool("archive-plan", "--stem", "acme_ml_engineer", expect=EXIT_ERROR)


class ManifestPathsAreExactNeverGlobs(ToolCase):
    def test_every_variant_gets_suffixed_source_and_pdf_paths(self):
        out = self.plan("--languages", "ko,en")
        self.assertEqual(
            out["variants"]["ko"],
            {
                "cv": "cv/main_acme_ml_engineer_ko.tex",
                "cv_pdf": "cv/main_acme_ml_engineer_ko.pdf",
                "cover_letter": "cover_letters/cover_acme_ml_engineer_ko.tex",
                "cover_letter_pdf": "cover_letters/cover_acme_ml_engineer_ko.pdf",
            },
        )
        self.assertEqual(out["variants"]["en"]["cv"], "cv/main_acme_ml_engineer_en.tex")

    def test_active_template_extensions_are_carried_into_every_variant(self):
        """/add-template makes `.typ` a real output; hardcoding `.tex` writes
        a file the declared compile command never reads."""
        out = self.plan("--languages", "ko,en", "--cv-ext", ".typ", "--cover-ext", ".md")
        self.assertEqual(out["variants"]["ko"]["cv"], "cv/main_acme_ml_engineer_ko.typ")
        self.assertEqual(
            out["variants"]["ko"]["cover_letter"],
            "cover_letters/cover_acme_ml_engineer_ko.md",
        )
        self.assertEqual(out["variants"]["ko"]["cv_pdf"], "cv/main_acme_ml_engineer_ko.pdf")

    def test_the_stem_follows_the_documented_subfolder_rule(self):
        out = self.run_tool(
            "plan", "--company", "Novo Nordisk A/S", "--role", "Data Scientist",
            "--languages", "en",
        )
        self.assertEqual(out["stem"], "novo_nordisk_as_data_scientist")
        self.assertNotIn("/", out["variants"]["en"]["cv"].split("cv/", 1)[1])

    def test_an_empty_derived_stem_stops_instead_of_writing_at_the_root(self):
        self.run_tool(
            "plan", "--company", "../..", "--role", "///", "--languages", "en",
            expect=EXIT_ERROR,
        )

    def test_no_path_in_the_manifest_is_a_glob_or_escapes_the_workspace(self):
        out = self.plan("--languages", "ko,en")
        for lang, variant in out["variants"].items():
            for key, value in variant.items():
                with self.subTest(language=lang, key=key):
                    self.assertNotIn("*", value)
                    self.assertNotIn("..", value)
                    self.assertFalse(value.startswith("/"))

    def test_two_roles_at_one_company_never_share_a_path(self):
        """`ML Engineer` and `ML Engineer II` differ only in the role half -
        the prefix collision that made /outcome archive a sibling role's CV."""
        mine = self.plan("--languages", "ko,en")["variants"]
        sibling = self.run_tool(
            "plan", "--company", "Acme", "--role", "ML Engineer II", "--languages", "ko,en"
        )["variants"]
        for lang in ("ko", "en"):
            self.assertNotEqual(mine[lang]["cv"], sibling[lang]["cv"])
            self.assertNotEqual(mine[lang]["cover_letter"], sibling[lang]["cover_letter"])

    def test_write_puts_the_manifest_in_the_application_archive(self):
        self.plan("--languages", "ko,en", "--write")
        doc = json.loads(self.manifest_path().read_text(encoding="utf-8"))
        self.assertEqual(doc["languages"], ["ko", "en"])
        self.assertEqual(doc["schema"], "document-bundle/1")
        self.assertIsNone(doc["submitted_language"])

    def test_the_tracker_gets_one_primary_path_per_column(self):
        out = self.plan("--languages", "ko,en", "--primary-language", "ko")
        self.assertEqual(out["tracker"]["cv_file"], "cv/main_acme_ml_engineer_ko.tex")
        self.assertEqual(
            out["tracker"]["cover_letter_file"], "cover_letters/cover_acme_ml_engineer_ko.tex"
        )
        for value in out["tracker"].values():
            self.assertNotIn(";", value, "the CSV column holds one path, never a list")


class ThePrimaryIsLabelledForWhatItIs(ToolCase):
    """Nothing is "submitted" until the user says so. A primary the tool
    picked is a proposal, and the manifest must say which of the two it is."""

    def test_a_bare_plan_marks_the_primary_provisional(self):
        out = self.plan("--languages", "ko,en", "--write")
        self.assertEqual(out["primary_status"], "provisional")
        self.assertIsNone(out["submitted_language"])

    def test_an_ad_language_suggestion_is_recorded_as_suggested(self):
        out = self.plan("--languages", "ko,en", "--suggested-language", "en", "--write")
        self.assertEqual(out["primary_language"], "en")
        self.assertEqual(out["primary_status"], "suggested")
        self.assertIsNone(out["submitted_language"])

    def test_an_employer_requirement_confirms_it(self):
        out = self.plan("--languages", "ko,en", "--primary-language", "en", "--write")
        self.assertEqual(out["primary_status"], "confirmed")
        self.assertIsNone(
            out["submitted_language"],
            "confirmed says which variant to send, never that it was sent",
        )


class MixedLanguageSubmissionsAreRefusedNotFlattened(ToolCase):
    """"I sent the English CV with the Korean cover letter" is a real thing
    users do. This schema has one submitted language, so recording `ko` for
    both would put a claim in the archive the user never made. Refuse, keep
    the manifest untouched, and let the command disclose it."""

    def setUp(self):
        super().setUp()
        self.plan("--languages", "ko,en", "--write")
        self.draft_files()

    def test_two_different_languages_are_rejected(self):
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer",
            "--cv-language", "en", "--cover-letter-language", "ko",
            "--date", TODAY, expect=EXIT_ERROR,
        )
        doc = json.loads(self.manifest_path().read_text(encoding="utf-8"))
        self.assertIsNone(doc["submitted_language"])
        self.assertIsNone(doc["submitted_at"])

    def test_the_same_language_on_both_is_accepted(self):
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer",
            "--cv-language", "ko", "--cover-letter-language", "ko", "--date", TODAY,
        )
        doc = json.loads(self.manifest_path().read_text(encoding="utf-8"))
        self.assertEqual(doc["submitted_language"], "ko")


class ManifestIsUntrustedInput(ToolCase):
    """The manifest is hand-editable personal data, so reading it is a
    parsing problem, not a trust problem to wave through."""

    def base_manifest(self, **over):
        doc = {
            "schema": "document-bundle/1",
            "company": "Acme",
            "role": "ML Engineer",
            "stem": "acme_ml_engineer",
            "languages": ["ko", "en"],
            "cv_ext": ".tex",
            "cover_ext": ".tex",
            "primary_language": "ko",
            "primary_status": "provisional",
            "submitted_language": None,
            "submitted_at": None,
            "variants": {
                "ko": {
                    "cv": "cv/main_acme_ml_engineer_ko.tex",
                    "cv_pdf": "cv/main_acme_ml_engineer_ko.pdf",
                    "cover_letter": "cover_letters/cover_acme_ml_engineer_ko.tex",
                    "cover_letter_pdf": "cover_letters/cover_acme_ml_engineer_ko.pdf",
                },
                "en": {
                    "cv": "cv/main_acme_ml_engineer_en.tex",
                    "cv_pdf": "cv/main_acme_ml_engineer_en.pdf",
                    "cover_letter": "cover_letters/cover_acme_ml_engineer_en.tex",
                    "cover_letter_pdf": "cover_letters/cover_acme_ml_engineer_en.pdf",
                },
            },
        }
        doc.update(over)
        return doc

    def resolve(self, expect=0, stem="acme_ml_engineer"):
        return self.run_tool("resolve", "--stem", stem, expect=expect)

    def test_a_traversing_path_is_rejected(self):
        doc = self.base_manifest()
        doc["variants"]["ko"]["cv"] = "../../../etc/passwd"
        self.write_manifest(doc)
        self.resolve(expect=EXIT_ERROR)

    def test_an_absolute_path_is_rejected(self):
        doc = self.base_manifest()
        doc["variants"]["ko"]["cv"] = "/etc/passwd"
        self.write_manifest(doc)
        self.resolve(expect=EXIT_ERROR)

    def test_a_path_outside_the_document_folders_is_rejected(self):
        """Staying inside the workspace is not enough: the profile and the
        tracker are also inside it."""
        doc = self.base_manifest()
        doc["variants"]["ko"]["cv"] = "job_search_tracker.csv"
        self.write_manifest(doc)
        self.resolve(expect=EXIT_ERROR)

    def test_a_midpath_escape_is_rejected(self):
        doc = self.base_manifest()
        doc["variants"]["ko"]["cv"] = "cv/../../secrets.tex"
        self.write_manifest(doc)
        self.resolve(expect=EXIT_ERROR)

    def test_a_language_key_cannot_be_a_path_fragment(self):
        doc = self.base_manifest()
        doc["variants"]["../etc"] = doc["variants"].pop("en")
        doc["languages"] = ["ko", "../etc"]
        self.write_manifest(doc)
        self.resolve(expect=EXIT_ERROR)

    def test_a_stem_argument_cannot_traverse(self):
        self.run_tool("resolve", "--stem", "../../etc", expect=EXIT_ERROR)

    def test_a_missing_manifest_is_reported_not_invented(self):
        self.resolve(expect=EXIT_ERROR)


class SubmittedVariantIsNeverGuessed(ToolCase):
    def setUp(self):
        super().setUp()
        self.plan("--languages", "ko,en", "--primary-language", "ko", "--write")
        self.draft_files()

    def test_resolve_refuses_to_pick_between_variants(self):
        out = self.run_tool("resolve", "--stem", "acme_ml_engineer", expect=EXIT_NEEDS_USER)
        self.assertEqual(out["error"], "submitted_language_unknown")
        self.assertEqual(out["candidates"], ["ko", "en"])

    def test_a_single_variant_bundle_is_unambiguous(self):
        self.run_tool(
            "plan", "--company", "Beta", "--role", "MLE", "--languages", "en", "--write"
        )
        self.draft_files(stem="beta_mle", languages=("en",))
        out = self.run_tool("resolve", "--stem", "beta_mle")
        self.assertEqual(out["submitted_language"], "en")
        self.assertEqual(out["cv"], "cv/main_beta_mle_en.tex")

    def test_marking_the_submission_makes_resolve_deterministic(self):
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer", "--language", "en", "--date", TODAY
        )
        out = self.run_tool("resolve", "--stem", "acme_ml_engineer")
        self.assertEqual(out["submitted_language"], "en")
        self.assertEqual(out["cv"], "cv/main_acme_ml_engineer_en.tex")

    def test_the_submitted_variant_may_differ_from_the_provisional_primary(self):
        """Generated is not submitted. The primary written into the tracker
        at draft time is a provisional choice; what the user actually sent
        wins over it everywhere the archive is read."""
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer", "--language", "en", "--date", TODAY
        )
        doc = json.loads(self.manifest_path().read_text(encoding="utf-8"))
        self.assertEqual(doc["primary_language"], "ko")
        self.assertEqual(doc["submitted_language"], "en")
        self.assertEqual(doc["submitted_at"], TODAY)

    def test_marking_a_language_outside_the_bundle_fails(self):
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer", "--language", "da",
            "--date", TODAY, expect=EXIT_ERROR,
        )


class ArchiveKeepsEveryVariantAndOverwritesNothing(ToolCase):
    def setUp(self):
        super().setUp()
        self.plan("--languages", "ko,en", "--primary-language", "ko", "--write")
        self.draft_files()
        self.run_tool(
            "mark-submitted", "--stem", "acme_ml_engineer", "--language", "ko", "--date", TODAY
        )

    def archive_plan(self, expect=0):
        return self.run_tool("archive-plan", "--stem", "acme_ml_engineer", expect=expect)

    def test_every_variant_is_copied_under_a_language_suffixed_name(self):
        pairs = {(c["source"], c["destination"]) for c in self.archive_plan()["copies"]}
        folder = "documents/applications/acme_ml_engineer"
        for language in ("ko", "en"):
            with self.subTest(language=language):
                self.assertIn(
                    (
                        f"cv/main_acme_ml_engineer_{language}.tex",
                        f"{folder}/cv_draft_{language}.tex",
                    ),
                    pairs,
                )
                self.assertIn(
                    (
                        f"cover_letters/cover_acme_ml_engineer_{language}.tex",
                        f"{folder}/cover_letter_{language}.tex",
                    ),
                    pairs,
                )

    def test_the_submitted_variant_also_lands_under_the_legacy_names(self):
        """/setup and every pre-bundle reader know `cv_draft.tex` and
        `cover_letter.tex` only. The submitted variant keeps those names so
        an unchanged reader still finds what was actually sent."""
        plan = self.archive_plan()
        legacy = {
            c["destination"]: c["source"]
            for c in plan["copies"]
            if c["destination"].endswith(("cv_draft.tex", "cover_letter.tex"))
        }
        self.assertEqual(
            legacy["documents/applications/acme_ml_engineer/cv_draft.tex"],
            "cv/main_acme_ml_engineer_ko.tex",
        )
        self.assertEqual(
            legacy["documents/applications/acme_ml_engineer/cover_letter.tex"],
            "cover_letters/cover_acme_ml_engineer_ko.tex",
        )

    def test_an_existing_archived_file_is_never_overwritten(self):
        archived = self.root / "documents/applications/acme_ml_engineer/cv_draft.tex"
        archived.parent.mkdir(parents=True, exist_ok=True)
        archived.write_bytes((self.root / "cv/main_acme_ml_engineer_ko.tex").read_bytes())
        plan = self.archive_plan()
        skipped = [c for c in plan["copies"] if c["destination"].endswith("/cv_draft.tex")]
        self.assertTrue(skipped and all(c["skip"] for c in skipped))
        self.assertTrue(
            all(c["reason"] == "exists" for c in skipped),
            "same bytes as the submitted source: an already-satisfied copy, not a conflict",
        )

    def test_a_missing_source_is_reported_rather_than_substituted(self):
        (self.root / "cv/main_acme_ml_engineer_en.tex").unlink()
        plan = self.archive_plan()
        missing = [c for c in plan["copies"] if c["source"].endswith("_en.tex") and c["skip"]]
        self.assertTrue(missing)
        self.assertTrue(all(c["reason"] == "missing-source" for c in missing))

    def test_every_destination_stays_inside_this_applications_folder(self):
        for copy in self.archive_plan()["copies"]:
            with self.subTest(destination=copy["destination"]):
                self.assertTrue(
                    copy["destination"].startswith(
                        "documents/applications/acme_ml_engineer/"
                    )
                )
                self.assertNotIn("..", copy["destination"])

    def test_an_unknown_submission_blocks_the_archive_plan(self):
        self.run_tool(
            "plan", "--company", "Gamma", "--role", "MLE", "--languages", "ko,en", "--write"
        )
        self.draft_files(stem="gamma_mle")
        out = self.run_tool("archive-plan", "--stem", "gamma_mle", expect=EXIT_NEEDS_USER)
        self.assertEqual(out["error"], "submitted_language_unknown")


class CommandsWireTheBundleIntoTheWorkflow(unittest.TestCase):
    """The command files are the implementation for the model-run steps, so
    a handful of load-bearing sentences have to be pinned somewhere.

    Deliberately short: one needle per contract that another command reads,
    scoped to the section that owns it. The behaviour of the helper is
    tested above against the real CLI; restating its rules as prose
    assertions here would only pin wording.
    """

    CASES = [
        (APPLY, "## Step 2: DRAFTER - Draft CV + Cover Letter",
         "tools/document_bundle.py languages",
         "the language set must come from the one documented resolution"),
        (APPLY, "## Step 5: DRAFTER - Compile & Inspect PDFs (MANDATORY)",
         "every variant in the manifest",
         "compiling the first variant only ships an unbuilt document"),
        (APPLY, "### 5d. ATS & keyword verification (CV)", "is not proof",
         "an extractor can drop a whole script while emitting neither `(cid:` "
         "nor a replacement character, so a clean parseability check on a "
         "Hangul document says nothing on its own"),
        (APPLY, "### Step 6b: Record the Application",
         '| `cv_file`, `cover_letter_file` | the two paths listed under "Files Created"',
         "Step 6b's column table lost the pointer to the documents"),
        (APPLY, "### Step 6b: Record the Application", "one path each, never a list",
         "a semicolon-joined column would break every existing CSV reader"),
        (OUTCOME, "## Step 3: Archive the Application Materials", "archive-plan",
         "the copy list is derived by the tool, so never-overwrite and the "
         "legacy names are not restated by eye"),
        (OUTCOME, "## Step 3: Archive the Application Materials",
         "ask the user which variant",
         "which file was sent is a fact only the user has"),
        (OUTCOME, "## Step 3: Archive the Application Materials",
         "Never widen those globs to the company alone",
         "the pre-bundle fallback still has to select one role's documents"),
        (INTERVIEW, "## Step 1: Load the Application Context", "never guess",
         "prepping off the English variant when the Korean one was submitted "
         "coaches claims the interviewer never read"),
        (APPLY, "## Step 0: Parse Input", "required for the application documents",
         "the language an ad is written in and the language it asks you to "
         "apply in are different facts, and only the second decides"),
        (OUTCOME, "## Step 2: Collect What Happened", "one language for both",
         "a mixed submission has to stop and be disclosed, not be flattened "
         "into a claim the user never made"),
        (HTML_REPORT, "## Step 3: Generate the HTML", "sort_by_preference",
         "grouping is shared with /rank and /scrape through the helper; a "
         "second rule kept in this file is a rule that drifts"),
        (HTML_REPORT, "## Step 3: Generate the HTML", "do not read a language out of `notes`",
         "notes are the candidate's words about the application, not the "
         "posting - feeding them in as posting_language invents a fact"),
        (HTML_REPORT, "## Step 3: Generate the HTML", "newest-first",
         "grouping must not silently replace the existing sort inside a group"),
        (SKILL, "### Step 2: Tailor CV", "document_bundle.py",
         "/scrape Step 5 routes into the skill and never runs /apply"),
        (SKILL, "### Step 3b: Record the Application", "`/apply` Step 6b",
         "the recording step must keep deferring rather than restating"),
        (DOCS_README, "## applications/", "document_bundle.json",
         "the archive gained a file; a folder listing that omits it reads as "
         "though the manifest is stray"),
    ]

    def test_each_contract_is_stated_where_its_reader_looks(self):
        for path, heading, needle, why in self.CASES:
            with self.subTest(file=path.name, rule=needle):
                self.assertIn(needle, section(path, heading), why)

    def test_step_0_no_longer_hardcodes_two_languages(self):
        self.assertNotIn(
            "(Danish or English)",
            section(APPLY, "## Step 0: Parse Input"),
            "the parenthetical reads as the supported set - a Korean posting "
            "would be recorded as one of the two",
        )

    def test_korean_font_work_stays_with_the_template_guides(self):
        """A separate change owns the opt-in CJK font support in `05`/`06`
        and `cover.cls`. /apply points at those guides; an inline font hack
        here would fork the templates."""
        self.assertNotIn("setCJKmainfont", APPLY.read_text(encoding="utf-8"))
        self.assertNotIn("korean-fonts", APPLY.read_text(encoding="utf-8"))

    def test_the_dashboard_table_schema_is_unchanged(self):
        line = re.search(
            r"### Table: columns to include\n\n(.+)\n",
            HTML_REPORT.read_text(encoding="utf-8"),
        ).group(1)
        self.assertIn("`Date` · `Deadline` · `Company`", line)
        self.assertNotIn("`Language`", line)


class NoFallbackGlobEverWidensToTheCompany(unittest.TestCase):
    """Every `cv/` glob in the two fallback sections - not just the first -
    must still select one role's documents.

    test_apply_records_application.py pins the first glob it finds. A second
    glob added beside it (a language-suffixed `main_<company>_<role>_*.*`,
    say) would match `main_acme_ml_engineer_ii.tex` for the role `ML
    Engineer` and reintroduce #443 with a green suite. This simulates the
    match rather than asserting on the wording.
    """

    COMPANY = "Acme"
    ROLES = ("Data Scientist", "ML Engineer", "ML Engineer II")
    SECTIONS = [
        (OUTCOME, "## Step 3: Archive the Application Materials"),
        (INTERVIEW, "## Step 1: Load the Application Context"),
    ]

    @staticmethod
    def derive(company, role):
        name = f"{company}_{role}".lower().replace(" ", "_")
        name = re.sub(r"[^\w]", "", name)
        return re.sub(r"_+", "_", name).strip("_")

    def files_on_disk(self):
        """What /apply leaves in cv/ for three roles at one company, both
        pre-bundle (unsuffixed) and bundled (language-suffixed)."""
        stems = [self.derive(self.COMPANY, role) for role in self.ROLES]
        return [f"cv/main_{s}.tex" for s in stems] + [
            f"cv/main_{s}_{lang}.tex" for s in stems for lang in ("en", "ko")
        ]

    def role_of(self, filename):
        stem = filename.rsplit("/", 1)[1][len("main_"):].rsplit(".", 1)[0]
        return stem.removesuffix("_en").removesuffix("_ko")

    def test_every_cv_glob_selects_one_role(self):
        files = self.files_on_disk()
        for path, heading in self.SECTIONS:
            body = section(path, heading)
            globs = [g for g in re.findall(r"`(cv/main_[^`]+)`", body) if "*" in g]
            self.assertTrue(globs, f"{path.name}: no CV fallback glob found")
            for glob in globs:
                for role in self.ROLES:
                    resolved = glob.replace(
                        "<company>_<role>", self.derive(self.COMPANY, role)
                    ).replace("<company>", self.derive(self.COMPANY, ""))
                    hits = fnmatch.filter(files, resolved)
                    with self.subTest(file=path.name, glob=glob, role=role):
                        self.assertLessEqual(
                            len({self.role_of(h) for h in hits}),
                            1,
                            f"{glob!r} matched more than one role's documents: {hits}",
                        )


if __name__ == "__main__":
    unittest.main()
