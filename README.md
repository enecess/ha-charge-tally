# Charge Tally

[简体中文](README.zh-CN.md)

Charge Tally turns Home Assistant energy, power and price sensors into charging records shared across charging points and named identities. It provides live accounting, historical corrections and a local dashboard card. Start/end actions control accounting only; connect your own buttons, RFID readers or charger automations separately.

Version **0.1.0** targets **Home Assistant 2026.9.1**. The tested Linux environment uses Python **3.14.7**; newer Home Assistant versions have not been certified. The integration has no third-party runtime Python requirements, CDN or remote frontend dependencies.

## Installation

For a local installation, extract `dist/charge_tally-0.1.0.zip` into the Home Assistant configuration directory. The resulting file must be `<config>/custom_components/charge_tally/manifest.json`, without an extra archive-name directory. Restart Home Assistant.

For HACS distribution, add `https://github.com/enecess/ha-charge-tally` as a custom repository of category **Integration**, download Charge Tally, then restart Home Assistant. This repository includes HACS metadata; it does not claim inclusion in the default HACS catalog. HACS installs the component directory from the repository; the separately built ZIP is for manual installation.

Open **Settings → Devices & services → Integrations → Add integration → Charge Tally**. Confirm the ledger currency; initial setup continues to the first charging point. Open the Charge Tally integration to add/reconfigure points and shared identities. Only one parent ledger is supported. Configure the currency correctly at creation; the first version does not offer currency conversion or a currency reconfiguration flow.

## Inputs and prices

| Input mode | Measurement | Optional automatic detection |
| --- | --- | --- |
| Energy only | Cumulative Wh/kWh/MWh sensor with `total` or `total_increasing` state class | No; use manual actions |
| Power only | W/kW sensor → owned native HA Integral, left method, hours, maximum subinterval **60 seconds** | Yes |
| Energy and power | Cumulative energy for accounting; power for detection/display | Yes; power is never counted a second time |

Use sensors representing the charging circuit. Interval-only energy values are not cumulative readings. The first valid reading establishes a baseline. Negative power or energy, invalid units, unknown and unavailable readings are not valid zero consumption. Reusing a source across points is rejected.

Choose whether the energy meter may reset. An allowed decrease counts only confirmed post-reset energy and marks missing coverage; a disallowed decrease pauses differencing until a valid baseline recovers. Owned Integral and daily/monthly/yearly Utility Meter helpers are created through native HA flows. Do not repurpose them. If an owned helper is deleted or changed, the point reports a repair issue; explicitly confirm its repair to rebuild it. External input entities are never deleted.

| Price mode | Behavior |
| --- | --- |
| Static | One price per kWh; edits create a new effective version |
| Dynamic sensor | Observed values in ledger-currency/Wh, /kWh or /MWh; explicitly confirm the unit if absent |
| Daily time-of-use | The same full-day schedule every day, including overnight periods; no gaps or overlaps; enter `24:00` for end of day |

Zero and negative prices are valid. Invalid/unavailable dynamic prices end the previous valid rate. Missing prices stay unknown; “known subtotal + pending” is never a complete zero fee. Future supplier attributes and late-arriving price timestamps are not interpreted. There are no exchange rates, weekday, holiday or seasonal schedules.

## Records, identities and estimates

Identities are shared by all points and have stable IDs. Names may change; disabling/removing an identity preserves its history. A newly created identity with a reused name has a new ID. Each point has its own next-identity select; **Unassigned** works without creating an identity first. A manual start can override this record's identity without changing the next selection.

Detection is off initially. When enabled, set start/end power thresholds (end lower than start) and positive confirmation durations; suggested durations are 30/300 seconds. The start candidate locks its identity immediately. Confirmation backdates to the candidate instant. Brief low-power pauses remain one record; a confirmed end backdates and removes provisional amounts after that end. Changing the select during charging affects the next record only. Use **Change record identity** to transfer the whole existing record, keeping energy and prices unchanged.

Manual records end manually. Ending an automatic record while power is high inhibits another automatic start until a low-power observation rearms detection. Unavailable power and downtime interrupt confirmation; neither is treated as zero power. Active records and their locked identities survive reload/restart.

The ledger splits observed energy at record boundaries, local midnight and price changes. Normal short intervals use elapsed-time allocation, marked **estimated**, with decimal conservation across segments. For example, 0.060 kWh over 23:59:50–00:00:20 gives 0.020/0.040 kWh on the two dates. Active and waiting-for-end records are **provisional**, and totals may decrease after backdating or corrections. Display precision does not round the ledger.

