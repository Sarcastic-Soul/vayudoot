"""Jurisdiction lookup.

The authority table is data, not code, and is keyed by administrative region
rather than hardcoded to one country. That is what lets the same agent be
pointed at a different state, or a different country, without a rewrite.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from strands import tool

_DATA = Path(__file__).resolve().parent.parent / "data" / "authorities.json"
_EXAMPLE = Path(__file__).resolve().parent.parent / "data" / "authorities.example.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    path = _DATA if _DATA.exists() else _EXAMPLE
    return json.loads(path.read_text())


@tool
def lookup_authority(state: str, city: str = "", pollution_type: str = "") -> dict:
    """Find the authority responsible for a pollution category in a given region.

    Use this after reverse geocoding to determine who the complaint should be
    addressed to, under which statute, and who it escalates to if unanswered.

    Args:
        state: State or province name from reverse geocoding.
        city: City name from reverse geocoding. Optional.
        pollution_type: One of open_waste_burning, crop_residue_burning,
            industrial_emission, construction_dust, vehicle_emission.

    Returns:
        The matching authority, the statute the complaint is filed under, the
        statutory response window, and the escalation authority.
    """
    table = _load()
    state_key = state.strip().lower()
    city_key = city.strip().lower()

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

    return {
        "authority_name": body.get("name", "Unknown authority"),
        "authority_tier": tier,
        "office": body.get("office", ""),
        "email": body.get("email", ""),
        "statute": rule.get("statute", ""),
        "section": rule.get("section", ""),
        "response_window_days": rule.get("response_window_days", 30),
        "escalation_authority": region.get("escalation", {}).get("name", ""),
        "escalation_email": region.get("escalation", {}).get("email", ""),
        "matched_region": "default" if is_generic else state,
        "coverage": coverage,
        "coverage_note": coverage_note,
    }


def coverage_is_generic(email: str) -> bool:
    """True when an email is the table's generic placeholder.

    A deterministic backstop for the agent's self-reported coverage: whatever the
    model says, an address that only exists in `default_state` means the region
    was not in the table.
    """
    table = _load()
    generic = table.get("default_state", {}).get("state_board", {}).get("email", "")
    return bool(email) and bool(generic) and email.strip().lower() == generic.lower()


def authority_table() -> dict:
    """The jurisdiction table, shaped for publication.

    Coverage is the honest limit of this system: an authority that is not in the
    table resolves to a placeholder, and a citizen should be able to see that in
    advance rather than infer it from a case. Emails are included because they
    are the point — every one of them is a non-routable `.invalid` address, and
    showing them is how that claim is checked rather than trusted.
    """
    table = _load()
    states = table.get("states", {})

    regions = [
        {
            "region": name.title(),
            "state_board": entry.get("state_board", {}),
            "municipal": [
                {"city": city.title(), **body} for city, body in entry.get("municipal", {}).items()
            ],
            "escalation": entry.get("escalation", {}),
        }
        for name, entry in sorted(states.items())
    ]

    return {
        "regions": regions,
        "categories": table.get("categories", {}),
        "fallback": table.get("default_state", {}),
        "region_count": len(regions),
        "municipal_count": sum(len(r["municipal"]) for r in regions),
        "source": "authorities.json" if _DATA.exists() else "authorities.example.json",
        "addresses_are_placeholders": not _DATA.exists(),
    }
