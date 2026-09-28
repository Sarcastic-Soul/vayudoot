"""One codebase, three countries: India, South Africa and Brazil.

What changes between countries is data — an authority table, a standard, a set
of corridors, a list of towns — and `VAYUDOOT_NODE_COUNTRY`. These tests pin the
rules that make that true, because each one fails quietly if it regresses:

- An authority is resolved from the geocoded country's own table, and a place in
  a country with no table is refused rather than addressed to another country's
  placeholder.
- A response window is only called statutory when a statute sets it.
- A station reading is measured against the node's own country's standard, and
  a country with none falls back to the WHO guideline, labelled as such.
- A node scans and lists only its own country's corridors.
- RTI is drafted only under India's law.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from fakes import StubAgent, alert_brief, complaint, corroboration, evidence, patch_stages
from vayudoot import alerts, api, corridors, exposure, hotspots, pipeline, scan, standards, store
from vayudoot.agents import alert as alert_agent
from vayudoot.agents.drafting import draft_complaint
from vayudoot.config import settings
from vayudoot.filing import rti_available, rti_supported
from vayudoot.schemas import (
    Case,
    CaseStatus,
    Jurisdiction,
    PollutionType,
    Report,
    Signal,
    SignalSource,
    Stage,
)
from vayudoot.tools import authorities
from vayudoot.tools.authorities import (
    authority_table,
    coverage_is_generic,
    lookup_authority,
    served_countries,
)

DATA = Path(authorities.__file__).resolve().parent.parent / "data"

EMALAHLENI_GEO = {
    "display_name": "Plot 7, Power Station Road, eMalahleni, Nkangala, Mpumalanga, South Africa",
    "city": "eMalahleni",
    "district": "Nkangala District Municipality",
    "state": "Mpumalanga",
    "country": "South Africa",
    "country_code": "za",
}
NOVO_PROGRESSO_GEO = {
    "display_name": "Estrada Vicinal 3, Novo Progresso, Pará, Brasil",
    "city": "Novo Progresso",
    "district": "",
    "state": "Pará",
    "country": "Brasil",
    "country_code": "br",
}
KARACHI_GEO = {
    "display_name": "Karachi, Sindh, Pakistan",
    "city": "Karachi",
    "state": "Sindh",
    "country": "Pakistan",
    "country_code": "pk",
}


@pytest.fixture
async def client():
    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def node_country(monkeypatch):
    """Set this node's country for one test."""

    def use(code: str) -> None:
        monkeypatch.setattr(settings, "vayudoot_node_country", code)

    return use


# --------------------------------------------------------------------------- #
# Authority tables
# --------------------------------------------------------------------------- #


def test_the_countries_served_are_the_countries_with_a_table():
    """Nothing in Python lists countries; the files do."""
    assert served_countries() == frozenset({"in", "za", "br"})
    assert alerts.SERVED_COUNTRIES == served_countries()


def test_a_highveld_industrial_emission_goes_to_the_district_that_licenses_it():
    """Section 36 of the Air Quality Act makes the district the licensing
    authority on the Highveld, so the complaint goes there, not to the province."""
    out = lookup_authority("Mpumalanga", "eMalahleni", "industrial_emission", country="za")
    assert out["authority_name"] == "Nkangala District Municipality"
    assert out["authority_tier"] == "municipal"
    assert out["coverage"] == "exact"
    assert "Air Quality Act 39 of 2004" in out["statute"]
    assert out["country"] == "ZA"
    assert out["local_language"] == "siSwati"
    assert "Forestry, Fisheries and the Environment" in out["escalation_authority"]

    secunda = lookup_authority("Mpumalanga", "Secunda", "industrial_emission", country="ZA")
    assert secunda["authority_name"] == "Gert Sibande District Municipality"


def test_a_south_african_town_not_in_the_table_falls_back_to_the_province_and_says_so():
    out = lookup_authority("Mpumalanga", "Nowhere", "industrial_emission", country="za")
    assert out["coverage"] == "fallback"
    assert "DARDLEA" in out["authority_name"]