Times are stored in UTC; each record retains its HA accounting timezone. Calendar days use that timezone, including daylight-saving transitions; durations use actual elapsed seconds. A timezone change affects new records, not historical dates. An ended record may remain **pending settlement** until the next energy reading covers its endpoint. That reading can settle the previous record and the next one without double counting.

The default maximum automatic allocation interval is **600 seconds**. Longer intervals or explicit unavailable gaps are not silently assigned to an identity/date/price. Reliable cumulative deltas can still advance the native total while record allocation remains incomplete. Later retained/Recorder history may fill gaps; otherwise use a reviewed manual correction. Repeated equal readings refresh observation coverage without adding energy.

**Record statistics differ from native Utility Meter totals.** Meters include standby and energy outside records. Edits, identity transfers and backdated ends change the ledger, not Utility Meter. A later sample can settle the ledger's previous day without rewriting a native meter's closed period. Identity period sensors can increase or decrease and are not `total_increasing`; Recorder's old entity graph is not recalculated ledger history. The card queries corrected ledger buckets.

## History and corrections

In the card, use **Add history** or open an ended record → **Edit record**. Choose point, identity, accounting-local start/end, optional manual energy, cost basis and note, then **Preview changes → Save preview**. Editing retains the original timezone; ambiguous daylight-saving times require a UTC choice and nonexistent times are rejected.

Retained observations are used first, with HA Recorder history as a fallback. Power-only history uses the owned Integral's energy; raw power from before that helper existed is not integrated retrospectively. Manual energy replaces the measurement basis instead of adding to it. A 21 kWh manual record spanning three hours across midnight allocates 7/14 kWh when one/two hours fall on each date.

Cost choices are available-history/prices, manual total, or pending (`null`). Editing can preserve the original cost basis. Manual values are apportioned by time and labeled manual/estimated. Blank manual energy on an edit preserves its previous basis; the UI does not remove an existing manual override by clearing the field. Unknown or partly unknown fees stay visibly incomplete.

Same-point valid records cannot overlap; adjacent records and simultaneous records at different points are allowed. Active boundaries are controlled by start/end, not historical editing. Voiding retains revisions but removes the record from statistics. Previews recheck overlap, configuration and record revision on save. Refresh stale/conflicting previews rather than overwriting changes. Duplicate submissions reuse the same request ID and original payload. Record-list pagination uses point/identity filters; the statistics date range does **not** filter the “Records · all dates” list.

## Native actions and automation YAML

The Actions tool exposes `charge_tally.start`, `charge_tally.end`, and `charge_tally.reassign`. Choose the optional owned identity-select entity, or provide `point_id`; end/reassign also accept `record_id` alone. Combined references must match one point. Existing `target.entity_id` automations remain supported. Multiple entities, device/area targets, external selects and unauthorized records are rejected. Records are scoped to the caller's permissions on the point's owned identity select. Configuration is administrator-only.

Replace entity IDs below with yours. This start example uses the point's selected identity:

```yaml
action: charge_tally.start
data:
  entity_id: select.garage_identity
  request_id: "{{ now().isoformat() }}"
```

To end from an automation, read the current record ID and revision from its **Status** sensor. These small attributes are also on the current-record sensors, and disappear after end. New meter observations can change the revision, so do not hardcode it:

```yaml
actions:
  - variables:
      record_id: "{{ state_attr('sensor.garage_status', 'record_id') }}"
      record_revision: "{{ state_attr('sensor.garage_status', 'record_revision') }}"
      operation_id: "{{ now().isoformat() }}"
  - condition: template
    value_template: "{{ record_id is not none and record_revision is not none }}"
  - action: charge_tally.end
    data:
      record_id: "{{ record_id }}"
      expected_revision: "{{ record_revision }}"
      request_id: "{{ operation_id }}"
```

For a historical identity correction, replace all example values with the chosen record's current details:

```yaml
action: charge_tally.reassign
data:
  record_id: REPLACE_WITH_RECORD_ID
  identity_id: REPLACE_WITH_IDENTITY_ID
  expected_revision: 7  # Replace with the current revision.
  request_id: REPLACE_WITH_UNIQUE_OPERATION_ID
```

