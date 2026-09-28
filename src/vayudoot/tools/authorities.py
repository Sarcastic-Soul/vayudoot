"""Jurisdiction lookup.

The authority table is data, not code, and is keyed by administrative region
rather than hardcoded to one country. That is what lets the same agent be
pointed at a different state, or a different country, without a rewrite.

**One file per country.** `data/authorities.example.json` is India's table, and
`data/authorities.<cc>.example.json` is any other country's — `za` for South
Africa, `br` for Brazil. Each file says which country it covers in its own
`country` field, and that field is what this module keys on; the file name is
for people. Separate files rather than one file with a country level, because a
country's table is written and reviewed by somebody who knows that country, and a
diff that touches one country should touch one file.

**Overrides work per file.** `authorities.json` replaces `authorities.example.json`
and `authorities.<cc>.json` replaces `authorities.<cc>.example.json`. The
override files hold real addresses, so they are never committed; the example
files are, and every address in them is on the reserved `.invalid` TLD (hard
constraint 1, asserted by `tests/test_filing_safety.py` for every file here).

**The countries served are the countries with a table.** Nothing in Python lists
them. A hotspot or a report in a country with no table is refused rather than
resolved: each table's generic fallback is a placeholder for a region of *that*
country the table does not name, and using India's to address a Brazilian fire
would be inventing an authority.

**A response window is stated only when a statute states one.** Indian rules
set deadlines for some duties; South Africa's and Brazil's air quality law sets
none for answering a complaint. Those tables carry `response_window_days: null`
with a note saying so, and the lookup substitutes the table's `follow_up_days` —
the interval after which this system suggests following up — and marks it
`response_window_statutory: false`. The escalation clock needs a number; a
citizen needs to know the number is ours and not the law's.
"""

from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

from strands import tool

from ..config import settings

#: Where the tables live. India's keep their original names,
#: `authorities.example.json` and `authorities.json`, which the rest of the
#: repository and its documentation already cite.
_DIR = Path(__file__).resolve().parent.parent / "data"
#: A table that predates the `country` field is India's.
_LEGACY_COUNTRY = "IN"
#: What a table without `follow_up_days` waits before suggesting a follow-up,
#: when no statute sets a window. The same thirty days clustering treats as the
#: default window, so the two clocks agree.
_DEFAULT_FOLLOW_UP_DAYS = 30


def _key(text: str) -> str:
    """A region or city name as the table keys it: lower case, no accents.

    Nominatim answers "Pará" and "São Paulo"; a person editing JSON types
    "para" as often as "pará". Folding both sides means neither spelling is a
    miss, and India's ASCII keys are unchanged by it.
    """
    decomposed = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _country(code: str | None) -> str:
    """An ISO 3166-1 alpha-2 code, lower case. Empty means this node's country."""
    return (code or settings.vayudoot_node_country or _LEGACY_COUNTRY).strip().lower()


@lru_cache(maxsize=1)
def _tables() -> dict[str, dict]:
    """Every country's table, keyed by lower-case country code.

    For each table name, the uncommitted override wins over the committed
    example. `_source` and `_placeholder` record which one was read, so the
    published table can say whether its addresses are real.
    """
    chosen: dict[str, Path] = {}
    for path in sorted(_DIR.glob("authorities*.json")):
        stem = path.name.removesuffix(".json").removesuffix(".example")
        if path.name.endswith(".example.json") and stem in chosen:
            continue  # the override for this table was already found
        chosen[stem] = path

    tables: dict[str, dict] = {}
    for path in chosen.values():
        table = json.loads(path.read_text(encoding="utf-8"))
        code = str(table.get("country") or _LEGACY_COUNTRY).lower()
        table["states"] = {_key(k): v for k, v in table.get("states", {}).items()}
        for region in [*table["states"].values(), table.get("default_state", {})]:
            region["municipal"] = {_key(k): v for k, v in region.get("municipal", {}).items()}
        table["_source"] = path.name
        table["_placeholder"] = path.name.endswith(".example.json")
        tables[code] = table
    return tables


def _load(country: str | None = None) -> dict:
    """One country's table; this node's country when none is named.

    An unknown country is an empty table, never another country's.
    """
    return _tables().get(_country(country), {})


def served_countries() -> frozenset[str]:
    """Lower-case country codes this node holds an authority table for."""
    return frozenset(_tables())


def country_name(country: str | None = None) -> str:
    """The country's name as its table gives it, or its code if it has none."""
    return _load(country).get("country_name") or _country(country).upper()


def access_to_information_law(country: str | None = None) -> str:
    """The country's access-to-information statute, as its table names it.

    Only named, never drafted under, outside India: see `filing.RTI_COUNTRIES`.
    """
    return _load(country).get("access_to_information", "")


