# Analysis across nations, in BigQuery

One node answers "what is burning near me". The questions a network is for are
different: how many hotspots each country had last week, which node's
detections are backed by instruments, where alerts are waiting, which corridors
run through smoke on both sides of a border. Those need every node's data in one
place with SQL over it.

`scripts/export_bigquery.py` writes what a node knows as files BigQuery loads
directly, and loads them into the **BigQuery sandbox** when it is set up. The
sandbox is free, needs no billing account and no card, so it is inside hard
constraint 3 and is one of the Google services constraint 6 lists as allowed.

## The short version

```bash
# Always works, no Google account needed: writes the files, prints bq commands.
.venv/bin/python scripts/export_bigquery.py

# Once the one-time setup below is done: also loads them.
uv pip install -e ".[bigquery]"
.venv/bin/python scripts/export_bigquery.py --project YOUR_PROJECT_ID
```

Run it with the same environment as the server (`DATABASE_URL`,
`VAYUDOOT_CASE_DIR`, `VAYUDOOT_ALERT_DIR`, `VAYUDOOT_NODE_*`,
`VAYUDOOT_NEIGHBOUR_FEEDS`). It only reads the store. Each node in a network runs
it for itself; loading several nodes' exports into one dataset is what makes the
queries below cross-national.

## One-time setup

You need a Google account. You do **not** need a billing account or a card.

1. Go to <https://console.cloud.google.com/> and create a project. If you are
   offered billing, skip it. A project with no billing account is exactly what
   puts BigQuery into sandbox mode.
2. Enable the BigQuery API for the project:
   <https://console.cloud.google.com/apis/library/bigquery.googleapis.com>
3. Give this machine credentials:
   ```bash
   gcloud auth application-default login
   gcloud auth application-default set-quota-project YOUR_PROJECT_ID
   ```
4. Install the client library, which is an optional extra and never a core
   dependency: `uv pip install -e ".[bigquery]"`.
5. Run the export with `--project YOUR_PROJECT_ID`, or set
   `GOOGLE_CLOUD_PROJECT` (or `VAYUDOOT_BIGQUERY_PROJECT`) once.

The script creates the `vayudoot` dataset (change with `--dataset`) in the `US`
location (change with `--location`, for example `asia-south1`; a dataset's
location cannot be changed later), loads every table, and creates the views.

If step 3 or 4 is skipped, nothing fails: the script prints the setup steps and
the exact `bq load` commands for the export it just wrote.

## What the sandbox allows, and how the export fits it

Checked against Google's sandbox page
(<https://docs.cloud.google.com/bigquery/docs/sandbox>) on 2026-09-29:

| Limit | What it means here |
| --- | --- |
| 10 GiB of storage, for the life of the sandbox | One node's export is kilobytes to a few megabytes. Not a concern for years. |
| 1 TiB of queries a month | BigQuery bills at least 10 MB for each table a query touches, so the practical ceiling is about 100,000 queries a month. Not a concern either. |
| Every table, view and partition is deleted 60 days after it is created | The real limit. Keep the export directories: loading them again is how history comes back. |
| No streaming inserts, no DML (`INSERT`, `UPDATE`, `MERGE`) | Every load is a load job that appends one export. Nothing is updated in place. |

**Snapshots, not updates.** Since rows cannot be updated, every row carries the
`export_id` and `exported_at` of the run that wrote it, and each table keeps
every export. The views pick the latest copy. **Query the views, not the
tables.** Loading the same export twice would count it twice, so the script
records which datasets an export went to (`uploaded.json` in the export
directory) and refuses to load it into the same one again.

**Partitioning and clustering.** At this volume partitioning does not save
bytes — the 10 MB minimum is higher than the tables. It is there for the 60 days:
a table partitioned by day loses its oldest days one at a time instead of all
its history at once.

| Table | Partitioned by (day) | Clustered by |
| --- | --- | --- |
| `exports` | none, one row per run | `country`, `node_id` |
| `signals` | `observed_at` | `country`, `node_id`, `source` |
| `hotspots` | `exported_at` | `country`, `node_id`, `corroborated` |
| `neighbour_hotspots` | `exported_at` | `source_country`, `source_node_id`, `reader_node_id` |
| `alerts` | `exported_at` | `country`, `node_id`, `status` |
| `corridors` | none, a handful of rows | `corridor_id` |

Snapshot tables are partitioned on `exported_at` because the views read the
latest export, which is one day. Signals are partitioned on `observed_at` because
every question about signals filters on when they were observed. One result of
that: in the sandbox, a signal observed more than 60 days ago lands in a
partition that has already expired and is dropped. The NDJSON file keeps it.
Clustering is by country and node because that is what every cross-national
query groups or filters on.

## What is exported, and what is not

Every table is an allowlist, built field by field in `src/vayudoot/export.py`, so
a field added to the app later is not exported until someone adds it on purpose.

- **Hotspots are areas, never points** (hard constraint 7). `area` is a WKT
  polygon at the hotspot's radius, loaded as `GEOGRAPHY`. Centre and radius are
  included because `/feed` already publishes them.
- **No cases.** A case holds the reporter's contact and their own note. Neither
  is exported, and nothing else from a case is either.
- **Citizen signals are coarsened.** Coordinates are rounded to two decimals
  (about 1 km, the hotspot minimum radius), the id (a case id) is replaced by a
  digest, and the summary is dropped. Satellite and station signals are public
  observations and are exported as observed.
- **Alerts are status, not letters.** Who an alert is for, under which statute,
  and whether it was sent. Not the authority's email, not the facts block, not
  the model's summary — the same rule the public register follows for emails.
- **A neighbour's hotspots keep their origin.** They go to
  `neighbour_hotspots` with the node that detected them, never into
  `hotspots`. Copying them in would count a detection twice and lose whose
  evidence it rests on — the federation rule, applied to analysis.

`country` on our own rows is the **detecting node's** country (from
`VAYUDOOT_NODE_COUNTRY`), not a lookup of where the hotspot's centre is. A node
near a border can see a fire just across it; the row says which node saw it.

