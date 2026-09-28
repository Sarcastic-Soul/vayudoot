"""The ambient air quality standard a reading is measured against, per country.

A station reading becomes a signal only when it exceeds a standard, so the
standard decides what reaches the map. It used to be India's NAAQS, held in
`config.py`, which was right for an Indian node and wrong for every other one:
a South African node would have scored Highveld SO2 against a limit South
African law does not use, and called the result "the Indian standard".

The tables are in `data/standards.json`, one per country, each with its
notification cited, because a standard is data an environmental lawyer should be
able to check without reading Python. Four decisions are worth stating.

**A national standard, not the WHO guideline, wherever there is one.** The WHO
guidelines are several times stricter than India's or South Africa's limits. A
hotspot is raised so that an authority acts on it, and it must be measured
against the number that authority is bound by — a map flagging half a country
for exceeding a guideline nobody is obliged to meet tells an inspector nothing.

**The node's country decides, not the station's.** A signal is scored when it
is scanned, by the node that will act on it, and the authority that node alerts
is bound by its own country's numbers. A corridor that crosses a border still
scores the far side against the home standard; the far side's own node, if it
has one, scores it against its own.

**One number per pollutant, chosen by one rule.** Standards set several
averaging periods. The one held is the 24-hour limit where the standard sets
one, else the 8-hour, else the 1-hour. That is the rule India's table already
followed (24-hour for particulates, 8-hour for ozone and CO), stated once so a
new country's table is filled the same way. The averaging period is recorded
beside every number. A single recent reading compared with a daily limit is a
screen for "worth a look", not a finding of non-compliance, and nothing in the
system claims otherwise.

**A country with no table falls back to the WHO 2021 guidelines, labelled as
such.** Not India's: an Indian limit applied in Kenya would be a number nobody
there is bound by, presented as though somebody were. The WHO guideline binds
nobody either, but it says so — every place it appears it is named as a
guideline, and `national` is false so a reader can tell.

**Every number is µg/m³, CO included.** See `hotspots._exceedance` for the
thousand-fold error that rule exists to prevent. Where a standard is written in
mg/m³ or ppm, the table holds the converted value and says what it was converted
from.

`NAAQS_STANDARDS`, the settings field that held India's numbers, still works as
a whole-table override for a deployment that needs different numbers without a
code or data change; it is empty by default, meaning "use the country table".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .config import settings

_DATA = Path(__file__).resolve().parent / "data" / "standards.json"

#: The table used for a country that has none of its own.
FALLBACK = "WHO"


@dataclass(frozen=True)
class AirStandard:
    """One country's ambient standard, reduced to the numbers a screen needs."""

    code: str
    #: The standard's own name, e.g. "National Ambient Air Quality Standards".
    name: str
    #: How it is named inside a sentence: "below {phrase}".
    phrase: str
    #: The notification or resolution that sets the numbers.
    source: str
    #: False for the WHO fallback, which binds nobody.
    national: bool = True
    limits: dict[str, float] = field(default_factory=dict)
    averaging: dict[str, str] = field(default_factory=dict)


def parameter_key(parameter: object) -> str:
    """A pollutant name as the tables key it: `pm2.5`, `PM2_5` and `pm25` agree."""
    return re.sub(r"[\s._-]", "", str(parameter).lower())


@lru_cache(maxsize=1)
def _tables() -> dict[str, AirStandard]:
    blob = json.loads(_DATA.read_text(encoding="utf-8"))
    out: dict[str, AirStandard] = {}
    for code, entry in blob.get("standards", {}).items():
        pollutants = entry.get("pollutants", {})
        out[code.upper()] = AirStandard(
            code=code.upper(),
            name=entry.get("name", code),
            phrase=entry.get("phrase", entry.get("name", code)),
            source=entry.get("source", ""),
            national=bool(entry.get("national", True)),
            limits={parameter_key(p): float(v["value"]) for p, v in pollutants.items()},
            averaging={parameter_key(p): v.get("averaging", "") for p, v in pollutants.items()},
        )
    return out


def for_country(country: str | None = None) -> AirStandard:
    """The standard for a country; this node's when none is named.

    A deployment that set `NAAQS_STANDARDS` gets exactly those numbers, named as
    this node's configured standard rather than as any country's.
    """
    if settings.naaqs_standards:
        return AirStandard(
            code="CONFIGURED",
            name="Standard configured for this node",
            phrase="the standard configured for this node",
            source="NAAQS_STANDARDS setting",
            limits={parameter_key(k): float(v) for k, v in settings.naaqs_standards.items()},
        )
    code = (country or settings.vayudoot_node_country or "").strip().upper()
    tables = _tables()
    return tables.get(code) or tables[FALLBACK]


def limit(parameter: object, country: str | None = None) -> float | None:
    """The limit for one pollutant, in µg/m³, or None if the standard sets none."""
    return for_country(country).limits.get(parameter_key(parameter))