def test_each_south_african_province_carries_its_own_language():
    """A per-province mapping held in data, so no model chooses among eleven
    official languages."""
    languages = {
        state: lookup_authority(state, country="za")["local_language"]
        for state in ("Mpumalanga", "Gauteng", "Western Cape", "KwaZulu-Natal")
    }
    assert languages == {
        "Mpumalanga": "siSwati",
        "Gauteng": "isiZulu",
        "Western Cape": "Afrikaans",
        "KwaZulu-Natal": "isiZulu",
    }


def test_a_clearing_fire_in_para_goes_to_the_state_agency_under_the_fire_law():
    out = lookup_authority("Pará", "Novo Progresso", "crop_residue_burning", country="br")
    assert "SEMAS" in out["authority_name"]
    assert "Lei 14.944/2024" in out["statute"]
    assert "Lei 9.605/1998" in out["section"]
    assert out["country"] == "BR"
    assert out["local_language"] == "Brazilian Portuguese"
    assert out["escalation_authority"].startswith("IBAMA")


def test_accents_are_folded_so_either_spelling_matches():
    """Nominatim says "Pará" and "São Paulo"; a person editing JSON types "Para"."""
    with_accent = lookup_authority("Pará", country="br")
    without = lookup_authority("Para", country="br")
    assert with_accent["authority_name"] == without["authority_name"]
    assert without["coverage"] == "exact"
    city = lookup_authority("Sao Paulo", "Sao Paulo", "open_waste_burning", country="br")
    assert "SVMA" in city["authority_name"]
    assert city["coverage"] == "exact"


def test_no_statute_no_statutory_window():
    """South Africa and Brazil set no deadline for answering a complaint. The
    number carried is this system's follow-up interval and must say so; India's
    rules do set one, and that is still reported as statutory."""
    for state, country in (("Mpumalanga", "za"), ("Pará", "br")):
        out = lookup_authority(state, "", "industrial_emission", country=country)
        assert out["response_window_statutory"] is False
        assert out["response_window_days"] == 30
        assert "not a statutory period" in out["response_window_note"]

    india = lookup_authority("Delhi", "Delhi", "open_waste_burning", country="in")
    assert india["response_window_statutory"] is True
    assert india["response_window_days"] == 15


def test_every_null_window_in_a_table_carries_a_note():
    for path in DATA.glob("authorities*.example.json"):
        table = json.loads(path.read_text(encoding="utf-8"))
        for name, rule in table["categories"].items():
            if rule.get("response_window_days") is None:
                assert rule.get("response_window_note"), (path.name, name)


def test_an_unserved_country_is_an_error_not_another_countrys_placeholder():
    out = lookup_authority("Sindh", "Karachi", "industrial_emission", country="pk")
    assert "error" in out
    assert "PK" in out["error"]


def test_an_empty_country_means_this_nodes_country(node_country):
    node_country("ZA")
    assert lookup_authority("Mpumalanga")["country"] == "ZA"
    node_country("IN")
    assert lookup_authority("Delhi")["country"] == "IN"


def test_each_countrys_generic_placeholder_is_recognised_as_generic():
    """The deterministic backstop for a model's self-reported coverage must know
    every country's placeholder, and the placeholders must differ, or a generic
    Brazilian match would be indistinguishable from an Indian one."""
    generics = {
        code: authorities._load(code)["default_state"]["state_board"]["email"]
        for code in served_countries()
    }
    assert len(set(generics.values())) == len(generics)
    for email in generics.values():
        assert coverage_is_generic(email)
    assert lookup_authority("Atlantis", country="br")["coverage"] == "generic"


def test_the_published_table_carries_every_country_and_keeps_its_old_shape(node_country):
    node_country("ZA")
    table = authority_table()
    assert table["node_country"] == "ZA"
    assert table["served_countries"] == ["BR", "IN", "ZA"]
    assert table["country"] == "ZA"
    assert table["region_count"] == 9
    assert set(table["countries"]) == {"BR", "IN", "ZA"}
    assert table["countries"]["IN"]["region_count"] > 30
    assert all(c["addresses_are_placeholders"] for c in table["countries"].values())


