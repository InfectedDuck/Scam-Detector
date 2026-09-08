"""Family G — link and domain risk.

Every rule here is offline. Redirect following is opt-in and lives in
`url_analyzer`; when a caller has not resolved a link, G4 simply produces no
evidence rather than guessing at a destination.

G6 follows the same rule as family I: domain age is a fact the text cannot
supply, so it reads `metadata["domain_ages"]` and returns nothing when no
enrichment step has filled it. Kazakhstani registry WHOIS is unreliable, and
a verdict must never depend on a third party answering.
"""

from __future__ import annotations

from saqbol.core.indicators.registry import DetectionContext, indicator
from saqbol.core.types import IndicatorHit, Severity
from saqbol.core.url_analyzer import UrlFacts, analyse_url, load_reference

#: A resolved chain longer than this suggests deliberate obfuscation rather
#: than the one hop a normal shortener makes.
REDIRECT_HOPS_SUSPICIOUS = 2

#: Domains younger than this are treated as fresh. Ninety days is the usual
#: window in which throwaway phishing domains are registered and abandoned.
FRESH_DOMAIN_DAYS = 90


def _facts(ctx: DetectionContext) -> list[UrlFacts]:
    """Analyse each link once and cache it on the context.

    Redirect chains may arrive two ways: from a live resolution when the caller
    opted in, or from `metadata["redirect_chains"]` when an enrichment step
    resolved them earlier. The second path is what keeps G4 reachable offline,
    and it matches how G6 receives domain ages.
    """
    cached = ctx.metadata.get("_url_facts")
    if cached is not None:
        return cached

    resolve = bool(ctx.metadata.get("resolve_links"))
    supplied = ctx.metadata.get("redirect_chains") or {}
    facts = []
    for url in ctx.entities.urls:
        fact = analyse_url(url, resolve=resolve)
        if not fact.redirect_chain and url in supplied:
            fact.redirect_chain = list(supplied[url])
        facts.append(fact)

    ctx.metadata["_url_facts"] = facts
    return facts


def _hit(indicator_id: str, severity: Severity, detail: dict) -> IndicatorHit:
    return IndicatorHit(indicator_id=indicator_id, severity=severity, detail=detail)


@indicator("G1.lookalike_domain", Severity.HIGH, "Domain imitates a known brand")
def lookalike_domain(ctx: DetectionContext) -> list[IndicatorHit]:
    found = [f for f in _facts(ctx) if f.lookalike_of]
    if not found:
        return []
    return [
        _hit(
            "G1.lookalike_domain",
            Severity.HIGH,
            {
                "domains": [
                    {
                        "host": f.host,
                        "lookalike_of": f.lookalike_of,
                        "distance": f.lookalike_distance,
                        "method": f.lookalike_method,
                    }
                    for f in found
                ]
            },
        )
    ]


@indicator("G2.punycode_idn", Severity.HIGH, "Internationalised domain encoded as punycode")
def punycode_idn(ctx: DetectionContext) -> list[IndicatorHit]:
    hosts = [f.host for f in _facts(ctx) if f.is_punycode]
    return [_hit("G2.punycode_idn", Severity.HIGH, {"hosts": hosts})] if hosts else []


@indicator("G3.shortener", Severity.MEDIUM, "Link shortener hides the destination")
def shortener(ctx: DetectionContext) -> list[IndicatorHit]:
    hosts = [f.host for f in _facts(ctx) if f.is_shortener]
    return [_hit("G3.shortener", Severity.MEDIUM, {"hosts": hosts})] if hosts else []


@indicator("G4.long_redirect_chain", Severity.MEDIUM, "Link passes through several hops")
def long_redirect_chain(ctx: DetectionContext) -> list[IndicatorHit]:
    chains = [f for f in _facts(ctx) if len(f.redirect_chain) > REDIRECT_HOPS_SUSPICIOUS]
    if not chains:
        return []
    return [
        _hit(
            "G4.long_redirect_chain",
            Severity.MEDIUM,
            {"chains": [{"from": f.host, "hops": len(f.redirect_chain)} for f in chains]},
        )
    ]


@indicator("G5.brand_mismatch", Severity.HIGH, "Host borrows a brand name but is not its domain")
def brand_mismatch(ctx: DetectionContext) -> list[IndicatorHit]:
    """The most common phishing shape, and the one a lookalike check misses.

    "kaspi-secure.ru" is nowhere near "kaspi.kz" by edit distance, so G1 stays
    quiet. What gives it away is that the host wears the brand's name while its
    registrable domain belongs to someone else.

    Keyed on the host rather than on the message body, deliberately. A message
    that mentions a bank and also links to an unrelated but legitimate site is
    ordinary; a host with the bank's name in it is not.
    """
    brands, _ = load_reference()
    mismatches = []
    for facts in _facts(ctx):
        if not facts.host or facts.is_ip:
            continue
        for brand in brands:
            if facts.registrable in brand.domains:
                continue
            hit_term = next((t for t in brand.terms if t in facts.host.casefold()), None)
            if hit_term:
                mismatches.append(
                    {"host": facts.host, "claims": brand.name, "registrable": facts.registrable}
                )
                break
    if not mismatches:
        return []
    return [_hit("G5.brand_mismatch", Severity.HIGH, {"mismatches": mismatches})]


@indicator("G6.fresh_domain", Severity.LOW, "Domain registered recently")
def fresh_domain(ctx: DetectionContext) -> list[IndicatorHit]:
    ages = ctx.metadata.get("domain_ages")
    if not ages:
        return []
    fresh = [
        {"host": f.host, "age_days": ages[f.registrable]}
        for f in _facts(ctx)
        if f.registrable in ages
        and ages[f.registrable] is not None
        and ages[f.registrable] < FRESH_DOMAIN_DAYS
    ]
    return [_hit("G6.fresh_domain", Severity.LOW, {"domains": fresh})] if fresh else []


@indicator("G7.qr_payload_risk", Severity.HIGH, "Decoded QR code carries a risky link")
def qr_payload_risk(ctx: DetectionContext) -> list[IndicatorHit]:
    """A QR code is a link the recipient cannot read before following it.

    The payload is run through the same analysis as a written link, so a
    lookalike or a brand mismatch inside a printed code is caught exactly as it
    would be in the message body.
    """
    risky = []
    for payload in ctx.entities.qr_payloads:
        facts = analyse_url(payload)
        if facts.lookalike_of or facts.is_punycode or facts.is_shortener or facts.is_ip:
            risky.append({"payload_host": facts.host, "lookalike_of": facts.lookalike_of})
    return [_hit("G7.qr_payload_risk", Severity.HIGH, {"payloads": risky})] if risky else []


@indicator("G8.ip_url", Severity.MEDIUM, "Bare IP address in place of a hostname")
def ip_url(ctx: DetectionContext) -> list[IndicatorHit]:
    hosts = [f.host for f in _facts(ctx) if f.is_ip]
    return [_hit("G8.ip_url", Severity.MEDIUM, {"hosts": hosts})] if hosts else []
