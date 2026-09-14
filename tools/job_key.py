#!/usr/bin/env python3
"""Canonical dedup key for a job posting, and an audit for existing state.

`/scrape` Step 4 keys every seen_jobs.json entry by company+title. The rule was
prose only ("<url_or_company_title_key>"), so each run slugified in its own way
and the state file accumulated two distinct failures:

  * Keys carrying characters that break things downstream. `/apply` and
    `/outcome` derive an archive folder name from the same company+role pair,
    and documents/README.md's subfolder rule exists because a "/" splits that
    path across directories. Real examples found in a live workspace:
    "deloitte_junior-cybersecurity-analyst-(ot/iot)",
    "neverhack-estonia_penetration-tester-/-red-teamer",
    "ops-consulting,-llc_malware-analyst".

  * The same job stored twice under different keys, because one run truncated
    the title at a different point than the next. "deloitte_cyber-intelligence-
    center-security-analy" and "deloitte_cyber-intelligence-center-security-
    analyst-at" are one posting, one URL, two entries - and dedup is the whole
    point of the file.

Both are fixed by making the key a pure, deterministic function of the posting.
Truncation is length-capped *and* disambiguated by a hash of the full slug, so a
long title always produces the same key and two different long titles never
collide.

A title that slugifies to nothing (a posting written in a non-Latin script) has
no usable key half at all - "securion_" was a real entry, and it would have
collided with every future non-Latin posting from that company. Those fall back
to the portal's numeric id from the URL.

The same hole was open on the company half, and it collided silently: both
make_key("카카오", "개발자", <url with id 123456>) and make_key("네이버",
"개발자", <same id>) produced "unknown-company_123456" - two employers, one
entry. A company (or title) that slugifies to nothing now falls back to a hash
of its NFC-normalized original text, so distinct Korean employers get distinct
keys and the same posting keys identically whether the portal shipped composed
or decomposed Hangul.

Mixed script is the same failure with a disguise: "회사A" slugifies to "a", not
to "", so the empty-slug fallback never fired and "회사A" and "다른A" keyed
identically again. Whenever transliteration drops non-Latin characters, the
slug keeps its readable Latin remnant *and* carries a hash of the original -
"a-9f3c1d". The check is by script, not by ASCII-ness, so Latin letters that
already transliterate (ø, ß, é -> "sborg", "strae", "cafe") are untouched and
existing Danish and German keys keep matching. The key itself stays ASCII on purpose: `/apply` and
`/outcome` derive an archive folder stem from it, and that contract is
unchanged. Latin keys are byte-for-byte what they were.

Usage:
  python3 tools/job_key.py --company "Acme Corp" --title "SOC Analyst (L2)"
  python3 tools/job_key.py --audit job_scraper/seen_jobs.json

Exit 0 when a key is produced, or when an audit finds nothing. Exit 1 when an
audit finds violations.
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from search_locale import fold_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "job_scraper" / "seen_jobs.json"

COMPANY_MAX = 40
TITLE_MAX = 60
HASH_LEN = 6

# Anything outside this set becomes a separator. Deliberately strict: "/" and
# "," are the characters that actually caused damage, and an allowlist cannot
# be surprised by the next punctuation mark a job board invents.
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_JOB_ID = re.compile(r"(\d{6,})")


def slugify(text: str) -> str:
    """Lowercase ASCII slug. Non-Latin scripts legitimately reduce to ''."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return _NON_SLUG.sub("-", ascii_only.lower()).strip("-")


def _cap(slug: str, limit: int) -> str:
    """Cap length without making truncation lossy across runs.

    A bare truncation is what produced the duplicate Deloitte entries: two runs
    cut the same title at different points and the file gained a second key for
    one job. Appending a hash of the *full* slug makes the result deterministic
    for a given title and distinct for any other.
    """
    if len(slug) <= limit:
        return slug
    digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:HASH_LEN]
    return f"{slug[:limit].rstrip('-')}-{digest}"


def has_lost_differentiator(text) -> bool:
    """True when slugifying `text` throws away non-Latin characters.

    An empty slug is the obvious case; this is the one that hid behind a
    surviving Latin remnant: "회사A" slugifies to "a", not "", so the
    empty-slug fallback never fired and "회사A" and "다른A" keyed identically.

    The test is *script*, not ASCII-ness: ø, ß and é are Latin letters that
    already transliterate ("sborg", "strae", "cafe"), and treating them as lost
    would change the key of every existing Danish and German entry.

    Normalized NFKC, to match the compatibility folding the slug already does.
    `slugify` runs NFKD, so ＮＨＮ is already "NHN" and Ⅲ is already "III" -
    nothing lost - but testing the NFC form saw characters named FULLWIDTH… and
    ROMAN NUMERAL…, judged them non-Latin, and keyed one employer two ways
    depending on which form the portal emitted. NFKC keeps the cases that *are*
    differentiators: ㈜ expands to (주), still Hangul, still hashed.
    """
    for ch in unicodedata.normalize("NFKC", str(text or "")):
        if not ch.isalnum() or ch.isascii():
            continue
        name = unicodedata.name(ch, "")
        if not name.startswith("LATIN") and not name.startswith("DIGIT"):
            return True
    return False