def test_a_new_country_is_a_file_and_an_override_beats_its_example(tmp_path, monkeypatch):
    """Adding a country is a JSON file, and `authorities.<cc>.json` replaces
    `authorities.<cc>.example.json` for that country only."""
    for path in DATA.glob("authorities*.example.json"):
        shutil.copy(path, tmp_path / path.name)
    kenya = {
        "country": "KE",
        "country_name": "Kenya",
        "categories": {"default": {"tier": "state", "statute": "EMCA 1999"}},
        "states": {"nairobi": {"state_board": {"name": "NEMA", "email": "nema@example.invalid"}}},
        "default_state": {"state_board": {"name": "County", "email": "ke@example.invalid"}},
    }
    (tmp_path / "authorities.ke.example.json").write_text(json.dumps(kenya), encoding="utf-8")
    override = json.loads((tmp_path / "authorities.za.example.json").read_text(encoding="utf-8"))
    override["states"]["mpumalanga"]["state_board"]["name"] = "Overridden"
    (tmp_path / "authorities.za.json").write_text(json.dumps(override), encoding="utf-8")

    monkeypatch.setattr(authorities, "_DIR", tmp_path)
    authorities._tables.cache_clear()
    try:
        assert served_countries() == frozenset({"in", "za", "br", "ke"})
        assert lookup_authority("Nairobi", country="ke")["authority_name"] == "NEMA"
        assert lookup_authority("Mpumalanga", country="za")["authority_name"] == "Overridden"
        assert authority_table()["countries"]["ZA"]["addresses_are_placeholders"] is False
        assert lookup_authority("Delhi", country="in")["authority_name"]
    finally:
        authorities._tables.cache_clear()


