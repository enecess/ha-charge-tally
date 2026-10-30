# Charge Tally

**English** · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Polski](README.pl.md) · [Italiano](README.it.md)

Track charging energy and cost by charging point and identity in Home Assistant, and review how each charge was calculated. Charge Tally uses your existing energy or power sensors. It keeps accounting records; it does not switch the charger on or off.

- Manage multiple charging points in one ledger, with shared identities for vehicles, drivers or household members.
- Measure cumulative energy, calculate energy from power, or combine energy measurement with power-based detection.
- Use static, dynamic or daily time-of-use prices, including zero and negative prices.
- Detect charging automatically, or start and end records from the card or Home Assistant automations.
- View live charging, statistics for today, this month, this year, all time or a custom range, and charts grouped by range.
- Add history, edit ended records, change identities, void incorrect records, and inspect fee details.
- Manage archived charging points and identities, and permanently clear unneeded ledger data.

Use **Settings → Devices & services → Charge Tally** for configuration and the **Charge Tally** dashboard card for records. The card contains several sections on one page; details and editing open in dialogs.

> Screenshot placeholder 01: The complete card, including charging points, record statistics and the record list.

## Current card and accounting behavior

Only charging controls are expanded when the page opens. Statistics and records start collapsed; live updates retain your open sections and controls, while reloading the page restores the defaults. Expand statistics to load its chart and expand records to load history.

Charts group Today by hour, This month by day, This year by month, and Total by year. For a custom range, the difference between the local calendar dates determines grouping: up to 2 days uses hours, up to 90 days uses days, up to 730 days uses months, and longer ranges use years. Buckets follow the ledger timezone, including daylight-saving transitions. Energy and known-cost charts use the same range as the summary; unknown cost remains unknown.

Fee details in previews and record details group consecutive periods with the same price and billing basis. Sampling-quality changes do not split a price period; real energy gaps remain separate notices. Original sampling details remain the basis of time-range statistics.

Removing a charging point configuration retains its unfinished records. To clear them, open the main integration's **Configure → Manage archived data → Archived charging points**, select the removed point, review the unfinished count and affected data, then explicitly confirm permanent deletion. Canceling confirmation preserves the records. Cleanup includes the point's records, revisions, samples and prices; it does not remove HA recorder data or backups.

The current development ledger format has changed. Unsupported older formats are rejected without automatic migration or deletion. A disposable development test ledger may need to be recreated after backing it up; updating the integration does not perform this cleanup.

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

You need **Home Assistant 2025.9.0 or newer** and at least one sensor measuring the charging circuit. Use an administrator account for installation and configuration. The interface follows the Home Assistant language; this guide uses its actual English labels. General HA menu locations may vary by version.

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

**One-click add to HACS:**

