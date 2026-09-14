"""The forecasting stage.

What is tested here is the part that is ours: which hotspots the model is told
about, how a corridor is summarised from its waypoints, and — the one that
matters most — that the fields a reader relies on to know what this is cannot be
lost or overwritten by the model. Hard constraint 7.

The model's judgement itself is not tested here; `evals/` is where prompt quality
is measured.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fakes import StubAgent
from vayudoot.agents import forecast
from vayudoot.config import settings
from vayudoot.schemas import (
    FORECAST_DISCLAIMER,
    AirQualityForecast,
    Corridor,
    Hotspot,
    PollutionType,
)

NOW = datetime(2026, 9, 14, 6, 0, tzinfo=UTC)

DELHI = (28.6139, 77.2090)
LUDHIANA = (30.9010, 75.8573)  # ~250 km north-west of Delhi
CHENNAI = (13.0827, 80.2707)


def hotspot(
    hotspot_id: str = "VDH-AAAA1111",
    *,
    at: tuple[float, float] = LUDHIANA,
    corroborated: bool = True,
    confidence: float = 0.92,
    severity: str = "severe",
) -> Hotspot:
    return Hotspot(
        hotspot_id=hotspot_id,
        pollution_type=PollutionType.CROP_RESIDUE_BURNING,
        centre_latitude=at[0],
        centre_longitude=at[1],
        radius_km=3.0,
        confidence=confidence,
        severity=severity,  # type: ignore[arg-type]
        corroborated=corroborated,
        signal_count=5,
        first_seen_at=NOW - timedelta(days=1),
        last_seen_at=NOW,
        span_days=1,
    )


def outlook(risk: str = "high", **overrides) -> AirQualityForecast:
    fields = {
        "latitude": 0.0,
        "longitude": 0.0,
        "risk": risk,
        "confidence": 0.7,
        "drivers": ["north-westerly wind from an active burning hotspot"],
        "basis": ["Open-Meteo air quality forecast"],
        "reasoning": "Stub.",
    }
    fields.update(overrides)
    return AirQualityForecast(**fields)


# --------------------------------------------------------------------------- #
# Hard constraint 7: a forecast must always say what it is
# --------------------------------------------------------------------------- #


async def test_the_disclaimer_is_present_by_default():
    """HARD CONSTRAINT 7. Not a formatting assertion — do not relax this.

    People act on air quality predictions; that is the point of making them. The
    disclaimer is a default on the model rather than something a template adds,
    because a label that lives in a template is a label that goes missing the
    first time a second template appears.
    """
    assert outlook().disclaimer == FORECAST_DISCLAIMER


async def test_a_model_cannot_silently_drop_the_disclaimer():
    """Even a stub that never sets it comes back carrying it."""
    agent = StubAgent(outlook())
    result = await forecast.forecast_location(*DELHI, agent=agent)

    assert result.disclaimer == FORECAST_DISCLAIMER
    assert "not an official forecast" in result.disclaimer.lower()


async def test_the_caller_owns_the_coordinates_not_the_model():
    """A model asked for a judgement must not also be trusted with the location.

    A forecast attached to coordinates the model invented would be a forecast
    for somewhere else, presented as this one.
    """
    agent = StubAgent(outlook(latitude=0.0, longitude=0.0))
    result = await forecast.forecast_location(*DELHI, location_name="Delhi", agent=agent)

    assert (result.latitude, result.longitude) == DELHI
    assert result.location_name == "Delhi"


async def test_the_horizon_comes_from_configuration_not_the_model():
    agent = StubAgent(outlook(horizon_hours=999))
    result = await forecast.forecast_location(*DELHI, agent=agent)

    assert result.horizon_hours == settings.vayudoot_forecast_horizon_hours


# --------------------------------------------------------------------------- #
# What the model is told
# --------------------------------------------------------------------------- #


async def test_hotspots_within_reach_are_described_to_the_model():
    agent = StubAgent(outlook())
    await forecast.forecast_location(*DELHI, nearby_hotspots=[hotspot()], agent=agent)

    prompt = agent.prompts[0]
    assert "crop residue burning" in prompt
    assert "severity severe" in prompt
    # Distance and direction, because "a fire somewhere" is not actionable.
    assert "km to the" in prompt


async def test_a_hotspot_beyond_reach_is_not_described():
    """Chennai's fires cannot reach Delhi and must not be offered as if they could."""
    agent = StubAgent(outlook())
    await forecast.forecast_location(
        *DELHI, nearby_hotspots=[hotspot(at=CHENNAI)], agent=agent
    )

    assert "none detected" in agent.prompts[0]


