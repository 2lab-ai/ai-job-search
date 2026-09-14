#!/usr/bin/env python3
"""Language-set and path resolution for an application's document bundle.

A bundle is English plus the language the user actually asked in, one CV and
one cover letter per language. Three decisions are mechanical, and each one
corrupts an application quietly when made by eye:

1. **Which languages.** Explicit request -> the language the caller read the
   request as (`--request-language`) -> what the script of the request proves
   (Hangul only) -> the profile's `CV language:` -> English. English is always
   in the set and never duplicated. The posting never enters it: it is
   untrusted third-party text, and a Korean ad is not a request for Korean
   documents. Tags and aliases come from tools/search_locale.py, shared with
   the search side.

2. **Which paths.** Exact filenames from the documented Subfolder naming rule
   and the active template's extensions, so nothing downstream widens a glob:
   `main_<stem>_*.tex` also matches the sibling role `ML Engineer II`.

3. **Which variant was submitted.** Only the user knows. `resolve` and
   `archive-plan` exit 2 with `submitted_language_unknown` rather than pick,
   `mark-submitted` is for a send the user confirms (not a decision to send),
   and a mixed-language pair is refused because this schema cannot say it.
   The primary is labelled `confirmed` (employer requires it, or the user
   chose it) / `suggested` (the ad's language) / `provisional` (nothing);
   none of them means sent.

The manifest is hand-editable personal data, so every path it holds is
recomputed from its own stem/language/extension and compared, and containment
is re-checked at each read, write and copy destination (a symlinked directory
relocates a path that validated fine as a string).

Usage:
  python3 tools/document_bundle.py languages [--requested ko] [--request-language en]
      [--request-text TEXT] [--profile-language da] [--posting-language ko]
      [--required-language en] [--submission-language ko]
  python3 tools/document_bundle.py plan --company NAME --role TITLE --languages ko,en
      [--cv-ext .tex] [--cover-ext .tex] [--primary-language ko]
      [--suggested-language ko] [--write]
  python3 tools/document_bundle.py resolve|archive-plan --stem STEM
  python3 tools/document_bundle.py mark-submitted --stem STEM --language ko [--date YYYY-MM-DD]

JSON on stdout. Exit 0, 1 on a usage or validation error, 2 when the answer is
a fact only the user has. Stdlib only, like the other tools here.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import search_locale  # noqa: E402 - sibling tool, same directory
except ImportError as exc:  # pragma: no cover - a missing file, not a branch
    sys.exit(
        f"document_bundle: tools/search_locale.py is required for language tags ({exc}). "
        "The alias table is shared with the search side on purpose; do not re-add a local copy."
    )

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = "document-bundle/1"
MANIFEST_NAME = "document_bundle.json"
APPLICATIONS = "documents/applications"

EXIT_ERROR = 1
EXIT_NEEDS_USER = 2

# ISO 639-1/3, optionally with a region subtag. Lowercase ASCII only: the
# code becomes part of a filename, so anything else is a path problem.
LANGUAGE_CODE = re.compile(r"^[a-z]{2,3}(-[a-z]{2,8})?$")
EXTENSION = re.compile(r"^\.[A-Za-z0-9]{1,8}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STEM = re.compile(r"^\w+$")

# Language tags, aliases and script attribution come from search_locale.py -
# the same table the search side uses, so `ko-KR`, `ko_KR`, `eng` and a
# decomposed `\ud55c\uad6d\uc5b4` cannot mean one thing here and another there. What is
# added here is strictness: this tool puts the tag in a filename, so an
# unrecognised token is an error rather than a None that degrades to English.

class BundleError(Exception):
    """A usage or validation failure: exit 1, nothing is written."""


class NeedsUser(Exception):
    """The answer is a fact only the user has: exit 2, the command asks."""

    def __init__(self, payload):
        super().__init__(payload.get("error", "needs user input"))
        self.payload = payload


# --------------------------------------------------------------------------
# language resolution
# --------------------------------------------------------------------------

def normalize_language(token):
    """A language name, tag or alias -> a canonical tag; empty is absent.

    Alias table delegated to search_locale (`en-US`, `eng`, `ko_KR`, NFD
    Hangul); raises where it returns None, because a dropped language
    silently becomes an English-only bundle.
    """
    if token is None or not str(token).strip():
        return None
    tag = search_locale.normalize_language(token)
    if tag is None or not LANGUAGE_CODE.match(tag):
        raise BundleError(
            f"unrecognised language {token!r}. Pass an ISO 639-1 tag (ko, da, de), "
            "a locale (ko-KR), or a name the shared table in tools/search_locale.py knows."
        )
    return tag


def normalize_languages(tokens):
    codes = []
    for token in str(tokens or "").split(","):
        code = normalize_language(token)
        if code and code not in codes:
            codes.append(code)
    return codes


def detect_script_language(text):
    """The language a script proves, or None. Hangul proves Korean; Cyrillic,
    Han and Latin are each shared by several languages, so they prove
    nothing and the caller falls through instead of labelling the bundle."""
    return search_locale.script_language(text)


def unattributable_script(text):
    """True when the text is non-Latin but not attributable - the difference
    between "no signal" and "a signal this refuses to guess from"."""
    for ch in unicodedata.normalize("NFC", str(text or "")):
        if not ch.isalpha() or ord(ch) < 0x250:
            continue
        if search_locale.script_language(ch) is None:
            return True
    return False


def resolve_languages(requested=None, request_text=None, profile_language=None,
                      posting_language=None, submission_language=None,
                      request_language=None, required_language=None):
    """The documented precedence, returned with the evidence for the choice.

    `request_language` is the caller stating what language the user wrote in -
    a reading of their message, not a character-range guess. It sits above the
    profile so an English request cannot fall through to a Danish CV language,
    which is the one case script detection can never settle on its own.
    """
    notes = []
    explicit = normalize_languages(requested)
    stated = normalize_language(request_language)
    if explicit:
        languages, source = list(explicit), "explicit"
    elif stated:
        languages, source = [stated], "request-language"
    else:
        detected = detect_script_language(request_text)
        if detected:
            languages, source = [detected], "request-text"
        else:
            if unattributable_script(request_text):
                notes.append(
                    "the request is in a script this tool will not attribute to a "
                    "language (only Hangul is unambiguous). Pass --request-language "
                    "once you have read the request, rather than letting it fall through."
                )
            profile = normalize_language(profile_language)
            if profile:
                languages, source = [profile], "profile"
            else:
                languages, source = ["en"], "default"

    if "en" not in languages:
        languages.append("en")

    posting = normalize_language(posting_language)
    required = normalize_language(required_language)
    submission = normalize_language(submission_language)

    suggested, suggested_source = None, None
    if submission:
        # What the user says they will send. Nothing outranks it.
        if submission not in languages:
            languages.append(submission)
            notes.append(
                f"submission language {submission!r} was not in the requested set; "
                "it is generated too, because it is what the employer receives"
            )
        primary, primary_source, confirm = submission, "submission-choice", False
    elif required:
        # An explicit instruction in the posting ("submit your CV in English").
        if required in languages:
            primary, primary_source, confirm = required, "employer-requirement", False
        else:
            primary, primary_source, confirm = None, None, True
            notes.append(
                f"the employer requires documents in {required!r}, which the bundle "
                f"({', '.join(languages)}) does not contain. Add that variant or tell the "
                "user plainly - do not submit in a language they did not ask for."
            )
    elif posting and posting not in languages:
        # Checked before the single-variant shortcut: a bundle with one
        # variant is unambiguous only when nothing suggests the employer
        # reads another language.
        primary, primary_source, confirm = None, None, True
        notes.append(
            f"the posting is written in {posting!r}, which is not in the bundle "
            f"({', '.join(languages)}). Ask which language the employer wants, and "
            "whether to add that variant."
        )
    elif len(languages) == 1:
        primary, primary_source, confirm = languages[0], "only-variant", False
    else:
        # The language the ad is written in is a hint about which variant to
        # propose, never a statement of what the employer accepts: Korean ads
        # routinely ask for an English CV, and English ads for a local-language
        # one. It is recorded as a suggestion and still needs confirming.
        primary, primary_source, confirm = None, None, True
        if posting:
            suggested, suggested_source = posting, "posting"
            notes.append(
                f"the posting is written in {posting!r}; that is a suggestion for which "
                "variant to propose, not a statement of what the employer requires. "
                "Confirm with the user before submitting."
            )
        else:
            notes.append(
                f"{len(languages)} variants and nothing stating which language the employer "
                "requires. Ask the user before submission - generated is not submitted."
            )

    return {
        "languages": languages,
        "language_source": source,
        "document_count": 2 * len(languages),
        "pdf_count": 2 * len(languages),
        "primary_language": primary,
        "primary_source": primary_source,
        "suggested_language": suggested,
        "suggested_source": suggested_source,
        "confirm_before_submission": confirm,
        "notes": notes,
    }


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------

def derive_stem(company, role):
    """documents/README.md's Subfolder naming rule, executed as documented:
    lowercase, underscores for spaces, drop every character that is not a
    letter/digit/underscore, collapse runs, trim the ends. (`\\w` is Unicode
    in Python 3, so Danish and Korean letters survive.) Returns None when the
    result is empty - the caller must stop rather than write at the root."""
    name = f"{company}_{role}".lower().replace(" ", "_")
    name = re.sub(r"[^\w]", "", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or None


def check_extension(value, label):
    if not isinstance(value, str) or not EXTENSION.match(value):
        raise BundleError(f"{label} must look like '.tex' or '.typ', got {value!r}")
    return value


def check_stem(value):
    if not isinstance(value, str) or not STEM.match(value):
        raise BundleError(
            f"invalid stem {value!r}: it must be a single path component derived by the "
            "Subfolder naming rule in documents/README.md"
        )
    return value


def check_date(value, label):
    """A date is a fact other commands do arithmetic on (days quiet, staleness).
    `--date not-a-date` used to be stored verbatim and break them silently."""
    if not isinstance(value, str) or not ISO_DATE.match(value):
        raise BundleError(f"{label} must be an ISO date (YYYY-MM-DD), got {value!r}")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise BundleError(f"{label} is not a real date: {value!r} ({exc})") from exc
    return value


def check_language(value):
    if not isinstance(value, str) or not LANGUAGE_CODE.match(value):
        raise BundleError(f"invalid language code {value!r}")
    return value


def require_english(languages):
    """Every bundle carries English. It is the variant the workflow promises
    is always there, and a caller passing `--languages ko` was silently
    getting a Korean-only application."""
    if "en" not in languages:
        raise BundleError(
            f"every bundle includes English: {', '.join(languages)} does not. "
            "Add 'en' to --languages."
        )
    return languages


def variant_paths(stem, language, cv_ext, cover_ext):
    """The four exact paths for one language. No globs, ever."""
    return {
        "cv": f"cv/main_{stem}_{language}{cv_ext}",
        "cv_pdf": f"cv/main_{stem}_{language}.pdf",
        "cover_letter": f"cover_letters/cover_{stem}_{language}{cover_ext}",
        "cover_letter_pdf": f"cover_letters/cover_{stem}_{language}.pdf",
    }


def archive_dir(stem):
    return f"{APPLICATIONS}/{stem}"


def inside_root(root, relative):
    """Whether a relative path still lands inside the workspace once symlinks
    are resolved. Recomputing a path only proves the string is ours."""
    target = (root / relative).resolve()
    base = root.resolve()
    return target == base or base in target.parents


def contained(root, relative, what):
    """inside_root as a guard: returns the absolute path or raises."""
    if not inside_root(root, relative):
        raise BundleError(
            f"{what} would leave the workspace: {relative!r} resolves outside "
            f"{root}. A symlinked directory is the usual cause; nothing is read or "
            "written through it."
        )
    return root / relative


def build_manifest(company, role, languages, cv_ext, cover_ext,
                   primary_language=None, generated=None, stem=None,
                   suggested_language=None):
    stem = check_stem(stem or derive_stem(company, role) or "")
    check_extension(cv_ext, "--cv-ext")
    check_extension(cover_ext, "--cover-ext")
    if not languages:
        raise BundleError("at least one language is required")
    for language in languages:
        check_language(language)
    require_english(languages)

    # Three labels, because they mean three different things to a reader
    # deciding whether to send the file: `confirmed` = the employer requires
    # it or the user chose it; `suggested` = the ad's language pointed here;
    # `provisional` = nothing pointed anywhere and this is just the first
    # variant. None of them means the document was sent - only
    # `submitted_language` says that, and only the user can set it.
    if primary_language is not None:
        check_language(primary_language)
        primary_status = "confirmed"
    elif suggested_language is not None:
        primary_language = check_language(suggested_language)
        primary_status = "suggested"
    else:
        primary_language, primary_status = languages[0], "provisional"
    if primary_language not in languages:
        raise BundleError(
            f"primary language {primary_language!r} is not in the bundle "
            f"({', '.join(languages)})"
        )

    return {
        "schema": SCHEMA,
        "generated": check_date(generated or date.today().isoformat(), "--today"),
        "company": company,
        "role": role,
        "stem": stem,
        "languages": list(languages),
        "cv_ext": cv_ext,
        "cover_ext": cover_ext,
        "primary_language": primary_language,
        "primary_status": primary_status,
        "submitted_language": None,
        "submitted_at": None,
        "variants": {
            language: variant_paths(stem, language, cv_ext, cover_ext)
            for language in languages
        },
    }


# --------------------------------------------------------------------------
# manifest I/O and validation
# --------------------------------------------------------------------------

def manifest_path(root, stem):
    relative = f"{archive_dir(check_stem(stem))}/{MANIFEST_NAME}"
    return contained(root, relative, "the manifest")


def load_manifest(root, stem):
    path = manifest_path(root, stem)
    if not path.is_file():
        raise BundleError(
            f"no {MANIFEST_NAME} in {archive_dir(stem)} - this application predates the "
            "bundle, or the stem is wrong. Fall back to the tracker's cv_file / "
            "cover_letter_file columns; never widen a glob to the company."
        )
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"{path} is not readable JSON: {exc}") from exc
    return validate_manifest(doc, root, expected_stem=stem)


def validate_manifest(doc, root, expected_stem=None):
    """Reject anything whose paths are not exactly what its own fields imply.

    Shape-checking a path string is not enough: `documents/applications/
    other_role/cv.tex` is shaped fine and reads another application's file.
    """
    if not isinstance(doc, dict):
        raise BundleError("manifest must be a JSON object")
    if doc.get("schema") != SCHEMA:
        raise BundleError(f"unsupported manifest schema {doc.get('schema')!r}, expected {SCHEMA!r}")

    stem = check_stem(doc.get("stem"))
    if expected_stem is not None and stem != expected_stem:
        raise BundleError(
            f"manifest stem {stem!r} does not match the folder it lives in "
            f"({expected_stem!r})"
        )
    cv_ext = check_extension(doc.get("cv_ext"), "cv_ext")
    cover_ext = check_extension(doc.get("cover_ext"), "cover_ext")

    languages = doc.get("languages")
    if not isinstance(languages, list) or not languages:
        raise BundleError("manifest languages must be a non-empty list")
    for language in languages:
        check_language(language)
    if len(set(languages)) != len(languages):
        raise BundleError(f"duplicate language in {languages}")
    require_english(languages)
    for key in ("generated", "submitted_at"):
        if doc.get(key) is not None:
            check_date(doc[key], key)

    variants = doc.get("variants")
    if not isinstance(variants, dict) or set(variants) != set(languages):
        raise BundleError(
            f"manifest variants {sorted(variants) if isinstance(variants, dict) else variants} "
            f"do not match its languages {languages}"
        )
    for language in languages:
        expected = variant_paths(stem, language, cv_ext, cover_ext)
        if variants[language] != expected:
            raise BundleError(
                f"manifest path(s) for {language!r} are not this application's: "
                f"{variants[language]!r} != {expected!r}. Re-run `plan` rather than "
                "hand-editing paths - a command follows these exactly."
            )
        for value in expected.values():
            parts = PurePosixPath(value).parts
            if len(parts) != 2 or parts[0] not in ("cv", "cover_letters") or not inside_root(root, value):
                raise BundleError(f"path escapes the document folders: {value!r}")

    for key in ("primary_language", "submitted_language"):
        value = doc.get(key)
        if value is not None:
            check_language(value)
            if value not in languages:
                raise BundleError(f"{key} {value!r} is not one of {languages}")
    return doc


def save_manifest(root, doc):
    """Atomic replace: a half-written manifest loses the record of which
    variant was submitted, which is the one fact nothing else holds."""
    path = manifest_path(root, doc["stem"])
    path.parent.mkdir(parents=True, exist_ok=True)
    # Re-check after mkdir: the parent may be (or may have just become) a link.
    contained(root, f"{archive_dir(doc['stem'])}", "the application archive folder")
    manifest_path(root, doc["stem"])
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".document_bundle.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def resolve_submitted(doc):
    """(language, source) for the variant that went to the employer. One
    variant is unambiguous, a recorded submission is a fact, anything else
    is a question for the user."""
    if doc.get("submitted_language"):
        return doc["submitted_language"], "manifest"
    if len(doc["languages"]) == 1:
        return doc["languages"][0], "only-variant"
    raise NeedsUser(
        {
            "error": "submitted_language_unknown",
            "stem": doc["stem"],
            "candidates": list(doc["languages"]),
            "primary_language": doc.get("primary_language"),
            "primary_status": doc.get("primary_status"),
            "ask": (
                "Which language variant did you actually send? Generated is not "
                "submitted, and the archive records what the employer read."
            ),
        }
    )


def same_bytes(left, right):
    """True only when both files exist and hold the same bytes. Unknown is
    False: an archive file we cannot prove came from this source must not be
    reported as a satisfied copy."""
    try:
        return left.is_file() and right.is_file() and left.read_bytes() == right.read_bytes()
    except OSError:
        return False


def archive_copies(doc, root, submitted):
    """Every variant under a `_<lang>` name, plus the submitted one again
    under the legacy `cv_draft`/`cover_letter` names /setup reads. Never
    overwrites: what is already archived is what was actually sent."""
    folder = archive_dir(doc["stem"])
    pairs = []
    for language in doc["languages"]:
        variant = doc["variants"][language]
        pairs.append((variant["cv"], f"{folder}/cv_draft_{language}{doc['cv_ext']}"))
        pairs.append(
            (variant["cover_letter"], f"{folder}/cover_letter_{language}{doc['cover_ext']}")
        )
    chosen = doc["variants"][submitted]
    pairs.append((chosen["cv"], f"{folder}/cv_draft{doc['cv_ext']}"))
    pairs.append((chosen["cover_letter"], f"{folder}/cover_letter{doc['cover_ext']}"))

    copies = []
    for source, destination in pairs:
        contained(root, source, "a draft this plan would copy")
        contained(root, destination, "an archive destination")
        if (root / destination).exists():
            skip = True
            reason = "exists" if same_bytes(root / source, root / destination) else "exists-other-variant"
        elif not (root / source).is_file():
            skip, reason = True, "missing-source"
        else:
            skip, reason = False, ""
        copies.append(
            {"source": source, "destination": destination, "skip": skip, "reason": reason}
        )
    return copies


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------

def cmd_languages(args):
    emit(
        resolve_languages(
            requested=args.requested,
            request_text=args.request_text,
            profile_language=args.profile_language,
            posting_language=args.posting_language,
            submission_language=args.submission_language,
            request_language=args.request_language,
            required_language=args.required_language,
        )
    )
    return 0


def carry_forward(new_doc, old_doc):
    """Keep a recorded submission across a redraft, or refuse the redraft.

    Rewriting the manifest from scratch would blank `submitted_language`. It
    survives only while it still describes the same file: dropping the
    submitted language, or moving its source to a new extension, is refused.
    """
    submitted = old_doc.get("submitted_language")
    if not submitted:
        return new_doc
    if submitted not in new_doc["languages"]:
        raise BundleError(
            f"this application was submitted in {submitted!r}, which the new bundle "
            f"({', '.join(new_doc['languages'])}) does not contain. Keep that language, "
            "or archive the application and start a new one - the record of what the "
            "employer received is not editable by a redraft."
        )
    if old_doc["variants"][submitted] != new_doc["variants"][submitted]:
        raise BundleError(
            f"this redraft moves the submitted {submitted!r} documents "
            f"({old_doc['variants'][submitted]['cv']} -> {new_doc['variants'][submitted]['cv']}). "
            "The archived copy is what was sent; re-point it deliberately rather than "
            "as a side effect of changing an extension."
        )
    new_doc["submitted_language"] = submitted
    new_doc["submitted_at"] = old_doc.get("submitted_at")
    # A recorded submission is also a settled primary: omitting
    # --primary-language on a redraft is not a retraction of that choice.
    if old_doc.get("primary_status") == "confirmed" and old_doc.get("primary_language") in new_doc["languages"]:
        new_doc["primary_language"] = old_doc["primary_language"]
        new_doc["primary_status"] = "confirmed"
    return new_doc


def cmd_plan(args):
    languages = normalize_languages(args.languages)
    doc = build_manifest(
        company=args.company,
        role=args.role,
        languages=languages,
        cv_ext=args.cv_ext,
        cover_ext=args.cover_ext,
        primary_language=normalize_language(args.primary_language),
        suggested_language=normalize_language(args.suggested_language),
        generated=args.today,
    )
    existing = manifest_path(args.root, doc["stem"])
    if existing.is_file():
        previous = load_manifest(args.root, doc["stem"])
        if previous.get("submitted_language") and not args.same_application:
            # Same company and role a year later derives the same stem. Carrying
            # the old submission forward would date the new application with the
            # old one's record, and the archive would claim the employer read a
            # file this run just rewrote.
            raise NeedsUser(
                {
                    "error": "existing_submission",
                    "stem": doc["stem"],
                    "submitted_language": previous["submitted_language"],
                    "submitted_at": previous.get("submitted_at"),
                    "ask": (
                        "This application already records a submission. Is this a redraft "
                        "of the SAME application (re-run with --same-application, which keeps "
                        "that record), or a new application to the same company and role? "
                        "For a new one, archive the existing folder first - nothing here "
                        "overwrites what was already sent."
                    ),
                }
            )
        doc = carry_forward(doc, previous)
    written = str(save_manifest(args.root, doc).relative_to(args.root)) if args.write else None
    primary = doc["variants"][doc["primary_language"]]
    emit(
        dict(
            doc,
            manifest=f"{archive_dir(doc['stem'])}/{MANIFEST_NAME}",
            written=written,
            tracker={
                "cv_file": primary["cv"],
                "cover_letter_file": primary["cover_letter"],
            },
        )
    )
    return 0


def cmd_resolve(args):
    doc = load_manifest(args.root, args.stem)
    submitted, source = resolve_submitted(doc)
    variant = doc["variants"][submitted]
    folder = archive_dir(doc["stem"])
    legacy_matches = all(
        same_bytes(args.root / variant[key], args.root / f"{folder}/{name}")
        for key, name in (
            ("cv", f"cv_draft{doc['cv_ext']}"),
            ("cover_letter", f"cover_letter{doc['cover_ext']}"),
        )
    )
    emit(
        {
            "stem": doc["stem"],
            "submitted_language": submitted,
            "submitted_source": source,
            "languages": doc["languages"],
            "primary_language": doc.get("primary_language"),
            "primary_status": doc.get("primary_status"),
            **variant,
            "archive": {
                "cv": f"{folder}/cv_draft{doc['cv_ext']}",
                "cover_letter": f"{folder}/cover_letter{doc['cover_ext']}",
                "cv_variant": f"{folder}/cv_draft_{submitted}{doc['cv_ext']}",
                "cover_letter_variant": f"{folder}/cover_letter_{submitted}{doc['cover_ext']}",
                # The legacy names are only *usually* the submitted pair: an
                # earlier run may have archived another variant under them, and
                # nothing is ever overwritten. Read the `_variant` paths when
                # this is false - they are unambiguous by construction.
                "legacy_pair_matches_submitted": legacy_matches,
            },
        }
    )
    return 0


def cmd_archive_plan(args):
    doc = load_manifest(args.root, args.stem)
    submitted, source = resolve_submitted(doc)
    emit(
        {
            "stem": doc["stem"],
            "submitted_language": submitted,
            "submitted_source": source,
            "copies": archive_copies(doc, args.root, submitted),
        }
    )
    return 0


def cmd_mark_submitted(args):
    doc = load_manifest(args.root, args.stem)
    parts = {
        "--language": normalize_language(args.language),
        "--cv-language": normalize_language(args.cv_language),
        "--cover-letter-language": normalize_language(args.cover_letter_language),
    }
    given = {flag: value for flag, value in parts.items() if value}
    if not given:
        raise BundleError("say which language was submitted: --language (or --cv-language and --cover-letter-language)")
    if len(set(given.values())) > 1:
        detail = ", ".join(f"{flag}={value}" for flag, value in sorted(given.items()))
        raise BundleError(
            f"mixed-language submission ({detail}) is not representable: this archive "
            "records one submitted language for the application, and writing either one "
            "would put a claim in the record the user never made. Nothing was written. "
            "Tell the user plainly that the two documents went out in different languages "
            "and that the archive cannot say so, then record nothing until they decide "
            "how to describe it."
        )
    language = check_language(next(iter(given.values())))
    if language not in doc["languages"]:
        raise BundleError(
            f"{language!r} is not one of this bundle's variants ({', '.join(doc['languages'])}). "
            "A document that was never generated cannot have been submitted."
        )
    variant = doc["variants"][language]
    missing = [
        variant[key]
        for key in ("cv", "cover_letter")
        if not contained(args.root, variant[key], "a submitted document").is_file()
    ]
    if missing:
        raise BundleError(
            f"these {language!r} documents do not exist: {', '.join(missing)}. "
            "Nothing was recorded - an employer cannot have received a file that was "
            "never written, so check the language before claiming the submission."
        )
    doc["submitted_language"] = language
    doc["submitted_at"] = check_date(args.date or date.today().isoformat(), "--date")
    save_manifest(args.root, doc)
    emit(
        {
            "stem": doc["stem"],
            "submitted_language": doc["submitted_language"],
            "submitted_at": doc["submitted_at"],
            "primary_language": doc["primary_language"],
            "manifest": f"{archive_dir(doc['stem'])}/{MANIFEST_NAME}",
        }
    )
    return 0


def emit(payload):
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)


    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    languages = sub.add_parser("languages", parents=[common], help="resolve the language set")
    languages.add_argument("--requested", help="language(s) the user explicitly asked for")
    languages.add_argument(
        "--request-text",
        help="the user's own words for this request - never the posting, which is untrusted",
    )
    languages.add_argument(
        "--request-language",
        help="the language the user's own request is written in, as you read it "
             "(use this instead of hoping script detection settles a Latin request)",
    )
    languages.add_argument("--profile-language", help="the CV language: line from CLAUDE.md")
    languages.add_argument(
        "--posting-language",
        help="the language the posting is written in - a suggestion only, never a requirement",
    )
    languages.add_argument(
        "--required-language",
        help="the language the posting explicitly requires the documents in "
             '(e.g. a Korean ad saying "submit your CV in English")',
    )
    languages.add_argument("--submission-language", help="the language the user will submit in")
    languages.set_defaults(func=cmd_languages)

    plan = sub.add_parser("plan", parents=[common], help="build (and optionally write) the manifest")
    plan.add_argument("--company", required=True)
    plan.add_argument("--role", required=True)
    plan.add_argument("--languages", required=True, help="comma-separated, e.g. ko,en")
    plan.add_argument("--cv-ext", default=".tex")
    plan.add_argument("--cover-ext", default=".tex")
    plan.add_argument(
        "--primary-language",
        help="the language the employer requires or the user chose: records `confirmed`",
    )
    plan.add_argument(
        "--suggested-language",
        help="the variant to propose when nothing states a requirement (e.g. the ad's "
             "own language): records `suggested`, which still needs confirming",
    )
    plan.add_argument("--today", help="YYYY-MM-DD, defaults to today")
    plan.add_argument(
        "--same-application",
        action="store_true",
        help="this is a redraft of the application already recorded here, not a new one: "
             "keep its submitted-language record",
    )
    plan.add_argument("--write", action="store_true", help="write it into the application archive")
    plan.set_defaults(func=cmd_plan)

    resolve = sub.add_parser("resolve", parents=[common], help="the submitted variant's paths")
    resolve.add_argument("--stem", required=True)
    resolve.set_defaults(func=cmd_resolve)

    archive = sub.add_parser("archive-plan", parents=[common], help="the copy list for /outcome")
    archive.add_argument("--stem", required=True)
    archive.set_defaults(func=cmd_archive_plan)

    mark = sub.add_parser(
        "mark-submitted",
        parents=[common],
        help="record what the user confirms they actually sent (never a plan to send)",
    )
    mark.add_argument("--stem", required=True)
    mark.add_argument("--language", help="the language of the documents the user actually sent")
    mark.add_argument("--cv-language", help="use with --cover-letter-language when reporting each separately")
    mark.add_argument("--cover-letter-language", help="must match --cv-language: see the mixed-submission error")
    mark.add_argument("--date", help="YYYY-MM-DD, defaults to today")
    mark.set_defaults(func=cmd_mark_submitted)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NeedsUser as needs:
        emit(needs.payload)
        return EXIT_NEEDS_USER
    except BundleError as exc:
        print(f"document_bundle: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