[![Open Charge Tally in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=enecess&repository=ha-charge-tally&category=integration)

Click the button, enter or confirm your Home Assistant address, then add or open Charge Tally in HACS. Continue from step 3 below to download, restart and add the integration, or start at step 1 to add the repository manually.

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

In **Charge Tally ledger**, select the **Currency** from all currencies supported by Home Assistant. Options show the localized name and ISO code, such as Chinese Yuan (CNY), and are sorted by name in your interface language. The initial selection uses the currency in Home Assistant’s household settings. Each Home Assistant instance uses one ledger; all points and records share its currency.

- Currency is editable when no charging points, including archived points, or accounting data remain. Identities alone do not lock it.
- Adding a point locks it, even before the first charge.
- Removing a point or identity configuration preserves history. Clear all points and related data completely to change the currency again.
- Removing the entire integration permanently deletes its ledger and private data. Adding it again creates a fresh ledger in the selected currency.
- Old ledger files left by a previously removed integration are cleared when you submit this form.

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
| **Long sampling interval threshold (seconds)** | Default: 600 seconds; longer valid cumulative-meter intervals are allocated by time and marked estimated |
| **Automatic charging detection** | Available in modes with power; enabling it opens detection settings next |

### 4. Configure automatic detection (optional)

After enabling **Automatic charging detection**, configure **Automatic detection**:

- **Start threshold (W)**: Power at or above this value starts confirmation.
- **Start duration (seconds)**: A record starts after the condition holds this long; default: 30 seconds.
- **End threshold (W)**: Power below this value starts end confirmation; it must be lower than the start threshold.
- **End duration (seconds)**: The record ends after this condition holds; default: 300 seconds.

Choose thresholds matching actual standby and charging power. Confirmed boundaries are backdated to when the condition first became true. A pause shorter than the end duration remains in the same record. You can select an identity before start confirmation completes; it applies to this charge without changing its start time or confirmation progress.

Detection is optional; you can use **Start recording manually** and **End recording** instead.

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
| Main integration **Configure** | Open **Ledger settings** and **Manage archived data**; **NFC identity links** |

**Shared identity** contains **Name** and **Enabled**. Identities are shared across points; configured names must be unique. The built-in **Unassigned** holds unassigned records and retains that English name in selectors.

Renaming keeps historical ownership. Clearing **Enabled** removes the identity from new selections but preserves history. Deleting its configuration also preserves history; archive management can then remove it permanently. Disabling and deleting configuration are different operations.

Before changing measurement or detection, end the current record and wait for **Confirming charging / Confirming end** to finish. Price changes apply from the change time without repricing earlier amounts. Also end the record before deleting a point: removing configuration does not automatically settle an ongoing charge.

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
| URL | `/charge_tally/charge-tally-card.js?v=0.1.2-13` |
| Resource type | **JavaScript module** |

Update an existing entry for that path rather than duplicating it. If you manage resources in YAML, register this URL and module type there; do not install a second card copy. See the [Home Assistant dashboard documentation](https://www.home-assistant.io/dashboards/dashboards/).

## The card at a glance

### Connection status and filters

The title shows **Connected** or **Disconnected · waiting for a fresh snapshot**. Use **Retry** once the connection is available; do not treat an old display as current accounting data.

**Charging point** and **Identity filter** apply to statistics and records. Point selection also controls the live panels; the identity filter does not change a point’s selected identity. Retained items may be **Archived**. Archived points show historical data but no live start controls. Disabled identities may carry the same marker; eligibility for permanent removal is determined by archive management in integration settings.

### Live charging point panels

The panel separates recording state from **Power** and **Detection**. **Not recording**, **Manual recording in progress** and **Automatic recording in progress** describe the ledger; an active record does not imply that the charger is drawing power. Detection separately reports waiting, confirmation, a manual-record pause, unavailable data or waiting for power to fall.

During start confirmation, **Identity for this pending charge** shows the current candidate identity. **Pending / manual record identity** changes this pending charge or an immediate manual start. The start time and confirmation progress stay the same; existing records keep their identity.

Each current point shows its name, status, **Power**, **Current price** and **Detection** state. Unavailable measurements may be blank. Detection here is only a status: change it in point configuration or with the native **Detection** switch.

| Content | Meaning |
| --- | --- |
| **Selected identity** | Select ownership for the pending charge or the next charge when no record is active |
| **This record** | Identity assigned to the active record |
| **Next record identity** | Prepare the next identity without changing the current record |
| **Recording · Current total** | Active energy, cost, start, elapsed time and quality notices |
| **Details** | Open the active record |
| **Change record identity** | Correct its ownership |
| **Start recording manually / End recording** | Begin/end accounting at the current time |

> Screenshot placeholder 09: Active charging, current/next identity, provisional cost and actions.

### Record statistics and charts

In **Record statistics → Statistics period**, choose **Today / This month / This year / All time / Custom range**. For custom dates, enter **Start** and **End (exclusive)**, then **Apply range**. To view September 1 in full, choose September 1 as start and September 2 as end.

The summary shows **Energy**, **Cost**, **Active / completed** and quality notices. **Refresh** fetches current results. Charts group values by the selected range; **Chart metric** switches **Energy / Cost**. Expand **Details** below the chart for values by bucket.

**Export PDF** downloads a searchable A4 report in the card’s language, using the point, identity and statistics range applied when you click. Unapplied date drafts do not change it. All matching readable records are included, even when the records panel is hidden or on another page. Choose **All** identities for a combined report; later filter changes and live updates do not change an export already in progress.

Rows show complete record times and only their energy and cost contribution within the selected period. Active records are provisional; incomplete costs show the known subtotal and quality notes, and unknown values are not zero. The completed count means records that started in the period and have ended. Totals use unrounded values; displayed energy has up to 3 decimals and cost 2, so rounded rows can differ from the total in the last digit.

Wait while the PDF is generated; another export can be retried after it finishes. If the report is too large, shorten the period or filter by point or identity. A font error identifies the field, record row when available and Unicode codepoints: edit those characters in the name or note, then retry. A disconnect or integration unload cancels the download.

> Screenshot placeholder 10: Statistics, custom dates, Chart metric and expanded grouped Details.

### Records · all dates

Active and ended records appear newest start first, 25 per page, with **Previous / Next** controls. Each row shows point, identity, start, status, energy, cost and quality; click the row for details.

Only point and identity filters apply: **statistics dates do not filter this list**. Older records remain visible with Today selected. **Add history** is beside the heading. An empty list displays **No records**.

> Screenshot placeholder 11: Records · all dates, Add history, rows and pagination.

## Everyday charging operations

### Start and end manually

1. Select the point’s identity and click **Start recording manually**; during start confirmation, use **Start recording now**.
2. Verify **Manual recording in progress** and the current totals. An immediate manual start uses the currently selected identity and clears the automatic candidate.
3. Click **End recording** to finish, then review the record in the list.

These buttons only record boundaries; they do not control the charger. Automatic charging detection pauses during a manually started record, even at zero power. End it from the card or an automation action, or let the source-unavailable rule below close it after a persistent measurement outage. A valid energy baseline is required to start; an existing record can still be ended if measurements become unavailable.

### Detect charging automatically

With detection configured and enabled, detection can progress through **Confirming charging → Tracking an automatic record → Confirming end → Waiting for automatic detection**. If the power condition fails during confirmation, the pending start or end is canceled. Automatic confirmation uses the last successfully selected identity before confirmation completes, including **Unassigned**. You can end an automatic record early with **End recording manually**, or **End recording now** during end confirmation.

After an explicit end, detection normally waits for power to fall below the end threshold. It can resume immediately only if the latest valid low-power observation is no later than the end command, its age does not exceed the duration set by **Long sampling interval threshold (seconds)**, and neither unavailable data nor a restart has invalidated it. High, missing, future or stale readings do not release the block. After `unknown` or unavailable power, a subsequent valid low-power observation is required. While blocked, manual recording remains available. A source-unavailable timeout is different: after recovery and a fresh energy baseline, automatic detection may confirm a new high-power cycle without first seeing low power.

### Temporary outages and automatic closure

A required measurement source that becomes unavailable starts a fixed **5-minute (300-second)** waiting period. This duration is not configurable. If every required source recovers before the deadline, the same record continues. In cumulative-energy modes, a nondecreasing meter reading recovers the missing increment; time-based allocation across tariff, date or record boundaries is marked estimated. Power is not used to replace missing cumulative-meter readings.

At 300 seconds, the record closes with its end time set to **the start of the outage**, not the timeout time. For example, an outage beginning at 10:01 is confirmed at 10:06, and the record ends at 10:01. Waiting-period amounts provisionally recorded while another required source was unavailable are removed. Recovery after timeout never backfills that bill or transfers the outage increment to a new record. The first fresh energy sample after recovery establishes the next billing baseline. A reload preserves the original deadline.

Manual energy-plus-power records require the energy source; power loss alone does not end them. Automatic energy-plus-power records require both sources. Power-only records require raw power and the native Integral sensor. Missing tariff data does not trigger record closure. A valid sensor that simply has no new reports does not start the unavailable timer.

Point cumulative energy and its Utility Meter helpers still reflect meter increments, including electricity outside recorded charges. Genuine meter resets, missing initial baselines and missing raw power cannot be reconstructed from invented readings. Unknown prices remain unknown; only already calculated amounts are included in the cost subtotal.

Before pausing with the native **Detection** switch, finish active records and pending confirmation. If thresholds are not configured, open **Configure charging point** first.

### View record details

Details show ownership, energy, cost, a compact date range and duration, accounting timezone, status, source and any note. One main notice explains missing energy, missing prices or a pending final sample. An unknown cost is not shown as zero; a manual cost remains the specified total even when measurement coverage is incomplete.

- **Fee details** starts collapsed. Expand it to see chronological price periods with energy and cost, separate gap notices and shared sampling explanations. Dates are grouped; more than 12 periods can be expanded. A rounding note appears only when displayed items differ from the displayed total. Manual fees show one total and measured energy coverage; manually entered energy does not imply measurement coverage.
- Active records allow **Change record identity**; only ended records show **Edit record** and **Void record**.

> Screenshot placeholder 12: An ended record with expandable fee details and actions.

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
5. Choose **Preview changes**. In **Preview · review before saving**, review amounts, **Fee details** and **Measurement coverage**. Edits also show **Before / After**.
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

Previews expire 30 minutes after creation. After upgrading, create a new preview for any draft opened before the upgrade. Successful saves remain safe to retry with the same request ID.

Reconstruction depends on data retained by Home Assistant and the ledger; arbitrary old dates cannot be guaranteed. With missing data, enter total energy and cost from the charger’s bill. Allocating manual totals over time produces **Manual override / Estimated** notices explaining the basis.

Times use the displayed accounting timezone, not the browser timezone. For repeated local times at daylight-saving transitions, choose **Repeated local time: select UTC instant**. Nonexistent local times cannot be submitted.

> Screenshot placeholder 13: New history record / Edit record, Cost basis, preview and coverage.

## Understand statistics and data quality

| Notice | Meaning |
| --- | --- |
| **Provisional / Pending settlement** | Record or measurement boundaries are not final; later readings may update results |
| **known subtotal · pending** | Only known cost, not a complete bill; unknown does not mean zero |
| **Missing price / Unknown price** | No valid price; check currency, units, availability and retained history |
| **Missing energy** | Energy coverage cannot be established; review and add manual values if appropriate |
| **Observation gap / Estimated** | A sampling interruption or long interval; a valid cumulative increment may still be allocated proportionally |
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
| **Garage Current/latest record energy / calculated cost** | Active record, or the latest non-void ended record when idle; attributes identify its status and end reason |
| **Garage Identity** | Select the next identity, including via RFID or buttons |
| **Garage Detection** | Detection switch in power modes; not charger power control |
| **Family car daily energy / daily cost, monthly energy / monthly cost, yearly energy / yearly cost, total energy / total cost** | Identity record statistics; Unassigned also has these |

Native cost entities publish the **calculated subtotal**, including when a bill is incomplete. Check `cost_complete`, `has_known_cost` and `quality`: a zero subtotal with `has_known_cost=false` is not proof of free charging, and an estimated amount need not be exact. Daily/monthly/yearly energy helpers selected at setup have a different purpose from identity statistics. Do not manually remove or alter the integration’s managed helpers.

Existing entity IDs and statistics identities remain unchanged. Upgrades do not rewrite past Recorder unknown states or bulk-recalculate old bills. Late short-outage recovery can update the ledger's original calendar-day totals; the native HA graph records the time a sensor value was published. Use the card or PDF ledger report to reconcile charges by their actual accounting period.

The automation action picker offers **Charge Tally: Start accounting / End accounting / Reassign record identity**. Start/end use server current time, not historical boundaries; use the card for history.

The forms require **Request ID**; reassignment also requires **Expected record revision**. For ending a record, the revision is optional: omit it to allow ongoing meter updates, or supply it to require an exact revision match. The card ends the displayed record by its fixed record ID. Use a new request identifier per new operation, reusing the identifier and fields for retries. To change only the next identity, use **Garage Identity**. If unfamiliar with these validation fields, use the card for direct accounting.

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
2. In **Select archived items**, select one or more points whose configurations were deleted.
3. In **Confirm permanent operation**, review item, operation, records including voided, revisions, UTC range, energy and known cost.
4. Check **I understand the impact and confirm permanent deletion** and submit. **Archive operation complete** reports the deleted count.

This deletes ledger records, revisions, samples and price history for the point, rather than just hiding its name.

### Permanently remove an archived identity

Open **Configure → Manage archived data → Archived identities** and select one or more items. If any selected identity has records, choose one **Receiving identity** under **Transfer identity records**: an enabled identity or **Unassigned**. With no records, go directly to confirmation.

All selected items are processed together. If any item changes or an operation fails, none of the selected items are changed.

All records, including voided ones, transfer without changing amounts. The source identity is deleted, while old revisions retain its name for audit. Unassigned cannot be deleted. In-use items or data changes during confirmation block the operation; finish active records or reopen the preview.

Cleanup affects only the ledger, **not Home Assistant recorder history, native long-term statistics or backups**. Confirmation totals include listed voided records to describe scope; do not compare them directly with ordinary statistics that exclude voided records.

> Screenshot placeholder 14: Archive categories, item selection, identity transfer and permanent confirmation.

### Change currency

Open **Configure → Ledger settings** on the main integration. The dropdown keeps the ledger’s current currency selected, even if the Home Assistant system currency changes. Currency is editable only without any points, including archived, or accounting data. Otherwise **Ledger currency locked** explains the restriction. Identities alone do not lock it.

To start over with another currency, back up, delete unneeded point configurations, clear related data through archive management, then reopen settings. This selects currency after clearing data; it does not convert history.

## Updates, backups and recovery

1. Back up the Home Assistant configuration directory before updating.
2. Update HACS installations through HACS, or replace the complete integration folder for manual installs, retaining its structure.
3. Restart Home Assistant and refresh the dashboard in the browser/app. For manually managed resources, check the resource version above too.
4. Check points, records and statistics; follow helper repairs if prompted.

The ledger is stored in the Home Assistant configuration directory. Home Assistant backups receive a consistent ledger copy. Removing the entire integration permanently deletes its ledger, internal backup and private settings; adding it again creates a fresh ledger with the selected currency. Restarting, reloading or updating preserves data. Removing program files alone does not run cleanup. HA recorder history, native statistics, external backups and user automations are not deleted. Restore matching configuration and ledger data together.

Local brand icons require **Home Assistant 2026.3 or newer**; older icon behavior does not affect accounting.

## Troubleshooting

| Problem | Check |
| --- | --- |
| Integration missing after download | Correct integration folder without extra nesting, restart completed, search in Add integration rather than just the card picker |
| Card missing | Integration loaded, frontend refreshed, correct Resources URL and JavaScript module type |
| **No accessible charging points. Configure Charge Tally or check permissions.** | At least one point and user read permission; identities alone create no live point |
| No automatic records | Power source, completed detection setup, switch enabled, thresholds/durations satisfied |
| **Start recording manually** unavailable | Sources and point identity entity available; loading/repair completed |
| Identity change did not affect this record | Selector prepares the next record; use **Change record identity** |
| Today still shows older records | Dates filter statistics, not **Records · all dates** |
| Calculated cost is incomplete or zero without known prices | Review `cost_complete`, `has_known_cost`, source coverage and historical prices; do not assume free charging |
| Stale preview, changed record or overlap | Refresh, reopen and preview again; adjust overlaps, as validation cannot be skipped |
| **Charging point helpers need repair** | Open HA repairs, choose **Repair managed helpers** and confirm; rebuild owned helpers while keeping history |
| Currency locked after removing configuration | Archived data remains; inspect **Manage archived data** |
| Regular user cannot see archives or operate | Check HA read/control permission; use an administrator for archives. Filters do not grant permission |

> Screenshot placeholder 15: Charging point helpers need repair and Repair managed helpers confirmation.

Need help? [Open an issue](https://github.com/enecess/ha-charge-tally/issues) with HA and Charge Tally versions, input/price modes, steps and exact messages. Hide private information in screenshots.

[MIT license](LICENSE)

## NFC identity links

Administrators can open **Settings → Devices & services → Charge Tally → Configure → NFC identity links**. Register a tag in HA first, then choose the tag, charging point, scanning devices and identities. Add multiple device bindings or only a default identity. Each tag/point pair has one managed automation. A shared tag can act on several points independently.

Device bindings take priority; other devices use the optional default. Without a default, no action occurs. Scanning selects a recording identity. Before start confirmation completes, it applies to this charge without changing its start time or confirmation progress; existing records keep their identity. Identity renames preserve bindings. A deleted tag, device or point, or a disabled identity, blocks the whole link until repaired; it never silently falls back to another identity.

Automations are marked **Charge Tally managed** and explain where to edit them. Edit mappings in the integration; use HA for traces and pausing. Saving preserves the paused state. HA's native entity ID rename can itself re-enable an automation, so check its switch afterward. External edits require explicit **Restore integration configuration**; deleted automations require **Recreate automation**. After a lost connection, **Complete pending operation** reuses the same automation.

Restore and recreate let you repair invalid mappings before confirming. Replacing external edits requires explicit confirmation. A pending deletion can be cancelled while the automation still exists, preserving its current HA configuration.

Before removing the entire integration, delete links from this page to clean up their automations. Management requires administrator access and loaded HA automation/configuration components. It does not write NFC tags or control a charger.