def test_an_override_with_real_addresses_is_never_committed():
    """The override files hold real addresses, so git must ignore every one of
    them while still tracking every example."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = Path(__file__).resolve().parent.parent

    def ignored(name: str) -> bool:
        path = f"src/vayudoot/data/{name}"
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path], cwd=root, check=False
        )
        return result.returncode == 0

    assert ignored("authorities.json")
    assert ignored("authorities.za.json")
    assert ignored("authorities.br.json")
    assert not ignored("authorities.example.json")
    assert not ignored("authorities.za.example.json")
    assert not ignored("authorities.br.example.json")


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #


@pytest.fixture
def geocode(monkeypatch):
    answer = {"value": EMALAHLENI_GEO}
    monkeypatch.setattr(alerts, "reverse_geocode", lambda *a, **k: answer["value"])

    def use(payload: dict) -> None:
        answer["value"] = payload

    return use


@pytest.fixture
def stub(monkeypatch) -> StubAgent:
    agent = StubAgent(alert_brief())
    monkeypatch.setattr(alert_agent, "build_alert_agent", lambda: agent)
    return agent


def _hotspot_at(lat: float, lon: float, kind: PollutionType) -> str:
    now = datetime.now(UTC)
    store.save_signals(
        [
            Signal(
                source=SignalSource.SATELLITE,
                signal_id=f"viirs:{n}:{lat}:{lon}",
                latitude=lat,
                longitude=lon,
                observed_at=now - timedelta(hours=hours),
                pollution_type=kind,
                strength=0.85,
                magnitude=0.6,
                summary="Satellite thermal detection, 40.0 MW radiative power",
            )
            for n, hours in ((1, 6), (2, 3))
        ]
    )
    (spot,) = hotspots.current()
    assert spot.corroborated
    return spot.hotspot_id


async def test_a_highveld_alert_goes_to_the_south_african_authority(client, stub, geocode):
    hotspot_id = _hotspot_at(-25.8713, 29.2332, PollutionType.INDUSTRIAL_EMISSION)
    resp = await client.post(f"/hotspots/{hotspot_id}/alert")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    j = body["jurisdiction"]

    assert j["authority_name"] == "Nkangala District Municipality"
    assert j["email"].endswith(".invalid")
    assert j["country"] == "ZA"
    assert "Air Quality Act 39 of 2004" in j["statute"]
    assert j["response_window_statutory"] is False
    assert j["local_language"] == "siSwati"
    assert body["area"] == "eMalahleni, Nkangala District Municipality, Mpumalanga"
    prompt = stub.prompts[0]
    assert "Country: South Africa" in prompt
    assert "Local language: siSwati" in prompt
    assert "Power Station Road" not in prompt


async def test_an_amazon_fire_alert_goes_to_the_state_agency_in_portuguese(client, stub, geocode):
    geocode(NOVO_PROGRESSO_GEO)
    hotspot_id = _hotspot_at(-7.1478, -55.3811, PollutionType.CROP_RESIDUE_BURNING)
    body = (await client.post(f"/hotspots/{hotspot_id}/alert")).json()
    j = body["jurisdiction"]

    assert "SEMAS" in j["authority_name"]
    assert j["country"] == "BR"
    assert "Lei 14.944/2024" in j["statute"]
    assert j["escalation_authority"].startswith("IBAMA")
    assert "Local language: Brazilian Portuguese" in stub.prompts[0]


async def test_a_country_with_no_table_is_a_422_naming_the_ones_held(client, stub, geocode):
    geocode(KARACHI_GEO)
    hotspot_id = _hotspot_at(24.86, 67.01, PollutionType.UNCLEAR)
    resp = await client.post(f"/hotspots/{hotspot_id}/alert")

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "Pakistan" in detail
    for held in ("India", "South Africa", "Brazil"):
        assert held in detail
    assert stub.prompts == []
    assert store.all_alerts() == []


# --------------------------------------------------------------------------- #
# The complaint pipeline
# --------------------------------------------------------------------------- #


def _report(lat: float = -25.8713, lon: float = 29.2332) -> Report:
    return Report(report_id="r-za", latitude=lat, longitude=lon)


async def test_a_report_in_an_unserved_country_stops_before_any_model_call(monkeypatch):
    """The geocoder runs first, so a report from a country with no table costs
    nothing: no evidence reading, no drafting, and a reason a person can read."""
    patch_stages(monkeypatch, pipeline)
    called: list[str] = []

    async def must_not_run(*a, **k):
        called.append("evidence")
        raise AssertionError("a model stage ran for an unserved country")

    monkeypatch.setattr(pipeline, "analyse_evidence", must_not_run)
    monkeypatch.setattr(pipeline, "reverse_geocode", lambda *a, **k: KARACHI_GEO)

    case = await pipeline.run(_report(24.86, 67.01))

    assert called == []
    assert case.status is CaseStatus.REJECTED
    assert case.stage is Stage.HALTED
    assert case.evidence is None
    assert "Pakistan" in case.error
    assert "No model was called" in case.error
    assert "South Africa" in case.error


async def test_a_south_african_report_settles_its_window_and_language_from_the_table(
    monkeypatch,
):
    """The jurisdiction agent is asked to copy the table's facts; the pipeline
    makes sure of it. The fake agent here answers with an Indian authority's
    fifteen-day statutory window, and the case must still say thirty days, not
    statutory, siSwati, South Africa."""
    patch_stages(monkeypatch, pipeline)
    monkeypatch.setattr(pipeline, "reverse_geocode", lambda *a, **k: EMALAHLENI_GEO)

    case = await pipeline.run(_report())

    assert case.status is CaseStatus.AWAITING_CONFIRMATION
    assert case.jurisdiction.country == "ZA"
    assert case.jurisdiction.local_language == "siSwati"
    assert case.jurisdiction.response_window_statutory is False
    assert case.jurisdiction.response_window_days == 30
    assert "not a statutory period" in case.jurisdiction.response_window_note


async def test_the_drafting_prompt_names_the_country_and_the_tables_language():
    agent = StubAgent(complaint())
    jurisdiction = Jurisdiction(
        authority_name="Nkangala District Municipality",
        authority_tier="municipal",
        email="nkangala-aqo@example.invalid",
        statute="National Environmental Management: Air Quality Act 39 of 2004",
        section="Section 22",
        response_window_days=30,
        response_window_statutory=False,
        country="ZA",
        local_language="siSwati",
    )
    await draft_complaint(
        _report(), evidence(), corroboration(), jurisdiction, "eMalahleni", agent=agent
    )
    prompt = agent.prompts[0]
    assert "Country: South Africa" in prompt
    assert "Local language: siSwati" in prompt
    assert "Air Quality Act 39 of 2004" in prompt


def _filed_case(country: str) -> Case:
    case = Case(
        case_id=f"VD-{country}000001",
        status=CaseStatus.FILED,
        report=_report(),
        jurisdiction=Jurisdiction(
            authority_name="Some authority",
            authority_tier="state",
            email="authority@example.invalid",
            statute="A statute",
            response_window_days=30,
            country=country,
        ),
        complaint=complaint(),
    )
    case.filed_at = datetime.now(UTC) - timedelta(days=60)
    return case


def test_rti_is_india_only():
    """The RTI prompt is written for India's Right to Information Act. A South
    African or Brazilian case long past its window is still not eligible, and a
    case from before tables were per country counts as India's."""
    assert rti_available(_filed_case("IN"))
    assert rti_available(_filed_case(""))
    for country in ("ZA", "BR"):
        case = _filed_case(country)
        assert not rti_supported(case)
        assert not rti_available(case)


