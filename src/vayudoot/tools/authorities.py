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

    tier = rule.get("tier", "state")
    if tier == "municipal" and city_key and city_key in region.get("municipal", {}):
        body = region["municipal"][city_key]
    else:
        tier = "state"
        body = region.get("state_board", {})

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
        "matched_region": state if region is not table.get("default_state", {}) else "default",
    }
