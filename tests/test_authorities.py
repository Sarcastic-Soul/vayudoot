from vayudoot.tools.authorities import authority_table, coverage_is_generic, lookup_authority


def test_known_state_and_category():
    out = lookup_authority(state="Delhi", city="Delhi", pollution_type="open_waste_burning")
    assert out["authority_tier"] == "municipal"
    assert "Delhi" in out["authority_name"]
    assert "Solid Waste Management Rules" in out["statute"]


def test_industrial_emission_routes_to_the_state_board():
    out = lookup_authority(
        state="Karnataka", city="Bengaluru", pollution_type="industrial_emission"
    )
    assert out["authority_tier"] == "state"
    assert "Pollution Control Board" in out["authority_name"]


def test_unknown_state_falls_back_without_raising():
    out = lookup_authority(state="Nowhere", city="Nowhere", pollution_type="construction_dust")
    assert out["authority_name"]
    assert out["response_window_days"] > 0


def test_every_committed_email_is_non_routable():
    """No real regulator address may be committed to this repository."""
    import json
    from pathlib import Path

    path = Path("src/vayudoot/data/authorities.example.json")
    blob = json.loads(path.read_text())

    def emails(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "email":
                    yield value
                else:
                    yield from emails(value)
        elif isinstance(node, list):
            for item in node:
                yield from emails(item)

    found = list(emails(blob))
    assert found
    assert all(e.endswith(".invalid") for e in found), found


def test_an_exact_municipal_match_is_reported_as_exact():
    result = lookup_authority("Delhi", "New Delhi", "open_waste_burning")
    assert result["coverage"] == "exact"
    assert result["coverage_note"] == ""


def test_a_missing_city_falls_back_and_says_so():
    """The substitution used to be invisible: a state board read like a match."""
    result = lookup_authority("Chhattisgarh", "Ambikapur", "open_waste_burning")
    assert result["coverage"] == "fallback"
    assert "Ambikapur" in result["coverage_note"]
    assert result["authority_tier"] == "state"


def test_a_state_level_category_is_exact_without_a_city():
    result = lookup_authority("Chhattisgarh", "Raipur", "industrial_emission")
    assert result["coverage"] == "exact"


def test_an_unknown_region_is_reported_as_generic():
    result = lookup_authority("Narnia", "Cair Paravel", "open_waste_burning")
    assert result["coverage"] == "generic"
    assert "not in the authority table" in result["coverage_note"]
    assert coverage_is_generic(result["email"])


def test_a_named_authority_is_not_mistaken_for_the_generic_one():
    result = lookup_authority("Delhi", "New Delhi", "open_waste_burning")
    assert not coverage_is_generic(result["email"])


def test_the_published_table_never_carries_a_routable_address():
    table = authority_table()
    emails = [r["state_board"].get("email", "") for r in table["regions"]]
    emails += [m.get("email", "") for r in table["regions"] for m in r["municipal"]]
    emails.append(table["fallback"]["state_board"]["email"])
    assert emails and all(e.endswith(".invalid") for e in emails)


def test_a_category_never_cites_a_statute_its_authority_cannot_enforce():
    """Vehicle emission used to be routed to the state pollution control board
    while citing Motor Vehicles Act Section 190(2), which that board has no power
    under — 190(2) is enforced by the transport authority and the police. The
    Air Act's Section 20 is the provision that names the State Board's role in
    vehicular emissions, so the authority and the statute now agree."""
    rule = lookup_authority("Delhi", "New Delhi", "vehicle_emission")
    assert rule["authority_tier"] == "state"
    assert "Air (Prevention and Control of Pollution) Act" in rule["statute"]
    assert "Motor Vehicles Act" not in rule["statute"]