async def test_rti_for_a_brazilian_case_is_a_409_naming_the_right_law(client):
    case = _filed_case("BR")
    store.save(case)
    resp = await client.post(f"/cases/{case.case_id}/rti")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "Brazil" in detail
    assert "Lei 12.527/2011" in detail


# --------------------------------------------------------------------------- #
# Standards
# --------------------------------------------------------------------------- #


def test_each_country_is_measured_against_its_own_standard(node_country):
    """The numbers come from each country's notification; see standards.json for
    the source of every one."""
    expected = {
        "IN": {"pm25": 60, "pm10": 100, "so2": 80, "no2": 80},
        "ZA": {"pm25": 40, "pm10": 75, "so2": 125, "no2": 200, "o3": 120, "co": 10000},
        "BR": {"pm25": 50, "pm10": 100, "so2": 50, "no2": 240, "o3": 130, "co": 10310},
    }
    for country, limits in expected.items():
        node_country(country)
        standard = standards.for_country()
        assert standard.national is True
        for parameter, value in limits.items():
            assert standards.limit(parameter) == value, (country, parameter)
    node_country("ZA")
    assert standards.for_country().averaging["no2"] == "1 hour"
    assert "South African" in standards.for_country().phrase


def test_a_country_with_no_standard_falls_back_to_who_and_says_so(node_country):
    node_country("KE")
    standard = standards.for_country()
    assert standard.code == "WHO"
    assert standard.national is False
    assert "WHO 2021 guideline" in standard.phrase
    assert "no national standard" in standard.phrase
    assert standards.limit("pm2.5") == 15


def test_every_standard_is_in_micrograms_and_says_how_it_is_averaged():
    """A CO limit of 10 is milligrams, and a thousand-fold error; see
    `hotspots._exceedance`. Every CO value here must be in the thousands."""
    blob = json.loads((DATA / "standards.json").read_text(encoding="utf-8"))
    for code, table in blob["standards"].items():
        assert table["source"], code
        for parameter, entry in table["pollutants"].items():
            assert entry["averaging"], (code, parameter)
            assert entry["value"] > 0, (code, parameter)
        if "co" in table["pollutants"]:
            assert table["pollutants"]["co"]["value"] >= 1000, code


def test_a_station_reading_is_a_signal_only_above_the_nodes_own_standard(node_country):
    """PM2.5 at 45 µg/m³ is over South Africa's 40 and under India's 60."""
    payload = {
        "latitude": -25.87,
        "longitude": 29.23,
        "station_id": "za-1",
        "measurements": [{"parameter": "pm25", "value": 45.0, "unit": "µg/m³"}],
    }
    node_country("ZA")
    assert len(hotspots.signals_from_stations(payload)) == 1
    node_country("IN")
    assert hotspots.signals_from_stations(payload) == []