@tool
def lookup_authority(
    state: str, city: str = "", pollution_type: str = "", country: str = ""
) -> dict:
    """Find the authority responsible for a pollution category in a given region.

    Use this after reverse geocoding to determine who the complaint should be
    addressed to, under which statute, and who it escalates to if unanswered.

    Args:
        state: State or province name from reverse geocoding.
        city: City name from reverse geocoding. Optional.
        pollution_type: One of open_waste_burning, crop_residue_burning,
            industrial_emission, construction_dust, vehicle_emission.
        country: The two-letter country_code from reverse geocoding, e.g. "in",
            "za" or "br". Pass it whenever the geocoder returned one.

    Returns:
        The matching authority, the statute the complaint is filed under, the
        response window and whether a statute sets it, the escalation
        authority, the region's local language if the table names one, and the
        country the table covers. An error if no table covers the country.
    """
    code = _country(country)
    table = _load(code)
    if not table:
        return {
            "error": (
                f"No authority table covers country '{code.upper()}'. This node holds "
                f"tables for {', '.join(sorted(c.upper() for c in served_countries()))} "
                "only, and will not name an authority it does not have."
            )
        }

    state_key = _key(state)
    city_key = _key(city)

    region = table.get("states", {}).get(state_key)
    if region is None:
        region = table.get("default_state", {})

    rule = table.get("categories", {}).get(pollution_type) or table.get("categories", {}).get(
        "default", {}
    )

    is_generic = region is table.get("default_state", {})
    tier = rule.get("tier", "state")

    if tier == "municipal" and city_key and city_key in region.get("municipal", {}):
        body = region["municipal"][city_key]
        coverage = "exact"
    else:
        # The category wanted a municipal body and this city is not in the table,
        # so the complaint goes one tier up. That is a guess, and a case must be
        # able to say so: without this the substitution is invisible, and a
        # generic state board reads exactly like a specific match.
        wanted_municipal = tier == "municipal"
        tier = "state"
        body = region.get("state_board", {})
        coverage = "generic" if is_generic else ("fallback" if wanted_municipal else "exact")

    if is_generic:
        coverage = "generic"

    coverage_note = {
        "exact": "",
        "fallback": (
            f"No municipal body for '{city or state}' is in the table, so this resolves to "
            "the state board instead of the local authority the statute names."
        ),
        "generic": (
            f"'{state}' is not in the authority table. This is the generic state board "
            "placeholder, not a real match — verify the authority before relying on it."
        ),
    }[coverage]

    window = rule.get("response_window_days", 30)
    statutory = window is not None
    if not statutory:
        window = table.get("follow_up_days", _DEFAULT_FOLLOW_UP_DAYS)

    return {
        "authority_name": body.get("name", "Unknown authority"),
        "authority_tier": tier,
        "office": body.get("office", ""),
        "email": body.get("email", ""),
        "statute": rule.get("statute", ""),
        "section": rule.get("section", ""),
        "response_window_days": window,
        "response_window_statutory": statutory,
        "response_window_note": rule.get("response_window_note", ""),
        "escalation_authority": region.get("escalation", {}).get("name", ""),
        "escalation_email": region.get("escalation", {}).get("email", ""),
        "matched_region": "default" if is_generic else state,
        "coverage": coverage,
        "coverage_note": coverage_note,
        "country": code.upper(),
        "local_language": region.get("local_language", table.get("local_language", "")),
    }


def coverage_is_generic(email: str) -> bool:
    """True when an email is a table's generic placeholder, in any country.

    A deterministic backstop for the agent's self-reported coverage: whatever the
    model says, an address that only exists in a `default_state` means the region
    was not in the table.
    """
    if not email:
        return False
    target = email.strip().lower()
    return any(
        target == generic.lower()
        for table in _tables().values()
        if (generic := table.get("default_state", {}).get("state_board", {}).get("email", ""))
    )


def _published(table: dict) -> dict:
    """One country's table in the published shape."""
    states = table.get("states", {})
    regions = [
        {
            "region": name.title(),
            "state_board": entry.get("state_board", {}),
            "municipal": [
                {"city": city.title(), **body} for city, body in entry.get("municipal", {}).items()
            ],
            "escalation": entry.get("escalation", {}),
            "local_language": entry.get("local_language", table.get("local_language", "")),
        }
        for name, entry in sorted(states.items())
    ]
    return {
        "country": str(table.get("country") or _LEGACY_COUNTRY).upper(),
        "country_name": table.get("country_name", ""),
        "regions": regions,
        "categories": table.get("categories", {}),
        "fallback": table.get("default_state", {}),
        "region_count": len(regions),
        "municipal_count": sum(len(r["municipal"]) for r in regions),
        "source": table.get("_source", ""),
        "addresses_are_placeholders": table.get("_placeholder", True),
    }


def authority_table() -> dict:
    """The jurisdiction tables, shaped for publication.

    Coverage is the honest limit of this system: an authority that is not in the
    table resolves to a placeholder, and a citizen should be able to see that in
    advance rather than infer it from a case. Emails are included because they
    are the point — every one of them is a non-routable `.invalid` address, and
    showing them is how that claim is checked rather than trusted.

    The top level is this node's own country, in the shape it has always had,
    so a reader built for one country keeps working. `countries` holds every
    table the node carries, keyed by country code, each in that same shape.
    """
    own = _load()
    countries = {code.upper(): _published(t) for code, t in sorted(_tables().items())}
    return {
        **(_published(own) if own else {"regions": [], "region_count": 0, "municipal_count": 0}),
        "node_country": _country(None).upper(),
        "served_countries": sorted(countries),
        "countries": countries,
    }