## The export directory

```
data/exports/bigquery/20260929T101500Z/
  manifest.json            what was written: node, export id, rows per table
  exports.ndjson           + exports.schema.json
  signals.ndjson           + signals.schema.json
  hotspots.ndjson          + hotspots.schema.json
  neighbour_hotspots.ndjson + neighbour_hotspots.schema.json
  alerts.ndjson            + alerts.schema.json
  corridors.ndjson         + corridors.schema.json
  views/*.sql              the view definitions, qualified with your project
  uploaded.json            only after a load: which datasets it went into
```

Schema files are BigQuery's JSON schema format, usable as-is with `bq load` and
`bq mk --table`.

## Tables

Every table starts with `export_id STRING` and `exported_at TIMESTAMP`, both
required.

**`exports`** — one row per export run. `node_id`, `node_name`, `region`,
`country`, `vayudoot_version`, `signal_count`, `hotspot_count`, `alert_count`,
`neighbour_hotspot_count`, `neighbour_errors` (repeated string).

**`signals`** — `node_id`, `country`, `signal_id`, `source` (`satellite`,
`ground_station`, `citizen_report`, `citizen_sensor`), `independent` (bool),
`latitude`, `longitude`, `coordinate_decimals` (set when coarsened),
`observed_at`, `pollution_type`, `strength`, `magnitude`, `summary`.

**`hotspots`** — `node_id`, `country`, `hotspot_id`, `pollution_type`,
`centre_latitude`, `centre_longitude`, `radius_km`, `area` (GEOGRAPHY polygon),
`confidence`, `severity`, `corroborated`, `signal_count`, `first_seen_at`,
`last_seen_at`, `span_days`, `satellite_signals`, `ground_station_signals`,
`citizen_report_signals`, `citizen_sensor_signals`, `exposure_population`,
`exposure_radius_km`, `exposure_towns` (repeated string).

**`neighbour_hotspots`** — `reader_node_id`, `reader_country`, `feed_url`,
`feed_version`, `source_node_id`, `source_node_name`, `source_region`,
`source_country`, `hotspot_id`, then the same area columns as `hotspots` from
`pollution_type` to `last_seen_at`. No exposure: the feed does not carry it.

**`alerts`** — `node_id`, `country`, `alert_id`, `hotspot_id`, `status`
(`draft`, `awaiting_confirmation`, `sent`), `created_at`, `updated_at`,
`sent_at`, `area_name` (city, district, state; never a street), `area`
(GEOGRAPHY polygon), `pollution_type`, `severity`, `confidence`, `corroborated`,
`exposure_population`, `authority_name`, `authority_tier`,
`jurisdiction_coverage`, `statute`, `response_window_days`, `cited_imagery`.

**`corridors`** — `node_id`, `corridor_id`, `name`, `states` and `countries`
(repeated strings), `waypoint_count`, `path` (GEOGRAPHY line through the
waypoints).

