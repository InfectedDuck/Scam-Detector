"""Link and domain analysis for family G.

Two halves, deliberately separated:

* **Offline** — confusable skeletons, edit distance against the brand list,
  punycode, shorteners, bare-IP hosts, brand-versus-host mismatch. Pure
  functions, no network, no clock. This is what runs inside the `rules_only`
  leaderboard row and inside CI.
* **Online** — following a shortener to its destination. Opt-in per call,
  never reached unless a caller passes `resolve=True`.

The online half is the only place in the project that fetches an attacker-
supplied URL, so it is written defensively: HEAD only, a scheme allowlist,
one short timeout, a hop cap, and an address check at every hop that refuses
loopback, private, link-local and other reserved ranges.

Residual risk, stated rather than hidden: the address is checked and then the
connection is made by hostname, so a DNS record that changes between the two
could still point elsewhere. Closing that hole means connecting by address and
carrying the hostname separately, which breaks certificate validation. For a
tool that issues a HEAD to a public URL the trade is acceptable; it would not
be if this ran inside a private network.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import tldextract
import yaml

DATA = Path(__file__).parent / "data" / "brands.yaml"

_tld = tldextract.TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)

ALLOWED_SCHEMES = ("http", "https")
RESOLVE_TIMEOUT = 3.0
MAX_HOPS = 5
USER_AGENT = "SaqBol-LinkCheck/0.1 (+https://github.com/saqbol)"

#: Characters that render like a Latin letter. The realistic attack on a `.kz`
#: brand is a Cyrillic letter inside an otherwise Latin domain, because both
#: scripts are on every Kazakhstani keyboard.
CONFUSABLES = {
    # Cyrillic → Latin
    "а": "a",
    "в": "b",
    "е": "e",
    "к": "k",
    "м": "m",
    "н": "h",
    "о": "o",
    "р": "p",
    "с": "c",
    "т": "t",
    "у": "y",
    "х": "x",
    "ѕ": "s",
    "і": "i",
    "ј": "j",
    "ԁ": "d",
    "һ": "h",
    "ӏ": "l",
    "ъ": "b",
    "ь": "b",
    "г": "r",
    "п": "n",
    "и": "u",
    "З": "3",
    "з": "3",
    # Greek → Latin
    "α": "a",
    "β": "b",
    "ε": "e",
    "ζ": "z",
    "η": "n",
    "ι": "i",
    "κ": "k",
    "μ": "u",
    "ν": "v",
    "ο": "o",
    "ρ": "p",
    "τ": "t",
    "υ": "u",
    "χ": "x",
    "γ": "y",
    # digit / letter pairs
    "0": "o",
    "1": "l",
    "3": "e",
    "5": "s",
    "6": "b",
    "8": "b",
    "9": "g",
}


@dataclass
class Brand:
    name: str
    region: str
    terms: tuple[str, ...]
    domains: tuple[str, ...]

    @property
    def sld(self) -> str:
        return _tld(self.domains[0]).domain if self.domains else ""


@dataclass
class UrlFacts:
    raw: str
    scheme: str = ""
    host: str = ""
    registrable: str = ""
    sld: str = ""
    suffix: str = ""
    is_ip: bool = False
    is_punycode: bool = False
    is_shortener: bool = False
    skeleton: str = ""
    lookalike_of: str | None = None
    lookalike_distance: int | None = None
    lookalike_method: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    final_registrable: str | None = None
    resolve_error: str | None = None


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_reference() -> tuple[tuple[Brand, ...], frozenset[str]]:
    raw = yaml.safe_load(DATA.read_text(encoding="utf-8")) or {}
    brands = tuple(
        Brand(
            name=b["name"],
            region=b.get("region", ""),
            terms=tuple(t.casefold() for t in b.get("terms", [])),
            domains=tuple(d.casefold() for d in b.get("domains", [])),
        )
        for b in raw.get("brands", [])
    )
    shorteners = frozenset(s.casefold() for s in raw.get("shorteners", []))
    return brands, shorteners


# --------------------------------------------------------------------------
# Offline analysis
# --------------------------------------------------------------------------


def skeleton(text: str) -> str:
    """Map a string to a canonical form in which lookalikes collapse together.

    "kaspі" with a Cyrillic i and "kaspi" with a Latin one produce the same
    skeleton, which is what makes a homograph detectable without a per-brand
    blocklist.
    """
    return "".join(CONFUSABLES.get(ch, ch) for ch in text.casefold())


def edit_distance(a: str, b: str, cap: int = 3) -> int:
    """Optimal string alignment distance, counting a transposition as one edit.

    Bounded: anything past `cap` is reported as `cap + 1`, since the caller only
    ever asks whether two labels are within a couple of edits.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1

    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > cap:
            return cap + 1
        prev2, prev = prev, cur
    return prev[len(b)]


_HIERARCHICAL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
_OPAQUE_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):(?![0-9])")


