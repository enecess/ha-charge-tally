# Charge Tally

**English** · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Polski](README.pl.md) · [Italiano](README.it.md)

Track charging energy and cost by charging point and identity in Home Assistant, and review how each charge was calculated. Charge Tally uses your existing energy or power sensors. It keeps accounting records; it does not switch the charger on or off.

- Manage multiple charging points in one ledger, with shared identities for vehicles, drivers or household members.
- Measure cumulative energy, calculate energy from power, or combine energy measurement with power-based detection.
- Use static, dynamic or daily time-of-use prices, including zero and negative prices.
- Detect charging automatically, or start and end records from the card or Home Assistant automations.
- View live charging, statistics for today, this month, this year, all time or a custom range, and daily charts.
- Add history, edit ended records, change identities, void incorrect records, and inspect accounting segments and revision history.
- Manage archived charging points and identities, and permanently clear unneeded ledger data.

Use **Settings → Devices & services → Charge Tally** for configuration and the **Charge Tally** dashboard card for records. The card contains several sections on one page; details and editing open in dialogs.

> Screenshot placeholder 01: The complete card, including charging points, record statistics and the record list.

## Contents

- [Before you install](#before-you-install)
- [Install the integration](#install-the-integration)
- [Initial setup](#initial-setup)
- [Identities and later configuration](#identities-and-later-configuration)
- [Add and configure the dashboard card](#add-and-configure-the-dashboard-card)
- [The card at a glance](#the-card-at-a-glance)
- [Everyday charging operations](#everyday-charging-operations)
- [Add and edit historical records](#add-and-edit-historical-records)
- [Understand statistics and data quality](#understand-statistics-and-data-quality)
- [Native entities and automations](#native-entities-and-automations)
- [Manage archived data and currency](#manage-archived-data-and-currency)
- [Updates, backups and recovery](#updates-backups-and-recovery)
- [Troubleshooting](#troubleshooting)

## Before you install

You need **Home Assistant 2025.3.4 or newer** and at least one sensor measuring the charging circuit. Use an administrator account for installation and configuration. The interface follows the Home Assistant language; this guide uses its actual English labels. General HA menu locations may vary by version.

| Available measurement | **Energy input mode** | Use |
| --- | --- | --- |
| Cumulative energy in Wh, kWh or MWh | **Energy only** | Account from meter readings; start and end records using the card or automations |
| Power in W or kW | **Power only (native Integral)** | Automatically create a Home Assistant helper to calculate energy; optionally enable detection |
| Both energy and power | **Energy and power** | Measure with energy and detect with power, without counting energy twice |

Cumulative energy should normally increase, or restart from zero after a reset, rather than represent “energy used in the last hour”. Sensors must be identified as energy or power in Home Assistant and provide valid nonnegative values. The same source cannot be assigned to multiple charging points.

For dynamic pricing, prepare a sensor using the ledger currency. To add records from sensor history, make sure Home Assistant records those sensors and still retains the dates you need.

## Install the integration

### Option 1: HACS

If necessary, follow the [official HACS installation instructions](https://hacs.dev/docs/use/download/download/) first.

1. Open **HACS**, then its top-right menu and **Custom repositories**.
2. Add `https://github.com/enecess/ha-charge-tally` with type **Integration**.
3. Search for **Charge Tally**, open it and download the desired version.
4. **Restart Home Assistant**.
5. Open **Settings → Devices & services → Add integration**, then search for **Charge Tally**.
6. Continue with “Initial setup”. Downloading through HACS does not create the ledger or charging points.

> Screenshot placeholder 02: HACS custom repositories, the download page and the Add integration search result.

### Option 2: Manual installation

1. Download and extract this repository, then locate `custom_components/charge_tally`.
2. Open the Home Assistant configuration directory containing `configuration.yaml`.
3. Create `custom_components` if needed and copy the entire `charge_tally` folder into it, including all subdirectories.
4. Verify the final location is `custom_components/charge_tally/manifest.json`, without an extra repository directory.
5. **Restart Home Assistant**, then open **Settings → Devices & services → Add integration → Charge Tally**.

The card is bundled with the integration; no separate HACS frontend installation is required. If the integration is missing, check the directory structure and restart, then refresh and review the Home Assistant logs.

## Initial setup

### 1. Create the ledger

In **Charge Tally ledger**, enter the **Currency**, such as CNY, EUR or USD. Each Home Assistant instance uses one ledger; all points and records share its currency.

- Currency is editable when no charging points, including archived points, or accounting data remain. Identities alone do not lock it.
- Adding a point locks it, even before the first charge.
- Removing configuration preserves history. Clear all points and related data completely to change it again.
- Amounts are not converted. When adding back a removed integration, first select the retained ledger’s original currency.

> Screenshot placeholder 03: Charge Tally ledger and its currency guidance.

### 2. Add a charging point

HA versions supporting automatic continuation open the point dialog after ledger creation. Otherwise, use **Settings → Devices & services → Charge Tally → Add charging point**.

On **Charging point**, enter a **Name**, such as “Garage”, and choose **Energy input mode**. A point represents a separately metered charging circuit.

### 3. Select measurement sources

On **Measurement sources**, expand **Measurement and detection**:

| Field | What to enter |
| --- | --- |
| **Cumulative energy sensor** | The circuit’s cumulative energy sensor; hidden for **Power only (native Integral)** |
| **Power sensor** | The circuit’s power sensor; hidden for **Energy only** |
| **Meter may reset** | Leave enabled if the meter may return to zero; a falling reading marks an incomplete reset interval |
| **Maximum allocation interval (seconds)** | Default: 600 seconds; longer reading intervals become gaps requiring review |
| **Automatic charging detection** | Available in modes with power; enabling it opens detection settings next |

### 4. Configure automatic detection (optional)

After enabling **Automatic charging detection**, configure **Automatic detection**:

- **Start threshold (W)**: Power at or above this value starts confirmation.
- **Start duration (seconds)**: A record starts after the condition holds this long; default: 30 seconds.
- **End threshold (W)**: Power below this value starts end confirmation; it must be lower than the start threshold.
- **End duration (seconds)**: The record ends after this condition holds; default: 300 seconds.

Choose thresholds matching actual standby and charging power. Confirmed boundaries are backdated to when the condition first became true. A pause shorter than the end duration remains in the same record. Select the identity before power rises: ownership is remembered when start confirmation begins.

Detection is optional; you can use **Start record** and **End record** instead.

> Screenshot placeholder 04: Measurement and detection and the Automatic detection dialog.

### 5. Configure electricity pricing

The **Price mode** options differ slightly from the next dialog titles:

| Option | Next dialog | Fields |
| --- | --- | --- |
| **Static** | **Static price** | **Price per kWh**, in the ledger currency |
| **Dynamic sensor** | **Dynamic price** | **Price sensor**, and **Confirmed unit** if needed |
| **Daily time-of-use** | **Daily time-of-use schedule** | Add the periods covering a day |

Static and time-of-use prices can be zero or negative. Dynamic prices accept the ledger currency per Wh, kWh or MWh: units are normalized, currencies are not converted. **Confirmed unit** is needed only when the source has no unit; it cannot override an incorrect existing currency or unit.

For **Daily time-of-use schedule**:

1. Choose **Add period** under **Action**.
2. In **Edit price period**, enter **Start time**, **End time (24:00 = end of day)** and **Price per kWh**.
3. Add further periods. To change or delete one, select a **Period**, then **Edit period** or **Remove period**.
4. Once the whole day is covered, choose **Finish schedule**.

Use `HH:MM`, for example `00:00–08:00`, `08:00–22:00`, `22:00–24:00`. Overnight periods such as `22:00–06:00` are supported. Gaps, overlaps and equal endpoints are invalid; `00:00–24:00` covers a full day. The schedule repeats daily without separate weekday and weekend rules.

> Screenshot placeholder 05: Price mode, dynamic unit confirmation, the daily schedule and period editing.

### 6. Review period statistics and the summary

In **Period statistics and summary**, check the point name, energy input and price modes. Select **Daily / Monthly / Yearly** under **Energy statistics periods**. All are selected by default; none is also allowed.

These create additional native energy helpers. They do not control availability of the card’s record statistics or identity statistics. After setup, check that the point appears on the integration page, its sensors work and no helper repair issue appears.

> Screenshot placeholder 06: Period statistics and summary and the configured integration page.

## Identities and later configuration

Under **Settings → Devices & services → Charge Tally**, use:

| Entry | Purpose |
| --- | --- |
| **Add charging point** | Add another independently metered circuit |
| **Configure charging point** | Change name, sensors, detection, pricing and statistics periods |
| **Add shared identity** | Create an identity for a vehicle, person or other subject |
| **Configure identity** | Change name or **Enabled** |
| Main integration **Configure** | Open **Ledger settings** and **Manage archived data** |

**Shared identity** contains **Name** and **Enabled**. Identities are shared across points; configured names must be unique. The built-in **Unassigned** holds unassigned records and retains that English name in selectors.

Renaming keeps historical ownership. Clearing **Enabled** removes the identity from new selections but preserves history. Deleting its configuration also preserves history; archive management can then remove it permanently. Disabling and deleting configuration are different operations.

Before changing measurement or detection, end the current record and wait for **Confirming start / Confirming end** to finish. Price changes apply from the change time without repricing earlier amounts. Also end the record before deleting a point: removing configuration does not automatically settle an ongoing charge.

> Screenshot placeholder 07: Shared identity setup and the separate configuration entries for points and the main integration.

## Add and configure the dashboard card

1. Configure at least one point, then open the desired dashboard.
2. Enter editing mode. In a sections layout use a section’s plus button; otherwise use **Add card**.
3. Search by card type for **Charge Tally** and select it.
4. Set the visual editor options, save the card and finish dashboard editing.

| Editor field | Purpose |
| --- | --- |
| **Title** | Custom title; blank shows Charge Tally |
| **Charging point** | Initial point selection, or **All** |
| **Identity filter** | Initial identity selection, or **All** |
| **Show records** | Show/hide the list and its **Add history** entry |
| **Show chart** | Show/hide the chart without changing summary values |

You can create multiple cards with different initial selections. These are display filters, not account permissions; users still require Home Assistant authorization. The card supports English, Simplified Chinese, German, French, Polish and Italian, and follows the theme.

> Screenshot placeholder 08: Adding the card and its five visual editor settings.

### If the card is not listed

Confirm the integration has loaded, then refresh the browser. With resources managed through the interface, registration is normally automatic.

If necessary, open **Resources** from the **Settings → Dashboards** menu. Enable **Advanced mode** in your profile if it is hidden. Add this resource and refresh:

| Field | Value |
| --- | --- |
| URL | `/charge_tally/charge-tally-card.js?v=0.1.2-3` |
| Resource type | **JavaScript module** |

Update an existing entry for that path rather than duplicating it. If you manage resources in YAML, register this URL and module type there; do not install a second card copy. See the [Home Assistant dashboard documentation](https://www.home-assistant.io/dashboards/dashboards/).

## The card at a glance

### Connection status and filters

The title shows **Connected** or **Disconnected · waiting for a fresh snapshot**. Use **Retry** once the connection is available; do not treat an old display as current accounting data.

**Charging point** and **Identity filter** apply to statistics and records. Point selection also controls the live panels; the identity filter does not change a point’s selected identity. Retained items may be **Archived**. Archived points show historical data but no live start controls. Disabled identities may carry the same marker; eligibility for permanent removal is determined by archive management in integration settings.

### Live charging point panels

Each current point shows its name, status, **Power**, **Current price** and **Detection** state. Unavailable measurements may be blank. Detection here is only a status: change it in point configuration or with the native **Detection** switch.

| Content | Meaning |
| --- | --- |
| **Selected identity** | Select the next charge’s ownership when no record is active |
| **This record** | Identity assigned to the active record |
| **Next record identity** | Prepare the next identity without changing the current record |
| **Current record · provisional** | Active energy, cost, start, elapsed time and quality notices |
| **Details** | Open the active record |
| **Change record identity** | Correct its ownership |
| **Start record / End record** | Begin/end accounting at the current time |

> Screenshot placeholder 09: Active charging, current/next identity, provisional cost and actions.

### Record statistics and charts

In **Record statistics → Statistics period**, choose **Today / This month / This year / All time / Custom range**. For custom dates, enter **Start** and **End (exclusive)**, then **Apply range**. To view September 1 in full, choose September 1 as start and September 2 as end.

The summary shows **Energy**, **Cost**, **Active / completed** and quality notices. **Refresh** fetches current results. Charts group values by date; **Chart metric** switches **Energy / Cost**. Expand **Details** below the chart for daily values.

> Screenshot placeholder 10: Statistics, custom dates, Chart metric and expanded daily Details.

### Records · all dates

Active and ended records appear newest start first, 25 per page, with **Previous / Next** controls. Each row shows point, identity, start, status, energy, cost and quality; click the row for details.

Only point and identity filters apply: **statistics dates do not filter this list**. Older records remain visible with Today selected. **Add history** is beside the heading. An empty list displays **No records**.

> Screenshot placeholder 11: Records · all dates, Add history, rows and pagination.

## Everyday charging operations

### Start and end manually

1. Set the point’s **Selected identity**.
2. Click **Start record** and verify **Current record · provisional** appears.
3. When charging finishes, click **End record**, then review it from the record list.

These buttons only record boundaries; they do not control the charger. A manually started record needs a manual or automation end, even if automatic detection is configured.

### Detect charging automatically

With detection configured and enabled, states can progress through **Confirming start → Charging → Confirming end → No active record**. If power no longer meets the condition during confirmation, that pending start or end is canceled without necessarily creating or ending a record.

Before pausing with the native **Detection** switch, finish active records and pending confirmation. If thresholds are not configured, open **Configure charging point** first instead of just enabling the switch. After a manual end, detection must observe power below the end threshold before detecting another charge.

### View details and revisions

Details include ownership, energy, cost, boundaries, accounting timezone, **Status**, **Source**, **Revision**, note and quality.

- **Accounting segments** shows time, energy, cost and **Data quality** for each segment, useful at midnight boundaries or price changes.
- **Revision history** expands to previous identities, states, amounts and notes. It is an audit trail, with no rollback button.
- Active records allow **Change record identity**; only ended records show **Edit record** and **Void record**.

> Screenshot placeholder 12: An ended record, accounting segments, revision history and actions.

### Correct an identity

In details, choose **Change record identity**, select **Assigned identity**, then **Save preview**. That is this dialog’s actual submit label; it requires no separate **Preview changes** step. The whole record transfers without recalculating energy or cost.

### Void an incorrect record

On an ended record choose **Void record**, review, then **Confirm void**. It leaves statistics and the ordinary list, but remains in the ledger with its revisions. There is no “show voided records” or restore button. Voiding is not permanent deletion.

## Add and edit historical records

**Add history** opens **New history record**. To edit, open an ended record and choose **Edit record**.

1. Check **Accounting timezone**, **Charging point** and **Assigned identity**. New records need a current point and enabled identity; an archived point cannot receive new records even if listed. Editing keeps the original point fixed.
2. Enter **Start** and **End (exclusive)** dates/times; end must follow start.
3. Enter or leave blank manual energy and choose the cost basis below.
4. Optionally add a **Note**, up to 2000 characters.
5. Choose **Preview changes**. In **Preview · review before saving**, review amounts, segments, quality and **Measurement coverage**. Edits also show **Before / After**.
6. With no overlaps, choose **Save preview**. Form changes require another preview; **Close** does not save.

| Field or option | Behavior |
| --- | --- |
| New record: **Manual energy (kWh, blank: use history)** | Blank uses available measurements; a value supplies total energy |
| Edit: **Manual energy (kWh, blank: keep existing basis)** | Blank preserves the existing basis rather than clearing a manual override |
| **Cost basis → Use available history and prices** | Default for new history, dependent on available history and prices |
| **Cost basis → Keep existing cost basis** | Default for editing; note-only changes do not reprice |
| **Cost basis → Manual total cost** | Enables **Manual total cost**, accepting a known total including zero or negative amounts |
| **Cost basis → Pending** | Explicitly keeps cost unknown instead of treating it as free |

Records at the same point cannot overlap. Overlapping previews cannot be saved. If a preview is stale or a record changed, refresh and preview again.

Reconstruction depends on data retained by Home Assistant and the ledger; arbitrary old dates cannot be guaranteed. With missing data, enter total energy and cost from the charger’s bill. Allocating manual totals over time produces **Manual override / Estimated** notices explaining the basis.

Times use the displayed accounting timezone, not the browser timezone. For repeated local times at daylight-saving transitions, choose **Repeated local time: select UTC instant**. Nonexistent local times cannot be submitted.

> Screenshot placeholder 13: New history record / Edit record, Cost basis, preview and coverage.

## Understand statistics and data quality

| Notice | Meaning |
| --- | --- |
| **Provisional / Pending settlement** | Record or measurement boundaries are not final; later readings may update results |
| **known subtotal · pending** | Only known cost, not a complete bill; unknown does not mean zero |
| **Missing price / Unknown price** | No valid price; check currency, units, availability and retained history |
| **Missing energy / Observation gap** | Insufficient data or overly long intervals; review and add manual values if needed |
| **Meter reset** | A falling reading made the affected interval incomplete |
| **Manual override / Estimated** | Manual values or time allocation, not actual measurements at every instant |

Energy is split into the days, months and years where it occurs; a charge crossing midnight is not all counted on its starting day. History retains its own accounting timezone. The completed count in **Active / completed** groups by record start: a record may contribute energy across a boundary without increasing that range’s completed count.

Card and identity statistics count charging records. Native energy statistics may also include standby outside records, so totals can differ. Editing updates the ledger without rewriting native meter history. Cost charts show known amounts; display rounding does not alter stored precision.

## Native entities and automations

Use integration data in HA entity pages, other cards and automations. Examples below use a point called “Garage” and identity “Family car”; names follow your configuration.

| Visible entity | Purpose |
| --- | --- |
| **Garage Energy** | Cumulative point energy |
| **Garage Status** | Charging or availability state |
| **Garage Record energy / Garage Record cost** | Active record; no current value when idle, not the previous record |
| **Garage Identity** | Select the next identity, including via RFID or buttons |
| **Garage Detection** | Detection switch in power modes; not charger power control |
| **Family car daily energy / daily cost, monthly energy / monthly cost, yearly energy / yearly cost, total energy / total cost** | Identity record statistics; Unassigned also has these |

Incomplete native cost entities may lack a complete value while the card shows the known subtotal. Daily/monthly/yearly energy helpers selected at setup have a different purpose from identity statistics. Do not manually remove or alter the integration’s managed helpers.

The automation action picker offers **Charge Tally: Start accounting / End accounting / Reassign record identity**. Start/end use server current time, not historical boundaries; use the card for history.

The forms require **Request ID**; ending and reassignment also require **Expected record revision**. These actions need more than selecting a device. Use a new request identifier per new operation, reusing the identifier and fields for retries. To change only the next identity, use **Garage Identity**. If unfamiliar with these validation fields, use the card for direct accounting.

## Manage archived data and currency

### Configuration removal, voiding and permanent cleanup

| Operation | Result |
| --- | --- |
| Disable identity | Removes new selections; keeps configuration and history |
| Delete point/identity configuration | Keeps ledger history and enables archive management; disabling is not deletion |
| Void record | Excludes ordinary list/statistics, retaining audit data |
| Permanent archive operation | Removes ledger objects and related data; no interface undo |

### Permanently clear an archived charging point

1. Open the main integration’s **Configure → Manage archived data → Archived charging points**.
2. In **Select archived item**, select a point whose configuration was deleted.
3. In **Confirm permanent operation**, review item, operation, records including voided, revisions, UTC range, energy and known cost.
4. Check **I understand the impact and confirm permanent deletion** and submit. **Archive operation complete** reports the deleted count.

This deletes ledger records, revisions, samples and price history for the point, rather than just hiding its name.

### Permanently remove an archived identity

Open **Configure → Manage archived data → Archived identities** and select an item. If records exist, choose **Receiving identity** under **Transfer identity records**: an enabled identity or **Unassigned**. With no records, go directly to confirmation.

All records, including voided ones, transfer without changing amounts. The source identity is deleted, while old revisions retain its name for audit. Unassigned cannot be deleted. In-use items or data changes during confirmation block the operation; finish active records or reopen the preview.

Cleanup affects only the ledger, **not Home Assistant recorder history, native long-term statistics or backups**. Confirmation totals include listed voided records to describe scope; do not compare them directly with ordinary statistics that exclude voided records.

> Screenshot placeholder 14: Archive categories, item selection, identity transfer and permanent confirmation.

### Change currency

Open **Configure → Ledger settings** on the main integration. Currency is editable only without any points, including archived, or accounting data. Otherwise **Ledger currency locked** explains the restriction. Identities alone do not lock it.

To start over with another currency, back up, delete unneeded point configurations, clear related data through archive management, then reopen settings. This selects currency after clearing data; it does not convert history.

## Updates, backups and recovery

1. Back up the Home Assistant configuration directory before updating.
2. Update HACS installations through HACS, or replace the complete integration folder for manual installs, retaining its structure.
3. Restart Home Assistant and refresh the dashboard in the browser/app. For manually managed resources, check the resource version above too.
4. Check points, records and statistics; follow helper repairs if prompted.

The ledger is stored in the Home Assistant configuration directory. When Home Assistant creates a backup, the integration prepares a consistent ledger copy. Removing the integration or program files does not actively clear the ledger; select its original currency when adding it back. Restore matching configuration and ledger data rather than mixing dates.

Local brand icons require **Home Assistant 2026.3 or newer**; older icon behavior does not affect accounting.

## Troubleshooting

| Problem | Check |
| --- | --- |
| Integration missing after download | Correct integration folder without extra nesting, restart completed, search in Add integration rather than just the card picker |
| Card missing | Integration loaded, frontend refreshed, correct Resources URL and JavaScript module type |
| **No accessible charging points. Configure Charge Tally or check permissions.** | At least one point and user read permission; identities alone create no live point |
| No automatic records | Power source, completed detection setup, switch enabled, thresholds/durations satisfied |
| **Start record** unavailable | Sources and point identity entity available; loading/repair completed |
| Identity change did not affect this record | Selector prepares the next record; use **Change record identity** |
| Today still shows older records | Dates filter statistics, not **Records · all dates** |
| Known subtotal only or native cost unavailable | Review gaps, historical prices, currency and quality; do not assume free charging |
| Stale preview, changed record or overlap | Refresh, reopen and preview again; adjust overlaps, as validation cannot be skipped |
| **Charging point helpers need repair** | Open HA repairs, choose **Repair managed helpers** and confirm; rebuild owned helpers while keeping history |
| Currency locked after removing configuration | Archived data remains; inspect **Manage archived data** |
| Regular user cannot see archives or operate | Check HA read/control permission; use an administrator for archives. Filters do not grant permission |

> Screenshot placeholder 15: Charging point helpers need repair and Repair managed helpers confirmation.

Need help? [Open an issue](https://github.com/enecess/ha-charge-tally/issues) with HA and Charge Tally versions, input/price modes, steps and exact messages. Hide private information in screenshots.

[MIT license](LICENSE)
