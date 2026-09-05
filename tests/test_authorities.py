from vayudoot.tools.authorities import lookup_authority


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
