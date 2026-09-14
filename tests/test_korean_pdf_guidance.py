"""Guards for the opt-in Korean (Hangul) rendering support.

The stock templates are Latin-only: `cover.cls` selects Lato/Raleway with
hardcoded `\\fontspec` switches (cover.cls:30-31 and every command from :36
down) and the CV is moderncv under lualatex with no Unicode font setup, so
a Korean document compiles with exit 0 and a clean-looking log while every
Hangul character is dropped from the page and from the ATS text layer -
F31's silent-success failure mode, document-wide. Measured on the fixtures
below: removing the opt-in line gives exit 0 with 717 `Missing character`
log lines and an unreadable text layer.

`templates/korean/korean-fonts.sty` is the opt-in fix. These tests pin that
it stays opt-in (English documents untouched), that it fails loudly instead
of degrading to tofu, and - the only check that can prove a glyph reached
the page - that the fixtures compile and the Hangul comes back out of the
PDF text layer, which is what an ATS reads.

The fixtures under tests/fixtures/ are synthetic: a made-up person applying
to a made-up company, never a genuine application record.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / ".claude" / "skills" / "job-application-assistant"
CV_TEMPLATES = SKILL_DIR / "05-cv-templates.md"
COVER_TEMPLATES = SKILL_DIR / "06-cover-letter-templates.md"
CI = REPO / ".github" / "workflows" / "ci.yml"

KOREAN_DIR = REPO / "templates" / "korean"
KOREAN_STY = KOREAN_DIR / "korean-fonts.sty"

FIXTURE_DIR = REPO / "tests" / "fixtures"
KOREAN_CV = FIXTURE_DIR / "korean-cv.tex"
KOREAN_COVER = FIXTURE_DIR / "korean-cover.tex"

EXAMPLE_CV = REPO / "cv" / "main_example.tex"
EXAMPLE_COVER = REPO / "cover_letters" / "cover_example.tex"
COVER_CLS = REPO / "cover_letters" / "cover.cls"

# Hangul syllables plus jamo. Anything in these ranges needs a Korean font;
# nothing in the stock Lato/Raleway/Latin Modern setup can render it.
HANGUL = re.compile(r"[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]")

# The single line a document adds to opt in. The guides must teach exactly
# what the compiled fixtures use - a guide that drifts from the fixture is
# a guide that produces documents CI never compiled.
OPT_IN_LINE = r"\usepackage{korean-fonts}"

# TEXINPUTS is how the shared package is found from cv/ and cover_letters/
# without installing anything into the user's TeX tree.
TEXINPUTS_PREFIX = "TEXINPUTS="

# Strings the compiled PDFs must contain. Kept here (not only in the
# fixtures) so the runtime test and the CI assertions check the same text.
CV_HANGUL_CHECKS = ["김민준", "핵심 역량", "경력 사항", "학력", "추천인"]
CV_ENGLISH_CHECKS = ["fixture@example.com", "Claude Code"]
COVER_HANGUL_CHECKS = ["김민준", "채용 담당자님께", "지원", "감사합니다"]
COVER_ENGLISH_CHECKS = ["fixture@example.com", "Kind regards"]

# `\item [text]` is parsed as moderncv's optional label and clipped off the
# page (F9). The fixtures must not teach it either.
UNBRACED_BRACKET_ITEM = re.compile(r"\\item\s*\[")


def read(path):
    return path.read_text(encoding="utf-8")


def macro_arguments(text, macro):
    """Return the brace-balanced arguments of every \\macro{...} in text."""
    found = []
    for match in re.finditer(re.escape("\\" + macro) + r"\s*(?=\{)", text):
        index = match.end()
        while index < len(text) and text[index] == "{":
            depth = 0
            start = index
            while index < len(text):
                if text[index] == "{":
                    depth += 1
                elif text[index] == "}":
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
            found.append(text[start + 1 : index - 1])
            while index < len(text) and text[index] in " \t":
                index += 1
    return found


class TestKoreanSupportPackageIsLoud(unittest.TestCase):
    """A missing engine, package or font must stop the compile, not tofu."""

    def setUp(self):
        self.assertTrue(
            KOREAN_STY.is_file(),
            f"{KOREAN_STY} is missing - the shared Korean preamble is the whole feature",
        )
        self.sty = read(KOREAN_STY)

    def test_every_failure_mode_is_probed_before_it_can_go_silent(self):
        required = {
            r"\RequirePackage{iftex}": "pdflatex cannot load a Hangul font; the engine must be detected",
            r"\PackageError": "an unsupported setup must error, not warn",
            r"\IfFileExists{kotex.sty}": "a missing ko.TeX must report an install command, not TeX's file prompt",
            r"\IfFontExistsTF": "a missing font must be named, or the document renders tofu and compiles clean",
        }
        missing = {k: why for k, why in required.items() if k not in self.sty}
        self.assertEqual(missing, {}, f"korean-fonts.sty lost a guard: {missing}")

    def test_routes_hangul_through_kotex_for_all_three_families(self):
        # ko.TeX switches font per character class, which is what keeps Hangul
        # readable inside cover.cls's hardcoded Latin \fontspec switches. All
        # three families are pinned because the stock CV is moderncv's `sans`
        # option and cover.cls switches families by hand.
        missing = [
            macro
            for macro in (
                r"\RequirePackage{kotex}",
                r"\setmainhangulfont",
                r"\setsanshangulfont",
                r"\setmonohangulfont",
            )
            if macro not in self.sty
        ]
        self.assertEqual(missing, [], f"korean-fonts.sty lost: {missing}")


class TestEnglishTemplatesStayUntouched(unittest.TestCase):
    """Opt-in means the stock documents do not change at all."""

    def assert_no_korean_support(self, path):
        text = read(path)
        self.assertNotIn(
            "korean-fonts",
            text,
            f"{path.name} must not load the Korean package - English "
            "documents keep compiling exactly as before",
        )
        hangul = HANGUL.search(text)
        self.assertIsNone(
            hangul,
            f"{path.name} must stay Latin-only; found Hangul at "
            f"offset {hangul.start() if hangul else -1}",
        )

    def test_example_cv_unchanged(self):
        self.assert_no_korean_support(EXAMPLE_CV)

    def test_example_cover_letter_unchanged(self):
        self.assert_no_korean_support(EXAMPLE_COVER)

    def test_cover_class_does_not_hardcode_korean(self):
        self.assert_no_korean_support(COVER_CLS)


class TestKoreanFixturesAreSyntheticAndComplete(unittest.TestCase):
    """The fixtures must be obviously fake and must exercise every region."""

    def setUp(self):
        for path in (KOREAN_CV, KOREAN_COVER):
            self.assertTrue(path.is_file(), f"{path} is missing")
        self.cv = read(KOREAN_CV)
        self.cover = read(KOREAN_COVER)

    def test_fixtures_declare_themselves_synthetic_and_opt_in(self):
        # A fixture that reads as a real application record is both a
        # personal-data and a factual-accuracy hazard.
        for name, text in (("korean-cv.tex", self.cv), ("korean-cover.tex", self.cover)):
            missing = [
                marker
                for marker in ("SYNTHETIC TEST FIXTURE", "fixture@example.com", OPT_IN_LINE)
                if marker not in text
            ]
            self.assertEqual(missing, [], f"{name} is missing: {missing}")

    def test_cv_fixture_has_hangul_in_name_contact_headings_and_bullets(self):
        # Each region is set in a different moderncv font, so one Hangul
        # string somewhere in the document would prove nothing.
        names = macro_arguments(self.cv, "name")
        self.assertTrue(
            names and any(HANGUL.search(part) for part in names),
            "the candidate name must be Hangul - \\namefont at 34pt is the first thing to tofu",
        )

        contact = macro_arguments(self.cv, "address") + macro_arguments(self.cv, "extrainfo")
        self.assertTrue(
            any(HANGUL.search(part) for part in contact),
            "the address/extrainfo line must carry Hangul",
        )

        sections = macro_arguments(self.cv, "section")
        self.assertGreaterEqual(len(sections), 4, "fixture CV needs the stock sections")
        untranslated = [s for s in sections if not HANGUL.search(s)]
        self.assertEqual(
            untranslated,
            [],
            "every \\section{} heading must be translated - English headings over "
            f"Korean prose is the drift 05-cv-templates.md warns about: {untranslated}",
        )

        bullets = [
            line
            for line in self.cv.splitlines()
            if line.lstrip().startswith(r"\item") and HANGUL.search(line)
        ]
        self.assertGreaterEqual(len(bullets), 5, "Hangul must appear inside itemize bullets")

    def test_cover_fixture_has_hangul_in_name_body_bullets_and_signature(self):
        header = macro_arguments(self.cover, "namesection")
        self.assertGreaterEqual(len(header), 3, "fixture cover letter has no \\namesection")
        self.assertTrue(HANGUL.search(header[1]), "\\namesection name must be Hangul")
        self.assertTrue(HANGUL.search(header[2]), "\\namesection contact line must carry Hangul")

        paragraphs = macro_arguments(self.cover, "lettercontent")
        self.assertGreaterEqual(len(paragraphs), 3, "fixture cover letter needs body paragraphs")
        self.assertTrue(
            all(HANGUL.search(p) for p in paragraphs),
            "every \\lettercontent{} paragraph must be Korean - each re-selects Raleway by hand",
        )

        signature = macro_arguments(self.cover, "signature")
        self.assertTrue(
            signature and HANGUL.search(signature[0]),
            "\\signature{} must be Hangul - the last hardcoded fontspec switch in the class",
        )

        # The Raleway-wrapped itemize block is the hardest case for ko.TeX:
        # an ad-hoc \fontspec family that is none of rm/sf/tt.
        bullet_block = re.search(
            r"\\fontspec.*?\\begin\{itemize\}(.*?)\\end\{itemize\}", self.cover, re.DOTALL
        )
        self.assertIsNotNone(bullet_block, "the Raleway-wrapped itemize block is gone")
        self.assertTrue(
            HANGUL.search(bullet_block.group(1)),
            "bullets inside the hardcoded Raleway \\fontspec switch must be Korean",
        )

    def test_fixtures_contain_the_strings_ci_asserts(self):
        # Both scripts: a Korean document still carries emails and tool names,
        # and mixed-script line breaking is its own failure mode.
        for name, text, checks in (
            ("korean-cv.tex", self.cv, CV_ENGLISH_CHECKS),
            ("korean-cover.tex", self.cover, COVER_ENGLISH_CHECKS),
        ):
            missing = [c for c in checks if c not in text]
            self.assertEqual(missing, [], f"{name} lost Latin text CI asserts: {missing}")

        for name, text, checks in (
            ("korean-cv.tex", self.cv, CV_HANGUL_CHECKS),
            ("korean-cover.tex", self.cover, COVER_HANGUL_CHECKS),
        ):
            missing = [c for c in checks if c not in text]
            self.assertEqual(
                missing, [], f"{name} lost strings the PDF check looks for: {missing}"
            )

    def test_fixtures_avoid_the_bracket_label_trap(self):
        for name, text in (("korean-cv.tex", self.cv), ("korean-cover.tex", self.cover)):
            offending = [
                f"{name}:{lineno}: {line.strip()}"
                for lineno, line in enumerate(text.splitlines(), 1)
                if UNBRACED_BRACKET_ITEM.search(line)
            ]
            self.assertEqual(
                offending,
                [],
                "\\item followed by [ is parsed as an optional label:\n"
                + "\n".join(offending),
            )


class TestGuidesTeachWhatTheFixturesCompile(unittest.TestCase):
    """The documented usage must be the usage CI actually compiles."""

    def setUp(self):
        self.guides = {
            "05-cv-templates.md": read(CV_TEMPLATES),
            "06-cover-letter-templates.md": read(COVER_TEMPLATES),
        }

    def test_both_guides_show_the_exact_opt_in_and_how_it_is_found(self):
        # Without TEXINPUTS the documented \usepackage line fails with "file
        # not found" and the agent "fixes" it by inlining fonts instead.
        for name, text in self.guides.items():
            missing = [s for s in (OPT_IN_LINE, TEXINPUTS_PREFIX) if s not in text]
            self.assertEqual(missing, [], f"{name} does not teach what CI compiles: {missing}")

    def test_each_guide_keeps_its_own_engine(self):
        # Switching the stock CV to xelatex would change every English compile.
        for name, engine in (
            ("05-cv-templates.md", "lualatex"),
            ("06-cover-letter-templates.md", "xelatex"),
        ):
            self.assertIn(engine, self.guides[name], f"{name} must stay on {engine}")

    def test_cv_guide_ties_korean_to_translated_headings(self):
        text = self.guides["05-cv-templates.md"]
        section = re.search(
            r"^#+ [^\n]*Korean[^\n]*\n(.*?)(?=^#+ |\Z)", text, re.MULTILINE | re.DOTALL
        )
        self.assertIsNotNone(section, "05-cv-templates.md has no Korean section")
        body = section.group(1)
        self.assertTrue(
            HANGUL.search(body),
            "the Korean section must show the translated headings literally - "
            "an agent that has to invent them will leave English ones behind",
        )


class TestCiCompilesTheKoreanFixtures(unittest.TestCase):
    """CI must compile the fixtures on both existing legs and read the text back."""

    def setUp(self):
        self.ci = read(CI)

    def test_ci_compiles_each_fixture_on_the_engine_its_template_uses(self):
        for pattern in (r"lualatex[^\n]*korean-cv\.tex", r"xelatex[^\n]*korean-cover\.tex"):
            self.assertRegex(self.ci, pattern, f"ci.yml no longer runs: {pattern}")

    def test_ci_installs_korean_tex_support(self):
        self.assertIn(
            "texlive-lang-korean",
            self.ci,
            "the apt leg ships no Korean TeX at all, so the fixture compile "
            "would die on a missing kotex.sty",
        )

    def test_ci_fails_on_missing_glyphs_and_asserts_the_text_layer(self):
        # The engine logs 'Missing character' and still exits 0, and a clean
        # compile does not prove a glyph reached the page - so CI needs both.
        self.assertIn("Missing character", self.ci, "ci.yml lost the tofu grep")
        for needle in (CV_HANGUL_CHECKS[0], COVER_HANGUL_CHECKS[1]):
            self.assertIn(
                needle, self.ci, f"ci.yml must assert {needle!r} via verify_pdf --contains"
            )

    def test_ci_keeps_the_english_assertions(self):
        for needle in (
            "main_example.tex",
            "cover_example.tex",
            "Dear [Hiring Manager / Team]",
        ):
            self.assertIn(needle, self.ci, f"ci.yml lost the English check {needle!r}")


def engine_available(engine):
    return shutil.which(engine) is not None


def extractor_available():
    """True when verify_pdf.py has something to read a PDF with."""
    if shutil.which("pdftotext") and shutil.which("pdfinfo"):
        return True
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


class TestKoreanFixturesActuallyRender(unittest.TestCase):
    """Compile for real and read the Hangul back out of the PDF text layer.

    Skipped where no TeX engine is installed (the python-tests job, most
    laptops); it runs in the latex-smoke containers and locally for anyone
    with TeX Live, which is where a font regression can be caught at all.
    """

    def compile_fixture(self, engine, workdir, fixture, pages, hangul, english):
        with tempfile.TemporaryDirectory() as out:
            env = dict(os.environ)
            texinputs = os.pathsep.join([str(KOREAN_DIR), ""])
            env["TEXINPUTS"] = texinputs + os.pathsep + env.get("TEXINPUTS", "")
            result = subprocess.run(
                [
                    engine,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    f"-output-directory={out}",
                    str(fixture),
                ],
                cwd=str(workdir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            log = Path(out) / (fixture.stem + ".log")
            log_text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
            self.assertEqual(
                result.returncode,
                0,
                f"{engine} failed on {fixture.name}:\n"
                + "\n".join(
                    line for line in log_text.splitlines() if line.startswith("!")
                )[:2000],
            )
            missing = [
                line for line in log_text.splitlines() if "Missing character" in line
            ]
            self.assertEqual(
                missing[:5],
                [],
                f"{fixture.name} rendered tofu - the engine had no glyph for "
                "these characters and still exited 0",
            )

            pdf = Path(out) / (fixture.stem + ".pdf")
            self.assertTrue(pdf.is_file(), f"{engine} produced no PDF for {fixture.name}")

            # Compile and tofu checks above need no extractor and have already
            # run. The PDF-reading checks below do, and a TeX install without
            # poppler or pypdf cannot make them - skip rather than report a
            # font failure that is really a missing tool (the same graceful
            # skip tools/verify_pdf.py and the ATS guidance use).
            if not extractor_available():
                self.skipTest("no PDF text extractor (install poppler-utils or pypdf)")

            verify = subprocess.run(
                [sys.executable, str(REPO / "tools" / "verify_pdf.py"), str(pdf), "--pages", str(pages)]
                + [arg for needle in hangul + english for arg in ("--contains", needle)],
                cwd=str(REPO),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(
                verify.returncode,
                0,
                f"{fixture.name} PDF failed verification (this is what an ATS "
                f"sees):\n{verify.stdout}\n{verify.stderr}",
            )

            # A fixture whose last page holds one heading proves the font
            # works and nothing about the layout, and it cannot be shown to
            # anyone as a rendering sample. Same thresholds a real CV is held
            # to (tools/verify_layout.py: non-final 25%, final 35% blank).
            layout = subprocess.run(
                [sys.executable, str(REPO / "tools" / "verify_layout.py"), str(pdf)],
                cwd=str(REPO),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(
                layout.returncode,
                0,
                f"{fixture.name} has a layout problem:\n{layout.stdout}\n{layout.stderr}",
            )

    @unittest.skipUnless(engine_available("lualatex"), "lualatex not installed")
    def test_korean_cv_compiles_to_two_pages_with_readable_hangul(self):
        self.compile_fixture(
            "lualatex",
            REPO / "cv",
            KOREAN_CV,
            2,
            CV_HANGUL_CHECKS,
            CV_ENGLISH_CHECKS,
        )

    @unittest.skipUnless(engine_available("xelatex"), "xelatex not installed")
    def test_korean_cover_letter_compiles_to_one_page_with_readable_hangul(self):
        self.compile_fixture(
            "xelatex",
            REPO / "cover_letters",
            KOREAN_COVER,
            1,
            COVER_HANGUL_CHECKS,
            COVER_ENGLISH_CHECKS,
        )


if __name__ == "__main__":
    unittest.main()