**`forecast_ledger`** — `node_id`, `country`, `forecast_id`, `made_at`,
`location_name`, `corridor_id`, `latitude` and `longitude` (two decimals),
`horizon_hours`, `window_start`, `window_end`, `risk`, `confidence`,
`forecaster_version`, `prompt_sha256`, `model_id`, then the outcome once the
window has closed: `outcome_status` (`scored`, `unscorable`, or null while
pending), `pollutant`, `observed_value`, `observed_band`, `band_error`, and the
two no-model baselines `persistence_band` and `cams_band`. Partitioned on
`made_at`.

### Views

| View | What it holds |
| --- | --- |
| `latest_exports` | each node's most recent export run |
| `hotspots_current` | each node's map as of its latest export (a node whose last export was empty shows nothing) |
| `hotspots_seen` | every hotspot ever exported, once, at its latest snapshot |
| `neighbour_hotspots_current` | what each node's neighbours reported at its latest export |
| `neighbour_hotspots_seen` | every neighbour hotspot, once |
| `signals_latest` | every signal, once |
| `alerts_current` | every alert, once, at its latest status |
| `corridors_current` | every corridor, once |
| `forecast_ledger_latest` | every forecast, once, at its latest state (pending ones turn scored in a later export) |

### Adding a table

`export.register(Table(...))` adds a table to every export: the writer, the
schema check, the manifest, the load and the `bq` commands all read the
registry. The forecast ledger went straight into `TABLES`; a `Table` whose
`rows` reads the snapshot is all a new one takes.

## Ready queries

These assume the dataset is `vayudoot` in your default project. In the console,
paste one and run it. From a shell:
`bq query --use_legacy_sql=false --project_id=YOUR_PROJECT_ID '<query>'`.

Several queries count a neighbour's hotspot only when the node that detected it
has not loaded its own export. A network where every node exports sees each
hotspot once, from its own node; a node that only publishes a feed is still
counted, through whoever reads it.

### 1. Hotspots per country per week

```sql
WITH network AS (
  SELECT country, node_id, hotspot_id, first_seen_at, corroborated
  FROM vayudoot.hotspots_seen
  UNION ALL
  SELECT source_country, source_node_id, hotspot_id, first_seen_at, corroborated
  FROM vayudoot.neighbour_hotspots_seen
  WHERE source_node_id NOT IN (SELECT node_id FROM vayudoot.latest_exports)
)
SELECT
  country,
  DATE_TRUNC(DATE(first_seen_at), WEEK(MONDAY)) AS week,
  COUNT(*) AS hotspots,
  COUNTIF(corroborated) AS corroborated
FROM network
GROUP BY country, week
ORDER BY week DESC, hotspots DESC;
```

### 2. Share of hotspots corroborated, per node

How much of each node's map rests on instruments rather than on citizen
submissions alone. A node with a low share is not wrong, but its map is more
open to coordinated false reporting — the risk hard constraint 7 caps.

```sql
SELECT
  node_id,
  country,
  COUNT(*) AS hotspots,
  COUNTIF(corroborated) AS corroborated,
  ROUND(SAFE_DIVIDE(COUNTIF(corroborated), COUNT(*)), 3) AS corroborated_share,
  ROUND(AVG(IF(corroborated, confidence, NULL)), 2) AS mean_confidence_corroborated,
  ROUND(AVG(IF(corroborated, NULL, confidence)), 2) AS mean_confidence_citizen_only
FROM vayudoot.hotspots_current
GROUP BY node_id, country
ORDER BY corroborated_share DESC;
```

### 3. Alerts sent and awaiting confirmation, per authority

`awaiting_confirmation` is waiting on a person at the node, not on the
authority: nothing is sent until someone confirms (hard constraint 2). An alert
has no acknowledgement step, so `sent` is the end of what can be measured.

```sql
SELECT
  country,
  authority_name,
  authority_tier,
  COUNTIF(status = 'sent') AS sent,
  COUNTIF(status = 'awaiting_confirmation') AS awaiting_confirmation,
  COUNTIF(status = 'draft') AS draft,
  ROUND(AVG(IF(status = 'sent', TIMESTAMP_DIFF(sent_at, created_at, MINUTE) / 60, NULL)), 1)
    AS mean_hours_to_confirm,
  MIN(IF(status = 'awaiting_confirmation', created_at, NULL)) AS oldest_waiting_since
FROM vayudoot.alerts_current
GROUP BY country, authority_name, authority_tier
ORDER BY awaiting_confirmation DESC, sent DESC;
```

### 4. Hotspots within 25 km of a corridor, on either side of a border

Every current hotspot — our own and neighbours' — whose area touches a 25 km
buffer around a corridor's line. On `lahore-delhi-transboundary` this is the
query that shows smoke on both sides of the border along one route.