def _differentiate(slug: str, text: str, limit: int) -> str:
    """Re-attach, as a hash, what the ASCII slug could not carry.

    The hash covers the *full* original text, so it also subsumes `_cap`'s own
    truncation hash - a long mixed-script title needs one disambiguator, not
    two - and it is taken over the folded (NFKC + casefolded) form, so the
    composed and decomposed spellings of one name produce one key.
    """
    if not slug or not has_lost_differentiator(text):
        return slug
    digest = hashlib.sha1(fold_text(text).encode("utf-8")).hexdigest()[:HASH_LEN]
    return f"{slug[: max(1, limit - HASH_LEN - 1)].rstrip('-')}-{digest}"


def _hashed(text: str, prefix: str) -> str:
    """An ASCII stand-in for text no slug survives, distinct per text.

    Hashing the folded (NFKC + casefolded) form is what makes the key stable:
    the same Korean company name arrives composed from one portal and
    decomposed from the next, and those two byte strings must not become two
    entries for one employer.
    """
    digest = hashlib.sha1(fold_text(text).encode("utf-8")).hexdigest()[:HASH_LEN]
    return f"{prefix}-{digest}"


def make_key(company: str, title: str, url: str = "") -> str:
    """The canonical seen_jobs.json key for one posting."""
    company_slug = _differentiate(_cap(slugify(company), COMPANY_MAX), company, COMPANY_MAX)
    if not company_slug:
        # No Latin characters in the company name. "unknown-company" is only
        # honest when there is no name at all - using it for a Korean employer
        # merges every Korean employer into one key.
        company_slug = _hashed(company, "company") if fold_text(company) else "unknown-company"
    title_slug = _differentiate(_cap(slugify(title), TITLE_MAX), title, TITLE_MAX)
    if not title_slug:
        # No Latin characters in the title. The portal's own numeric id is the
        # only stable handle left; never emit a bare "company_" prefix.
        match = _JOB_ID.search(url or "")
        if match:
            title_slug = match.group(1)
        elif fold_text(title):
            title_slug = _hashed(title, "title")
        else:
            digest = hashlib.sha1((str(title) + str(url)).encode("utf-8")).hexdigest()[:HASH_LEN]
            title_slug = f"untitled-{digest}"
    return f"{company_slug}_{title_slug}"


# A canonical key is "<company-slug>_<title-slug>": lowercase alphanumerics and
# hyphens on either side of exactly one underscore. The underscore is the
# separator, so it is the one character outside the slug alphabet that belongs.
_CANONICAL = re.compile(r"^[a-z0-9][a-z0-9-]*_[a-z0-9][a-z0-9-]*$")


def is_canonical(key: str) -> bool:
    """Structurally safe as a dedup key and as an archive folder name."""
    return bool(key) and bool(_CANONICAL.match(key))


def is_legacy_shape(key: str) -> bool:
    """Old three-part "company_title_location" keys.

    Harmless - they carry no path-breaking character - but they are not what
    make_key produces, so a later run would store the same job under a new key
    and reintroduce a duplicate. Reported apart from real damage so the fix
    stays a decision rather than an automatic rename.
    """
    return bool(key) and key.count("_") > 1 and all(
        re.fullmatch(r"[a-z0-9][a-z0-9-]*", part) for part in key.split("_") if part
    )


def audit(path: Path) -> int:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        return 1
    seen = doc.get("seen", doc)
    if not isinstance(seen, dict):
        print(f"{path}: expected an object of job entries", file=sys.stderr)
        return 1

    malformed = [k for k in seen if not is_canonical(k) and not is_legacy_shape(k)]
    legacy = [k for k in seen if is_legacy_shape(k)]
    by_url: dict[str, list[str]] = {}
    for key, entry in seen.items():
        url = (entry.get("url") or "").rstrip("/")
        if url:
            by_url.setdefault(url, []).append(key)
    duplicates = {u: ks for u, ks in by_url.items() if len(ks) > 1}
    # A key that does not match what make_key would produce today is drift, not
    # damage: reported separately so a rename is a choice, never automatic.
    drift = [
        k for k, v in seen.items()
        if is_canonical(k) and k != make_key(v.get("company", ""), v.get("title", ""), v.get("url", ""))
    ]

    print(json.dumps({
        "entries": len(seen),
        "malformed_keys": malformed,
        "legacy_three_part_keys": legacy,
        "duplicate_urls": duplicates,
        "keys_not_matching_current_rule": len(drift),
    }, indent=2, ensure_ascii=False))
    return 1 if (malformed or duplicates) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--company")
    ap.add_argument("--title")
    ap.add_argument("--url", default="")
    ap.add_argument("--audit", nargs="?", const=str(STATE), metavar="STATE_JSON")
    args = ap.parse_args()

    if args.audit:
        return audit(Path(args.audit))
    if args.company is None or args.title is None:
        ap.error("give --company and --title, or --audit")
    print(make_key(args.company, args.title, args.url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