The card provides identity names; authenticated WS `charge_tally/snapshot` returns stable point/identity IDs and the current `identity_entity_id`, and `charge_tally/records` with `record_id` returns details/revisions. Service responses are optional and return the record. Repeating one logical operation must reuse its original request ID **and fields**, not generate a new timestamp; persist those values if your automation retries later. A new operation needs a new ID. Start/end use server time; use preview/commit for past dates. On a revision conflict, read the latest record and deliberately start a new operation.

## Dashboard card

In Lovelace **storage resource mode**, the integration registers one local JavaScript module automatically. In **YAML resource mode**, add this to your existing resources configuration:

```yaml
lovelace:
  resources:
    - url: /charge_tally/charge-tally-card.js?v=0.1.0
      type: module
```

Reload the browser, add **Charge Tally** from the card picker, and use its graphical editor to select points/identities and sections. It never modifies a dashboard layout automatically. Equivalent card YAML:

```yaml
type: custom:charge-tally-card
title: Charging records
show_records: true
show_chart: true
# point_id: REPLACE_WITH_POINT_ID
# identity_id: REPLACE_WITH_IDENTITY_ID
```

English/Chinese labels and HA theme variables are included. After an update, refresh cached resources; reconnecting or reloading the integration obtains a fresh authorized snapshot. If no points appear, check the integration state and permissions on the owned identity selects. A missing Integral/Utility Meter is repaired through the point's HA repair issue, not by recreating the ledger.

## Storage, backups and upgrades

The database is `<config>/charge_tally/ledger.sqlite3`. Records, priced segments and revisions are retained indefinitely until explicitly cleaned; there is no automatic record deletion or bulk purge UI. Unreferenced observations/prices default to 90-day retention; data referenced by records, active work or unresolved gaps is protected. Older unrecorded history depends on Recorder retention or manual values. Removing points or unloading the integration does not delete the ledger. Do not edit SQLite or HA's `.storage` manually while running.

Back up the **complete Home Assistant configuration**, including `charge_tally/`, config entries, the entity registry and `.storage/charge_tally.<entry_id>.helpers` ownership mapping. The ledger alone does not recreate point configuration or native helpers. Backup hooks pause writes and create `charge_tally/ledger.backup.sqlite3` using SQLite's consistent backup API, then resume queued work. A stale snapshot is not a replacement for the latest ledger. For manual file copies/restoration, stop Home Assistant first and restore mutually consistent configuration and ledger files.

Before upgrading, keep a restorable full configuration backup and the matching previous integration code. Replace the entire component directory with the new package, retaining `<config>/charge_tally/`, then restart and check helper readiness, current record and totals. Do not copy release files into `.storage`. Version 0.1.0 uses the initial schema 1; there is no previously published schema migration to test. Unknown schema versions fail closed. Do not run older code against a newer ledger; roll back the matching configuration/database backup together with code.

## Verification and release build

On Linux Python 3.14.7 with Node 24.19.0:

```sh
python -m pip install -r requirements-test-ha.txt
python -m pytest tests/ha -q
python -m unittest discover -s tests/core -v
node --test tests/frontend/*.test.mjs
python scripts/package.py
```

CI pins HA 2026.9.1, the custom-component pytest plugin 0.13.364 and pytest 9.0.3. The packager validates manifest/project/frontend versions, local module paths and a strict file allowlist; it fixes ZIP timestamps/permissions and prints SHA-256. Its output contains only `custom_components/charge_tally/` code, local JS and necessary assets, with no tests, ledgers, secrets or local design files. Repeat builds in the same Python/zlib environment are byte-identical. Build output is ignored by Git.

Automated acceptance uses real HA flows, Integral/Utility Meter, event delivery, authenticated WS, SQLite, history preview/commit, whole-record identity transfer and unload/reload. Separate tests cover permissions, negative/unknown prices, DST, gaps, overlap, revision conflicts, subscriptions and helper ownership. Abrupt **application-process exit before commit**, subsequent commits, backup hooks and SQLite snapshot restoration are verified. This is not an OS power-loss test or a complete Home Assistant BackupManager archive restore certification.

Manual browser checks use a disposable official HA 2026.9.1 instance and synthetic sensors: configuration, automatic/manual records, identity locking/transfer, native meter differences and local card creation/history preview. No real charger, physical meter or existing user HA deployment was used. Other HA versions and provider-specific sensor behavior remain outside this baseline.

License: [MIT](LICENSE).