```sql
WITH params AS (
  SELECT 25000 AS buffer_m
),
neighbours AS (
  SELECT * FROM vayudoot.neighbour_hotspots_current
  WHERE source_node_id NOT IN (SELECT node_id FROM vayudoot.latest_exports)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY source_node_id, hotspot_id ORDER BY exported_at DESC) = 1
),
network AS (
  SELECT node_id AS detected_by, country, hotspot_id, severity, confidence, corroborated, area
  FROM vayudoot.hotspots_current
  UNION ALL
  SELECT source_node_id, source_country, hotspot_id, severity, confidence, corroborated, area
  FROM neighbours
)
SELECT
  c.corridor_id,
  c.name AS corridor,
  h.country,
  h.detected_by,
  h.hotspot_id,
  h.severity,
  h.confidence,
  h.corroborated,
  ROUND(ST_DISTANCE(h.area, c.path) / 1000, 1) AS km_from_route
FROM vayudoot.corridors_current AS c
CROSS JOIN params
JOIN network AS h
  ON ST_INTERSECTS(h.area, ST_BUFFER(c.path, params.buffer_m))
ORDER BY c.corridor_id, km_from_route;
```

### 5. People within reach of a hotspot, per country

`exposure_population` is the population of towns over 15,000 within reach of a
hotspot, from the node's gazetteer. Two hotspots near the same town both count
it, so the sum is an upper bound; `towns_in_reach` counts each town once.
Neighbours' hotspots are not included because the feed does not carry exposure.

```sql
WITH per_country AS (
  SELECT
    country,
    COUNT(*) AS hotspots,
    COUNTIF(exposure_population IS NOT NULL) AS hotspots_near_towns,
    SUM(exposure_population) AS people_upper_bound,
    SUM(IF(corroborated, exposure_population, 0)) AS people_near_corroborated
  FROM vayudoot.hotspots_current
  GROUP BY country
),
towns AS (
  SELECT country, COUNT(DISTINCT town) AS towns_in_reach
  FROM vayudoot.hotspots_current, UNNEST(exposure_towns) AS town
  GROUP BY country
)
SELECT
  p.country,
  p.hotspots,
  p.hotspots_near_towns,
  p.people_upper_bound,
  p.people_near_corroborated,
  IFNULL(t.towns_in_reach, 0) AS towns_in_reach
FROM per_country AS p
LEFT JOIN towns AS t ON p.country = t.country
ORDER BY p.people_upper_bound DESC;
```

### 6. Which nodes read which, across borders

What each node is being told by neighbours in other countries — the
cross-border half of the network, from the reader's side.

```sql
SELECT
  reader_country,
  source_country,
  reader_node_id,
  source_node_id,
  COUNT(*) AS hotspots_offered,
  COUNTIF(corroborated) AS corroborated,
  COUNTIF(severity IN ('high', 'severe')) AS high_or_severe
FROM vayudoot.neighbour_hotspots_current
WHERE reader_country != source_country
GROUP BY reader_country, source_country, reader_node_id, source_node_id
ORDER BY hotspots_offered DESC;
```

### 7. Forecast skill per country, against the two baselines

Whether the model beats simply carrying yesterday forward, or reading the raw
CAMS number, on the same forecasts — per country and per forecaster version, so
two nodes are compared only when they ran the same prompt. A handful of scored
forecasts says little; the count is there so nobody reads a rate off three.

```sql
SELECT
  country,
  forecaster_version,
  prompt_sha256,
  COUNT(*) AS scored,
  AVG(IF(band_error = 0, 1, 0)) AS model_exact,
  AVG(IF(ABS(band_error) <= 1, 1, 0)) AS model_within_one,
  AVG(IF(persistence_band = observed_band, 1, 0)) AS persistence_exact,
  AVG(IF(cams_band = observed_band, 1, 0)) AS cams_exact
FROM vayudoot.forecast_ledger_latest
WHERE outcome_status = 'scored'
GROUP BY country, forecaster_version, prompt_sha256
ORDER BY country, scored DESC;
```

### How these were checked

There is no BigQuery project behind this repository, so none of these has been
run against BigQuery itself. `tests/test_export.py` parses every query on this
page, and every view, with `sqlglot`'s BigQuery dialect and resolves every
table and column against the exported schema files, so a misspelt column or a
query that no longer matches the schema fails the suite. That test needs
`sqlglot` (`uv pip install sqlglot`) and is skipped without it. It proves the
queries are well-formed and consistent with the schema; it cannot prove
BigQuery's own type checks, so the first real run is still worth watching.
