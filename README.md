# Charge Tally

**English** · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Polski](README.pl.md) · [Italiano](README.it.md)

Keep track of charging energy and costs in Home Assistant. Charge Tally uses your existing energy or power sensors to create charging records, and lets you assign each record to a vehicle, driver or another name of your choice.

- Use a fixed price, a price sensor, or different prices at different times of day.
- Detect charging automatically, or start and end records yourself.
- See today's, this month's and this year's energy and costs for each identity.
- Add past charging sessions and correct their details.
- View and control everything from a dashboard card.

> Screenshot placeholder: dashboard card with charging status, identity selection and statistics.

## Before you start

You need Home Assistant and at least one sensor that measures the charging circuit. Charge Tally records charging; it does not turn your charger on or off.

Requires **Home Assistant 2025.3.4 or newer**. Tested on 2025.3.4, 2025.12.4, 2026.3.4 and 2026.9.1.

| Sensors you have | Choose during setup |
| --- | --- |
| A running energy total in Wh, kWh or MWh | **Energy only** |
| Power in W or kW | **Power only** — Home Assistant calculates the energy used |
| Both | **Energy and power** — energy measures usage, power detects charging |

A running energy total is a meter reading that normally increases, not just the energy used in the last hour. Automatic detection requires a power sensor.

## Install with HACS

1. Open **HACS**, then its menu → **Custom repositories**.
2. Enter `https://github.com/enecess/ha-charge-tally` and choose **Integration**.
3. Find **Charge Tally** in HACS and download it.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration** and search for **Charge Tally**.

For a manual installation, copy the repository's `custom_components/charge_tally` folder into your Home Assistant `custom_components` folder, then restart.

## Set up your first charging point

If the charging-point form does not open automatically after choosing the currency, open Charge Tally under **Settings → Devices & services** and choose **Add charging point**.

1. **Choose your currency.** All charging points and records share one currency. Change it in Configure → Ledger settings when no charging points (including archived points) or accounting data remain. Identities alone do not lock it. Removing a point keeps its history and the currency lock; fully clearing points and related data through Manage archived data allows changes again. Dynamic prices must use the same currency; amounts are never converted automatically. When restoring a retained ledger, select its original currency first.
2. **Name the charging point**, choose which sensors you have, and select them.
3. If you have a power sensor, choose whether to enable **automatic charging detection**. Set the power levels and how long they must last before charging starts or ends. The end level must be lower than the start level.
4. **Choose your electricity price** using the table below.
5. Select any daily, monthly or yearly energy meters you want, then finish setup.

| Price option | What to enter |
| --- | --- |
| Fixed price | Your price per kWh |
| Dynamic price | A price sensor using the same currency as Charge Tally |
| Time-of-use price | The start, end and price of each period, covering the whole day |

Time-of-use prices repeat every day. Periods can cross midnight; use `24:00` for the end of the day. Zero and negative prices are supported.

> Screenshot placeholder: sensor selection and electricity price setup.

To add another charging point or an identity, open **Charge Tally** under **Settings → Devices & services**. You can also change an existing point's settings there. End its current charging record before changing measurement or detection settings.

## Add the dashboard card

Edit your dashboard, select **Add card**, and search for **Charge Tally**. Its editor lets you choose the charging points, identities and information to display. The card follows your Home Assistant language and theme.

The card is normally available automatically. If it is missing, refresh the browser first. If you manage dashboard resources yourself, add `/charge_tally/charge-tally-card.js?v=0.1.2-3` as a **JavaScript module**, then refresh again.

## Use identities and charging records

An identity can represent a car, a family member, or anything else you want to track. Identities are shared across charging points. **Unassigned** is available if you have not chosen one.

Choose the identity before charging starts. Once a record starts, it keeps that identity. Changing the selection while charging prepares the **next** record. To correct the current or an older record, use **Change record identity**.

With automatic detection enabled, a record starts and ends after your power thresholds and waiting times are met. Short pauses can stay in the same record. Without detection, use **Start record** and **End record** on the card.

For your own automations, select the charging point's **Identity** entity to choose who is charging. For example, an RFID reader or a button can change this selection. The automation action picker also provides Charge Tally actions to start or end a record.

## Add or correct past charging

1. Select **Add history** on the card, or open a finished record and choose **Edit record**.
2. Choose the charging point, identity, start and end times.
3. Use available sensor history, or enter the energy total yourself. Choose how to calculate the cost, or leave it pending if you do not know it yet.
4. Select **Preview changes**, check the result, then **Save preview**.

History depends on what Home Assistant has retained. If readings are missing, you can enter the total from another source, such as your charger's own record. Two records at the same charging point cannot overlap.

Use **Void record** to exclude an incorrect record from totals. Its previous details remain available for reference.

> Screenshot placeholder: a past charging record and its preview before saving.

## Understanding the totals

- **Charging across midnight:** usage is split between the dates it belongs to. The same applies across months and years. Where a meter reading spans a boundary, the split is estimated from the elapsed time.
- **Charging in progress:** figures can change as more readings arrive or the final end time is confirmed.
- **Pending cost:** some prices are missing. The displayed known amount is only part of the cost, not the final bill.
- **Meter totals and record totals can differ:** meters include energy used outside charging records, such as standby usage. Identity totals include only their assigned records. Correcting a record updates record statistics, not the meter's history.

## Manage archived data

Open **Charge Tally → Configure → Manage archived data**. Only charging points and identities whose configuration entries have been deleted are listed; disabling an entry is not enough. Review the record and revision counts, UTC time range, energy and known cost, then explicitly confirm permanent deletion.

Deleting a charging point removes its ledger records, revisions, samples and price history. Before deleting an identity with records, transfer all its current records, including voided records, to a receiving identity. Amounts stay unchanged and old revisions retain the original identity name for audit.

These operations cannot be undone in the interface and affect only the Charge Tally ledger, not Home Assistant native history, statistics or backups. Currency changes become available only when no charging points (including archived points) or accounting data remain. When restoring a retained ledger, choose its original currency first.

## Common questions

**Why is there no charging record?** Check that the selected sensors are available. For automatic detection, check that it is enabled and that power stays above the start level for long enough. Otherwise, start the record manually.

**Why is the cost pending?** Check the price sensor and its currency, or open the record to enter a known total. Missing data is not treated as zero cost.

**Why does Home Assistant ask to repair a charging point?** One of the energy meters created for that point may have been removed or changed. Open the repair notice and follow its instructions.

**How do I update safely?** Make a Home Assistant backup, update Charge Tally through HACS, and restart Home Assistant. Removing the integration does not clear its saved charging records.

Need help? [Open an issue](https://github.com/enecess/ha-charge-tally/issues) with your Home Assistant version, Charge Tally version and a description of the problem.

[MIT license](LICENSE)