async def test_the_corroboration_state_travels_into_the_prompt():
    """The model must not weigh an uncorroborated hotspot as if it were confirmed."""
    agent = StubAgent(outlook())
    await forecast.forecast_location(
        *DELHI, nearby_hotspots=[hotspot(corroborated=False, confidence=0.6)], agent=agent
    )

    assert "not independently corroborated" in agent.prompts[0]


async def test_no_hotspots_is_stated_rather_than_left_out():
    """Silence reads as missing data; an explicit "none" reads as a quiet picture."""
    agent = StubAgent(outlook())
    await forecast.forecast_location(*DELHI, agent=agent)

    assert "none detected" in agent.prompts[0]


def test_upwind_hotspots_are_ordered_by_distance():
    near = hotspot("VDH-NEAR", at=(28.7, 77.3))
    far = hotspot("VDH-FAR", at=LUDHIANA)

    found = forecast.upwind_hotspots(*DELHI, [far, near])

    assert [h.hotspot_id for h in found] == ["VDH-NEAR", "VDH-FAR"]


def test_reach_is_bounded_by_configuration(monkeypatch):
    monkeypatch.setattr(settings, "vayudoot_forecast_upwind_km", 10.0)
    assert forecast.upwind_hotspots(*DELHI, [hotspot()]) == []


# --------------------------------------------------------------------------- #
# Corridors
# --------------------------------------------------------------------------- #


def corridor(points: int = 3) -> Corridor:
    return Corridor(
        corridor_id="test-corridor",
        name="Test Corridor",
        states=["delhi", "haryana"],
        waypoints=[(28.6 + n * 0.5, 77.2 - n * 0.5) for n in range(points)],
    )


async def test_a_corridor_takes_the_worst_risk_any_waypoint_carries():
    """A corridor is a population strip and a supply line.

    The segment in trouble is what an authority needs to see; averaging it away
    would hide exactly the thing worth acting on.
    """

    class VaryingAgent(StubAgent):
        def __init__(self):
            super().__init__(None)
            self.risks = iter(["low", "severe", "elevated"])

        async def invoke_async(self, prompt, structured_output_model=None, **kwargs):
            self.prompts.append(prompt)
            return type("R", (), {"structured_output": outlook(next(self.risks))})()

    result = await forecast.forecast_corridor(corridor(), agent=VaryingAgent())

    assert result.risk == "severe"
    assert len(result.waypoint_forecasts) == 3


async def test_one_failing_waypoint_does_not_sink_the_corridor():
    """One provider error must not turn a corridor's outlook into silence."""

    class FlakyAgent(StubAgent):
        def __init__(self):
            super().__init__(None)
            self.calls = 0

        async def invoke_async(self, prompt, structured_output_model=None, **kwargs):
            self.prompts.append(prompt)
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("provider rate limit")
            return type("R", (), {"structured_output": outlook("elevated")})()

    result = await forecast.forecast_corridor(corridor(), agent=FlakyAgent())

    assert result.risk == "elevated"
    assert len(result.waypoint_forecasts) == 2
    assert "2 of 3 waypoints reporting" in result.summary


async def test_a_corridor_where_everything_failed_says_so_rather_than_reporting_calm():
    """The dangerous failure mode: total silence rendering as "low risk"."""

    class DeadAgent(StubAgent):
        def __init__(self):
            super().__init__(None)

        async def invoke_async(self, prompt, structured_output_model=None, **kwargs):
            raise RuntimeError("provider down")

    result = await forecast.forecast_corridor(corridor(), agent=DeadAgent())

    assert result.waypoint_forecasts == []
    assert "No outlook could be produced" in result.summary


async def test_a_corridor_forecast_carries_the_disclaimer():
    result = await forecast.forecast_corridor(corridor(1), agent=StubAgent(outlook()))
    assert result.disclaimer == FORECAST_DISCLAIMER


async def test_every_waypoint_is_named_in_its_own_forecast():
    result = await forecast.forecast_corridor(corridor(2), agent=StubAgent(outlook()))
    names = [o.location_name for o in result.waypoint_forecasts]

    assert names == ["Test Corridor waypoint 1", "Test Corridor waypoint 2"]


@pytest.mark.parametrize(
    ("risks", "expected"),
    [
        (["low", "low"], "low"),
        (["low", "elevated"], "elevated"),
        (["elevated", "high"], "high"),
        (["high", "severe"], "severe"),
        (["severe", "low"], "severe"),
    ],
)
def test_risk_ordering_is_worst_first(risks, expected):
    assert max(risks, key=forecast.RISK_ORDER.index) == expected