def test_the_alert_facts_name_the_standard_in_use(node_country):
    node_country("BR")
    label = alerts.SOURCE_LABELS[SignalSource.GROUND_STATION].format(
        standard=standards.for_country().phrase
    )
    assert "CONAMA" in label
    assert "Indian" not in label


def test_the_air_quality_forecast_tool_uses_the_nodes_standard(node_country, monkeypatch):
    from vayudoot.tools import weather

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"hourly": {"time": ["t0", "t1"], "pm2_5": [45.0, 30.0], "pm10": [60, 80]}}

    monkeypatch.setattr(weather.httpx, "get", lambda *a, **k: Response())
    node_country("ZA")
    out = weather.get_air_quality_forecast(-25.87, 29.23, 2)
    assert out["pm2_5_standard"] == 40
    assert out["pm2_5_hours_above_standard"] == 1
    assert out["pm10_standard"] == 75
    assert "South Africa" in out["standard"]


def test_place_search_is_limited_to_the_nodes_country(node_country, monkeypatch):
    from vayudoot.tools import geocode

    seen: dict = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return []

    def fake_get(url, params=None, **kwargs):
        seen.update(params or {})
        return Response()

    monkeypatch.setattr(geocode.httpx, "get", fake_get)
    node_country("BR")
    geocode.search_places("Santa Maria")
    assert seen["countrycodes"] == "br"


# --------------------------------------------------------------------------- #
# Corridors
# --------------------------------------------------------------------------- #


def test_the_brief_names_corridors_for_both_new_countries():
    ids = {c.corridor_id for c in corridors.all_corridors()}
    assert {"gauteng-emalahleni-middelburg", "gauteng-durban-n3"} <= ids
    assert {"via-dutra", "br-163-arc-of-deforestation", "manaus-porto-velho"} <= ids


def test_a_node_scans_only_its_own_countrys_corridors(node_country):
    """The rule: a corridor belongs to every country it lists. A South African
    node spends no forecast calls on Indian highways; an Indian node still scans
    Lahore to Delhi, because it lists India."""
    node_country("ZA")
    za = {c.corridor_id for c in corridors.for_country()}
    assert za == {"gauteng-emalahleni-middelburg", "gauteng-durban-n3"}
    points = scan._corridor_waypoints()
    assert points and all(lat < 0 and lon > 0 for lat, lon in points)

    node_country("BR")
    points = scan._corridor_waypoints()
    assert points and all(lat < 7 and lon < -30 for lat, lon in points)

    node_country("IN")
    india = {c.corridor_id for c in corridors.for_country()}
    assert "lahore-delhi-transboundary" in india
    assert not india & za
    node_country("PK")
    assert {c.corridor_id for c in corridors.for_country()} == {"lahore-delhi-transboundary"}


async def test_the_corridor_list_is_the_nodes_own(client, node_country):
    node_country("BR")
    ids = {c["corridor_id"] for c in (await client.get("/corridors")).json()}
    assert "via-dutra" in ids
    assert "ncr" not in ids
    # A direct request by id still answers: refusing one that exists would only hide it.
    assert corridors.get_corridor("ncr") is not None


# --------------------------------------------------------------------------- #
# Settlements
# --------------------------------------------------------------------------- #


def test_south_african_and_brazilian_towns_are_counted():
    """Exposure for a Highveld or Amazon hotspot must not read as nobody."""
    near_emalahleni = {s.name for s in exposure.settlements_within(-25.8713, 29.2332, 10)}
    assert "Emalahleni" in near_emalahleni
    near_manaus = {s.name for s in exposure.settlements_within(-3.1019, -60.025, 10)}
    assert "Manaus" in near_manaus
    countries = {s.country for s in exposure._load(exposure._DATA).settlements}
    assert {"ZA", "BR", "IN"} <= countries
