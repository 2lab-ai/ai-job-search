#!/usr/bin/env python3
"""The search locale of one run: which language to prefer, which market.

A run that should surface Korean postings says so as an argument
(`--request-language ko`), never as a deduction. Two rules fall out of that,
and they are the reason this module exists rather than a few inline regexes:

  * **The request language is a search instruction, never a proficiency
    claim.** "Find me Korean jobs" says nothing about how well the user reads
    Korean. `04-job-evaluation.md`'s Language Gate - the PASS/FAIL/FLAG verdict
    about the *candidate* - keeps taking its input from the candidate profile's
    Languages table alone. Nothing here writes, weakens or strengthens it.

  * **An explicit argument beats an inferred signal.** `--market` beats the
    market implied by the language (a Korean speaker can search Denmark), and
    a stated place beats the portal's own country (Korean boards advertise
    overseas roles, and `kr.linkedin.com` is a localized domain that serves the
    whole world - reading a market off that host would file a Berlin job under
    Korea).

Preference is a **grouping**: matching rows move ahead of non-matching ones,
and the order inside each group is left exactly as the caller had it. It never
edits a score, a band, or a veto - `/rank`'s thresholds and deal-breakers are
untouched by which locale a run asked for.

The alias tables are deliberately small and open: an unknown two-letter tag
passes through, so this never becomes the list of languages the repo allows.
Two limits of that passthrough, stated rather than papered over:

  * a two-letter tag is accepted **unvalidated** - it is not checked against
    ISO 639-1, so a typo that happens to be two letters becomes a language
    nobody searches in. The cost of the alternative (a closed list) is worse.
  * the one refusal is a value this module already knows as a *market*
    (`KR`, `Korea`, `dk`, `USA`, …) passed to the language flag, because that
    silently produced a run with no market at all. `kr` is refused under that
    rule even though ISO 639-1 `kr` is Kanuri: Kanuri is not supported here and
    the ko/KR mix-up is the realistic case, so the error names the flag to use
    instead of calling the tag invalid.
"""

import unicodedata
from urllib.parse import urlsplit

# Canonical short tag -> the spellings a user (or a portal) might type.
# Compared after fold_text(), so separators and case are already gone.
LANGUAGE_ALIASES: dict[str, tuple[str, ...]] = {
    "ko": ("ko", "kor", "kokr", "korean", "한국어", "국문", "한글"),
    "en": ("en", "eng", "enus", "engb", "english", "영어", "영문"),
    "da": ("da", "dan", "dadk", "danish", "dansk", "덴마크어"),
}

MARKET_ALIASES: dict[str, tuple[str, ...]] = {
    "KR": ("kr", "kor", "korea", "southkorea", "republicofkorea", "koreasouth", "한국", "대한민국", "남한"),
    "DK": ("dk", "dnk", "denmark", "danmark", "덴마크"),
    "US": ("us", "usa", "unitedstates", "unitedstatesofamerica", "미국"),
}

# Only where a language maps to one market unambiguously. English does not.
MARKET_FOR_LANGUAGE: dict[str, str] = {"ko": "KR", "da": "DK"}

# Place-name hints, used only when an entry carries no verified market. Best
# effort by design: a miss leaves the entry unmatched rather than guessed at.
MARKET_PLACE_HINTS: dict[str, tuple[str, ...]] = {
    "KR": ("korea", "seoul", "incheon", "busan", "pangyo", "seongnam",
           "한국", "대한민국", "서울", "경기", "판교", "성남", "부산", "인천"),
    "DK": ("denmark", "danmark", "copenhagen", "kobenhavn", "københavn", "aarhus", "odense"),
    "US": ("unitedstates", "usa", "미국"),
}

# Work arrangements, not places. A location field holding only one of these
# answers "how", not "where": it is skipped so the next field is read, instead
# of being taken as "a stated place that is not the target market".
WORK_ARRANGEMENT_MARKERS: tuple[str, ...] = (
    "remote", "fullyremote", "workfromhome", "wfh", "hybrid", "onsite", "anywhere", "flexible",
    "재택근무", "재택", "원격근무", "원격", "하이브리드", "무관",
)

