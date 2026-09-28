"""Regenerate `src/vayudoot/data/settlements.csv` from the GeoNames gazetteer.

    .venv/bin/python scripts/build_settlements.py
    .venv/bin/python scripts/build_settlements.py --source path/to/cities15000.zip
    .venv/bin/python scripts/build_settlements.py --countries BR,AR,PY,BO

The exposure figure on every hotspot is a sum over this table, so where the table
came from has to be something anybody can check and rebuild, not a file that
appeared in the repository one day. This script is that provenance: it downloads
GeoNames `cities15000` (every populated place over 15,000 people, published under
CC BY 4.0), keeps the countries listed below, and writes the five
columns `exposure.py` reads.

Which countries, and why:

- IN, because it is where this system runs.
- PK, BD and NP, because their smoke crosses into India. Pakistan's Punjab burns
  the same paddy stubble as India's and on the same calendar; Bangladesh's brick
  kilns and Nepal's Terai fires sit upwind of the eastern Gangetic plain. A node
  standing up across any of those borders needs its own towns in the table.
- BT, because it is four rows and leaving a neighbour out would be a strange
  thing to explain.
- ZA and BR, because the repository carries authority tables for South Africa
  and Brazil, so a node started with `VAYUDOOT_NODE_COUNTRY=ZA` or `BR` must be
  able to count the people near its own hotspots without a rebuild. Brazil is
  most of the added rows; together they keep the file well under a megabyte.

A node whose air shed crosses more borders rebuilds the table with `--countries`
— Brazil with the neighbours whose Amazon and Chaco fire smoke it shares, South
Africa with Mozambique and Zimbabwe — and changes nothing else. The same script,
the same five columns, the same attribution.

Which places, and why some are dropped:

GeoNames lists a *section* of a city (`PPLX`, e.g. Karol Bagh inside Delhi) as its
own place with its own population. Keeping those would count the same people
twice — once in Delhi, once in Karol Bagh — so they are dropped. Historical,
abandoned and destroyed places (`PPLH`, `PPLQ`, `PPLW`) are dropped because nobody
is breathing there. Everything else populated is kept.

Nothing else is filtered and nothing is edited by hand. If a number in the table
looks wrong, it is GeoNames' number, and the fix belongs upstream.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

SOURCE_URL = "https://download.geonames.org/export/dump/cities15000.zip"
OUT = Path(__file__).resolve().parents[1] / "src" / "vayudoot" / "data" / "settlements.csv"

COUNTRIES = ("IN", "PK", "BD", "NP", "BT", "ZA", "BR")

#: Feature codes that describe a place nobody should be counted in, or a place
#: already counted as part of a larger one. See the module docstring.
DROPPED_FEATURE_CODES = frozenset({"PPLX", "PPLH", "PPLQ", "PPLW"})

# Column positions in the GeoNames dump format, documented in the readme at
# https://download.geonames.org/export/dump/readme.txt.
ASCIINAME, LATITUDE, LONGITUDE, FEATURE_CODE, COUNTRY, POPULATION = 2, 4, 5, 7, 8, 14


def read_source(source: str | None) -> str:
    """The text of `cities15000.txt`, from a local zip or the GeoNames server."""
    if source:
        blob = Path(source).read_bytes()
    else:
        with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:
            blob = response.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return archive.read("cities15000.txt").decode("utf-8")


def rows(
    text: str, countries: tuple[str, ...] = COUNTRIES
) -> list[tuple[str, str, float, float, int]]:
    out = []
    for line in text.splitlines():
        field = line.split("\t")
        if len(field) <= POPULATION:
            continue
        if field[COUNTRY] not in countries or field[FEATURE_CODE] in DROPPED_FEATURE_CODES:
            continue
        population = int(field[POPULATION] or 0)
        if population <= 0:
            continue
        out.append(
            (
                field[ASCIINAME],
                field[COUNTRY],
                round(float(field[LATITUDE]), 4),
                round(float(field[LONGITUDE]), 4),
                population,
            )
        )
    # Largest first: a reader skimming the file sees the places that matter, and
    # a diff after a GeoNames refresh shows the big changes at the top.
    return sorted(out, key=lambda r: (-r[4], r[1], r[0]))


def write(
    table: list[tuple[str, str, float, float, int]], countries: tuple[str, ...] = COUNTRIES
) -> None:
    today = datetime.now(UTC).date().isoformat()
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            "# Populated places over 15,000 people in the countries this table covers\n"
            "# (" + ", ".join(countries) + "); see scripts/build_settlements.py for why.\n"
            "# Source: GeoNames cities15000, " + SOURCE_URL + "\n"
            "# Licence: Creative Commons Attribution 4.0 (CC BY 4.0), (c) GeoNames,\n"
            "# https://www.geonames.org/ . Filtered, not edited: city sections (PPLX) and\n"
            "# historical, abandoned or destroyed places are dropped.\n"
            "# Built " + today + " by scripts/build_settlements.py; rebuild with that script\n"
            "# rather than editing by hand.\n"
        )
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["name", "country", "latitude", "longitude", "population"])
        writer.writerows(table)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", help="A local copy of cities15000.zip, instead of downloading")
    parser.add_argument(
        "--countries",
        default=",".join(COUNTRIES),
        help="ISO 3166-1 alpha-2 codes to keep, comma-separated (default: %(default)s)",
    )
    args = parser.parse_args()
    countries = tuple(c.strip().upper() for c in args.countries.split(",") if c.strip())

    table = rows(read_source(args.source), countries)
    if not table:
        print("No rows matched. Refusing to write an empty table.", file=sys.stderr)
        return 1
    write(table, countries)
    per_country = {c: sum(1 for r in table if r[1] == c) for c in countries}
    print(f"Wrote {len(table)} places to {OUT} ({OUT.stat().st_size // 1024} KB): {per_country}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