def _host_of(url: str) -> tuple[str, str]:
    """Split a link into (scheme, host), tolerating a missing scheme.

    Bare hosts are common in messages ("перейдите на kaspi.kz"), so a string
    with no scheme is read as http. That default must not be applied blindly:
    prepending it to "javascript:alert(1)" produces a URL whose host parses as
    "javascript", which would then be looked up and fetched. Opaque schemes are
    therefore rejected before the default is applied, and only a real
    scheme-plus-authority is parsed as written.
    """
    text = url.strip()
    if _HIERARCHICAL.match(text):
        parsed = urlparse(text)
    else:
        opaque = _OPAQUE_SCHEME.match(text)
        if opaque:
            # data:, javascript:, mailto:, file: without an authority. The
            # negative lookahead keeps "kaspi.kz:8080/path" out of this branch.
            return opaque.group(1).casefold(), ""
        parsed = urlparse("http://" + text)
    return (parsed.scheme or "").casefold(), (parsed.hostname or "").casefold()


def canonical_url(url: str) -> str | None:
    """The absolute URL to fetch, or None when the input is not fetchable.

    The single place the missing-scheme default is applied. Duplicating it at a
    call site is how "javascript:alert(1)" became "http://javascript:alert(1)"
    and slipped past the scheme allowlist.
    """
    text = url.strip()
    if _HIERARCHICAL.match(text):
        return text
    if _OPAQUE_SCHEME.match(text):
        return None
    return "http://" + text


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def analyse_url(url: str, *, resolve: bool = False) -> UrlFacts:
    """Everything family G needs to know about one link."""
    brands, shorteners = load_reference()
    scheme, host = _host_of(url)
    facts = UrlFacts(raw=url, scheme=scheme, host=host)

    if not host:
        return facts

    if _is_ip(host):
        facts.is_ip = True
        facts.registrable = host
        return facts

    parts = _tld(host)
    facts.sld = parts.domain
    facts.suffix = parts.suffix
    facts.registrable = ".".join(p for p in (parts.domain, parts.suffix) if p)
    facts.is_punycode = "xn--" in host
    facts.is_shortener = facts.registrable in shorteners
    facts.skeleton = skeleton(facts.sld)

    official = {d for b in brands for d in b.domains}
    if facts.registrable not in official:
        best: tuple[int, str, str] | None = None
        for brand in brands:
            target = skeleton(brand.sld)
            if not target or len(facts.skeleton) < 4:
                continue
            if facts.skeleton == target:
                best = (0, brand.name, "confusable")
                break
            distance = edit_distance(facts.skeleton, target)
            if distance <= 2 and (best is None or distance < best[0]):
                best = (distance, brand.name, "edit")
        if best is not None:
            facts.lookalike_distance, facts.lookalike_of, facts.lookalike_method = best

    if resolve and (facts.is_shortener or facts.lookalike_of):
        chain, final, error = resolve_redirects(url)
        facts.redirect_chain = chain
        facts.resolve_error = error
        if final:
            final_parts = _tld(final)
            facts.final_registrable = ".".join(
                p for p in (final_parts.domain, final_parts.suffix) if p
            )

    return facts


def brands_named_in(text: str) -> list[Brand]:
    """Brands the message talks about, matched on their written forms."""
    lowered = text.casefold()
    return [b for b in load_reference()[0] if any(term in lowered for term in b.terms)]


def official_domains(brand: Brand) -> set[str]:
    return set(brand.domains)


# --------------------------------------------------------------------------
# Online resolution. Never reached unless a caller opts in.
# --------------------------------------------------------------------------


def _address_is_public(host: str) -> bool:
    """Refuse anything that resolves into a range the internet does not route."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            return False
    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Each hop is inspected before the next is made, so nothing auto-follows."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_redirects(url: str) -> tuple[list[str], str | None, str | None]:
    """Follow a link by HEAD, one checked hop at a time.

    Returns the chain walked, the final host, and an error label. Failure is
    normal and never raises: an unreachable link simply produces no G4 or G5
    evidence, and a verdict must not depend on a third party being up.
    """
    opener = urllib.request.build_opener(_NoRedirect)
    chain: list[str] = []
    current = canonical_url(url)
    if current is None:
        return chain, None, "scheme_not_allowed"

    for _ in range(MAX_HOPS):
        scheme, host = _host_of(current)
        if scheme not in ALLOWED_SCHEMES:
            return chain, None, "scheme_not_allowed"
        if not host:
            return chain, None, "no_host"
        # Covers bare addresses too: getaddrinfo accepts a literal IP and
        # returns it, so one check refuses both a private hostname and a
        # private literal.
        if not _address_is_public(host):
            return chain, None, "address_not_public"

        chain.append(current)
        request = urllib.request.Request(current, method="HEAD", headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=RESOLVE_TIMEOUT) as response:
                return chain, _host_of(response.url)[1] or host, None
        except urllib.error.HTTPError as err:
            location = err.headers.get("Location") if err.headers else None
            if err.code in (301, 302, 303, 307, 308) and location:
                current = urllib.parse.urljoin(current, location)
                continue
            return chain, host, None
        except (urllib.error.URLError, OSError, ValueError):
            return chain, None, "unreachable"

    return chain, None, "too_many_hops"