# Hosts that localize their domain per visitor rather than per market. A
# posting on kr.linkedin.com can be anywhere, so the host proves nothing.
LOCALIZED_HOSTS: tuple[str, ...] = ("linkedin.com", "indeed.com", "glassdoor.com", "google.com")

# Last labels that are generic rather than a country.
_NON_COUNTRY_TLDS = frozenset(
    {"com", "org", "net", "edu", "gov", "int", "mil", "info", "biz", "io", "co", "me", "ai", "app", "dev", "jobs"}
)

_HANGUL_RANGES = ((0xAC00, 0xD7A3), (0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F))


def fold_text(value) -> str:
    """Case- and punctuation-insensitive form that keeps every script.

    The previous folding was `[^a-z0-9]` deletion, which erases Hangul (and
    Cyrillic, and Greek) outright: every Korean company folded to "" and so
    matched every other Korean company. NFKC first, so a decomposed Hangul
    syllable from one portal folds to the same value as the composed one from
    the next.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return unicodedata.normalize("NFC", "".join(ch for ch in text if ch.isalnum()))


def language_alias(value) -> str | None:
    """The tag `value` is a *known* spelling of, ignoring the passthrough."""
    folded = fold_text(value)
    for tag, aliases in LANGUAGE_ALIASES.items():
        if folded and folded in aliases:
            return tag
    return None


def market_alias(value) -> str | None:
    """The market code `value` is a *known* spelling of, ignoring the passthrough."""
    folded = fold_text(value)
    for code, aliases in MARKET_ALIASES.items():
        if folded and folded in aliases:
            return code
    return None


def normalize_language(value) -> str | None:
    """Canonical short language tag ("ko"), or None when nothing is recognized."""
    known = language_alias(value)
    if known:
        return known
    folded = fold_text(value)
    if len(folded) == 2 and folded.isascii() and folded.isalpha():
        return folded
    return None


def normalize_market(value) -> str | None:
    """Canonical upper-case market code ("KR"), or None when unrecognized."""
    folded = fold_text(value)
    if not folded:
        return None
    for code, aliases in MARKET_ALIASES.items():
        if folded in aliases:
            return code
    if len(folded) == 2 and folded.isascii() and folded.isalpha():
        return folded.upper()
    return None


def resolve_locale(request_language=None, market=None) -> dict:
    """The locale of one run: {language, market, market_source}.

    `market_source` is "explicit" when the user named the market and
    "inferred" when it came from the language, because the two rank
    differently: an explicit market leads the ordering, an inferred one only
    fills the second group behind the requested language.
    """
    language = None
    if request_language not in (None, ""):
        # A market handed to the language flag used to resolve to a two-letter
        # "language" with no market, which put every posting in the bottom
        # group - a typo that looked like a working run. Refused only for
        # spellings this module actually knows as markets, and the refusal is a
        # local disambiguation, not a claim about ISO: `kr` *is* ISO 639-1
        # Kanuri, which this tool does not support, so the message says which
        # flag to use rather than calling the tag invalid.
        as_market = market_alias(request_language)
        if as_market and not language_alias(request_language):
            raise ValueError(
                f"{request_language!r} names a market here, not a language: use "
                f"--market {as_market} (with --request-language <language>, e.g. ko for Korean)"
            )
        language = normalize_language(request_language)
        if language is None:
            raise ValueError(f"unrecognized request language: {request_language!r}")

    code, source = None, None
    if market not in (None, ""):
        code = normalize_market(market)
        if code is None:
            raise ValueError(f"unrecognized market: {market!r}")
        source = "explicit"
    elif language:
        code = MARKET_FOR_LANGUAGE.get(language)
        source = "inferred" if code else None

    return {"language": language, "market": code, "market_source": source}


def is_active(locale: dict) -> bool:
    """True when this run asked for a locale at all. A generic run does not,
    and then nothing in this module reorders or annotates anything."""
    return bool(locale) and bool(locale.get("language") or locale.get("market"))


def script_language(text) -> str | None:
    """The language a script gives away - Hangul means Korean.

    **Ordering and presentation only.** It is never persisted as the posting's
    language: a Hangul title can head an English posting, and a stored fact has
    to come from the posting itself (the scoring agent's `language`), not from
    a character-range test. Latin script is shared by dozens of languages, so
    it yields nothing rather than a guess.
    """
    for ch in unicodedata.normalize("NFC", str(text or "")):
        code = ord(ch)
        if any(low <= code <= high for low, high in _HANGUL_RANGES):
            return "ko"
    return None


def place_market(text) -> str | None:
    """Market implied by a place name, or None. Best effort, never a claim."""
    folded = fold_text(text)
    if not folded:
        return None
    for code, hints in MARKET_PLACE_HINTS.items():
        if any(fold_text(hint) in folded for hint in hints):
            return code
    return None


def is_work_arrangement(text) -> bool:
    """True when a location field says *how* the work happens, not where.

    Only when that is all it says: "Remote (Seoul)" still names Seoul, and
    place_market() is consulted first, so this never swallows a real place.
    """
    folded = fold_text(text)
    if not folded:
        return False
    for marker in sorted((fold_text(m) for m in WORK_ARRANGEMENT_MARKERS), key=len, reverse=True):
        folded = folded.replace(marker, "")
    return not folded


def host_market(url) -> str | None:
    """Market implied by a ccTLD - the weakest signal, and skipped entirely for
    hosts that localize their domain rather than their market."""
    host = urlsplit(str(url or "")).hostname or ""
    if not host:
        return None
    if any(host == localized or host.endswith("." + localized) for localized in LOCALIZED_HOSTS):
        return None
    tld = host.rsplit(".", 1)[-1].lower()
    if len(tld) == 2 and tld.isalpha() and tld not in _NON_COUNTRY_TLDS:
        return tld.upper()
    return None


def entry_language(entry: dict) -> str | None:
    """The language to order a stored entry by: the persisted posting language
    when `/rank` recorded one, else what the script of its text suggests."""
    stored = normalize_language(entry.get("posting_language"))
    if stored:
        return stored
    return script_language(f"{entry.get('title') or ''} {entry.get('company') or ''}")


def entry_market(entry: dict) -> str | None:
    """The market of a stored entry, most trustworthy signal first:

    1. `market` - verified and persisted by `/rank` from the posting itself
    2. `location_verified` - the place the scoring agent read in the posting
    3. `location` - the place the scraper recorded
    4. the URL's ccTLD - last resort, and never for a localized host

    A field holding only a work arrangement ("Remote", "재택근무") is skipped
    rather than treated as a place, so the next field still gets read. A field
    holding a *real* place that maps to no known market stops the search and
    returns None: falling through to the host from there is exactly how a
    Berlin posting found on a .kr board would be filed under Korea.
    """
    verified = normalize_market(entry.get("market"))
    if verified:
        return verified
    for field in ("location_verified", "location"):
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip() or value in ("PASS", "FAIL", "FLAG"):
            continue
        found = place_market(value)
        if found:
            return found
        if is_work_arrangement(value):
            continue
        return None  # a stated place that is not the target market is an answer
    return host_market(entry.get("url"))


def preference_tier(entry: dict, locale: dict) -> int:
    """0 = leading group, 1 = second group, 2 = everything else.

    With an explicit `--market` the market leads (the user named it); with a
    market only inferred from the request language, the language leads.
    """
    if not is_active(locale):
        return 0
    language_hit = bool(locale.get("language")) and entry_language(entry) == locale["language"]
    market_hit = bool(locale.get("market")) and entry_market(entry) == locale["market"]
    first, second = (
        (market_hit, language_hit) if locale.get("market_source") == "explicit" else (language_hit, market_hit)
    )
    if first:
        return 0
    if second:
        return 1
    return 2


def sort_by_preference(rows: list, locale: dict, key=None) -> list:
    """Regroup rows by preference tier, stable within each tier.

    `key` maps a row to the entry the tier is computed from, for callers whose
    rows are projections of a stored entry rather than the entry itself.
    """
    if not is_active(locale):
        return list(rows)
    pick = key or (lambda row: row)
    return sorted(rows, key=lambda row: preference_tier(pick(row), locale))
