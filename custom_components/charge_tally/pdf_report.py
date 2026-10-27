"""Render frozen report snapshots without accessing Home Assistant or the ledger."""

import json
import re
import unicodedata
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from functools import lru_cache, partial
from io import BytesIO
from itertools import zip_longest
from pathlib import Path
from threading import RLock
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

from .reports import MAX_REPORT_RECORDS

_ROOT = Path(__file__).parent
_FONT = "ChargeTallySarasaRegular"
_LOCK = RLock()
_WIDTHS = (38, 88, 134, 64, 70, 137)
# The widths fill the A4 body with 32-point side margins.
_WIDTHS = tuple(width * (A4[0] - 64) / sum(_WIDTHS) for width in _WIDTHS)


class PdfReportError(ValueError):
    """A controlled renderer error safe for structured HTTP error responses."""

    def __init__(self, code: str, details: dict | None = None):
        super().__init__(code)
        self.code = code
        self.details = details


@lru_cache(maxsize=6)
def _catalog(language):
    return json.loads(
        (_ROOT / "report_locales" / f"{language}.json").read_text(encoding="utf-8")
    )


def _language(language):
    tag = language.replace("_", "-") if isinstance(language, str) else ""
    if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", tag):
        return "en"
    base = tag.split("-")[0].lower()
    return (
        "zh-Hans"
        if base == "zh"
        else base
        if base in {"de", "fr", "pl", "it"}
        else "en"
    )


def _font():
    if _FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont(_FONT, str(_ROOT / "fonts" / "SarasaUiSC-Regular.ttf"), validate=1)
        )
    return pdfmetrics.getFont(_FONT)


def _text(value, field, row):
    text = (
        unicodedata.normalize("NFC", str(value))
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\t", "    ")
    )
    missing = sorted(
        {
            ord(char)
            for char in text
            if char != "\n" and ord(char) not in _font().face.charToGlyph
        }
    )
    if missing:
        raise PdfReportError(
            "export_missing_glyph",
            {
                "field": field,
                "row": row,
                "codepoints": [f"U+{code:04X}" for code in missing],
            },
        )
    return escape(text).replace("\n", "<br/>")


def _rounded(value, digits):
    value = Decimal(value)
    if not value.is_finite():
        raise ValueError("Non-finite report value")
    with localcontext() as context:
        context.prec = (
            max(36, len(value.as_tuple().digits), value.adjusted() + 1) + digits + 3
        )
        rounded = value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return abs(rounded) if rounded.is_zero() else rounded


def _number(value, digits, language):
    text = format(_rounded(value, digits), f".{digits}f")
    if digits == 3:
        text = text.rstrip("0").rstrip(".")
    integer, dot, fraction = text.partition(".")
    negative = integer.startswith("-")
    integer = integer.lstrip("-")
    separator = {
        "en": ",",
        "zh-Hans": ",",
        "de": ".",
        "it": ".",
        "fr": "\u202f",
        "pl": "\u00a0",
    }[language]
    if len(integer) >= (5 if language == "pl" else 4):
        integer = separator.join(
            reversed(
                [integer[max(0, end - 3) : end] for end in range(len(integer), 0, -3)]
            )
        )
    return (
        ("-" if negative else "")
        + integer
        + (
            ("," if language in {"de", "fr", "pl", "it"} else ".") + fraction
            if dot
            else ""
        )
    )


def _timestamp(value, timezone):
    instant = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        ZoneInfo(timezone)
    )
    offset = instant.strftime("%z")
    return instant.strftime("%Y-%m-%d %H:%M:%S ") + offset[:3] + ":" + offset[3:]


def _has_rounding_difference(report):
    for key, flag, digits in (
        ("energy_kwh", "has_energy_data", 3),
        ("known_cost", "has_known_cost", 2),
    ):
        values = [_rounded(row[key], digits) for row in report["rows"] if row[flag]]
        if not values or not report["summary"][flag]:
            continue
        with localcontext() as context:
            context.prec = (
                max(
                    36,
                    *(
                        max(len(value.as_tuple().digits), value.adjusted() + 1)
                        for value in values
                    ),
                    len(Decimal(report["summary"][key]).as_tuple().digits),
                )
                + len(str(len(values)))
                + digits
                + 4
            )
            if sum(values, Decimal(0)) != _rounded(report["summary"][key], digits):
                return True
    return False


def _fragments(paragraph, width):
    """Bound physical rows so long content can continue with its record ordinal."""
    fragments = []
    pending = paragraph
    while pending is not None:
        if pending.wrap(width, 180)[1] <= 180:
            fragments.append(pending)
            break
        split = pending.split(width, 180)
        if len(split) != 2:
            raise PdfReportError("export_too_large")
        fragments.append(split[0])
        pending = split[1]
    return fragments


def render_pdf(report: dict, language: str) -> bytes:
    """Return a searchable A4 PDF; callers must execute this on a background thread."""
    if len(report["rows"]) > MAX_REPORT_RECORDS:
        raise PdfReportError("export_too_large")
    # ReportLab font registration and subset creation share process-global state.
    with _LOCK:
        _font()
        return _render(report, _language(language))


def _render(report, language):
    messages = _catalog(language)
    english = _catalog("en")

    def tr(key):
        return messages.get(key) or english[key]

    normal = ParagraphStyle(
        "body",
        fontName=_FONT,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#202a35"),
        splitLongWords=1,
        spaceAfter=0,
        allowWidows=1,
        allowOrphans=1,
    )
    amount = ParagraphStyle("amount", parent=normal, alignment=TA_RIGHT)
    heading = ParagraphStyle(
        "heading", parent=normal, fontSize=18, leading=24, spaceAfter=10
    )
    meta = ParagraphStyle("meta", parent=normal, fontSize=9, leading=13, spaceAfter=5)

    def paragraph(value, field="note", row=None, style=normal):
        return Paragraph(_text(value, field, row), style)

    def metric(item, key, flag, digits, unit):
        return (
            (_number(item[key], digits, language) + " " + unit)
            if item[flag]
            else tr("unknown")
        )

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        # Platypus adds six points of frame padding to these margins.
        leftMargin=26,
        rightMargin=26,
        topMargin=42,
        bottomMargin=42,
        title="Charge Tally - " + tr("title"),
        author="Charge Tally",
        pageCompression=1,
    )
    story = [paragraph("Charge Tally | " + tr("title"), "title", style=heading)]
    scope = report["scope"]
    for key in ("identity", "point"):
        story.append(
            paragraph(
                tr(key)
                + ": "
                + (
                    scope.get(key + "_name")
                    or tr("unknown" if scope.get(key + "_id") else "all")
                ),
                key,
                style=meta,
            )
        )
    if scope.get("calendar_period"):
        period = tr("calendar_" + scope["calendar_period"]) + (
            " " + scope["calendar"] if scope.get("calendar") else ""
        )
    else:
        period = (
            (
                _timestamp(scope["start"], report["timezone"])
                if scope.get("start")
                else tr("open_start")
            )
            + " / "
            + (
                _timestamp(scope["end"], report["timezone"])
                if scope.get("end")
                else tr("open_end")
            )
        )
    story.extend(
        [
            paragraph(tr("period") + ": " + period, "period", style=meta),
            paragraph(
                tr("currency")
                + ": "
                + report["currency"]
                + " | "
                + tr("timezone")
                + ": "
                + report["timezone"],
                "currency",
                style=meta,
            ),
            paragraph(
                tr("generated")
                + ": "
                + _timestamp(report["generated_at"], report["timezone"]),
                "generated",
                style=meta,
            ),
        ]
    )
    summary = report["summary"]
    cost_label = tr("cost") if summary["cost_complete"] else tr("known_subtotal")
    totals = [
        tr("energy")
        + ": "
        + metric(summary, "energy_kwh", "has_energy_data", 3, "kWh"),
        cost_label
        + ": "
        + metric(summary, "known_cost", "has_known_cost", 2, report["currency"]),
        tr("matched")
        + ": "
        + str(summary["matched_count"])
        + " | "
        + tr("active_count")
        + ": "
        + str(summary["active_count"]),
        tr("completed_count") + ": " + str(summary["completed_count"]),
    ]
    story.extend(paragraph(text, "cost", style=meta) for text in totals)
    story.append(Spacer(1, 8))
    header = [
        paragraph(tr(key), key)
        for key in ("ordinal", "names", "times", "energy", "cost", "status_note")
    ]
    table_rows = [header]
    cross_period = False
    quality = set()
    for ordinal, row in enumerate(report["rows"], 1):
        record = row["record"]
        timezone = record["timezone"]
        active = record["end"] is None
        times = (
            tr("start")
            + ": "
            + _timestamp(record["start"], timezone)
            + "\n"
            + tr("end")
            + ": "
            + (tr("active") if active else _timestamp(record["end"], timezone))
            + "\n"
            + timezone
        )
        # An active range_end is a query bound, never a completion timestamp.
        clipped = row["range_start"] != record["start"] or (
            row["range_end"] != record["end"]
        )
        if clipped:
            cross_period = True
            times += (
                "\n" + tr("coverage") + ": " + _timestamp(row["range_start"], timezone)
            )
            if row["range_end"]:
                times += " / " + _timestamp(row["range_end"], timezone)
        marks = set(row["quality"])
        quality.update(marks)
        if not row["cost_complete"]:
            quality.add("incomplete")
        status = [tr("active") if active else tr("completed")]
        status.extend(
            tr("quality_" + mark)
            for mark in sorted(marks - {"provisional"})
            if "quality_" + mark in english
        )
        if not row["cost_complete"]:
            status.append(tr("quality_incomplete"))
        if record.get("note"):
            status.append(tr("note") + ": " + record["note"])
        _text(row["identity_name"] or "", "identity", ordinal)
        _text(row["point_name"] or "", "point", ordinal)
        cells = [
            paragraph(
                (row["identity_name"] or tr("unknown"))
                + "\n"
                + (row["point_name"] or tr("unknown")),
                "identity",
                ordinal,
            ),
            paragraph(times, "times", ordinal),
            paragraph(
                metric(row, "energy_kwh", "has_energy_data", 3, "kWh"),
                "energy",
                ordinal,
                amount,
            ),
            paragraph(
                (tr("known_subtotal") + "\n" if not row["cost_complete"] else "")
                + metric(row, "known_cost", "has_known_cost", 2, report["currency"]),
                "cost",
                ordinal,
                amount,
            ),
            paragraph("\n".join(status), "note", ordinal),
        ]
        chunks = [
            _fragments(cell, _WIDTHS[index + 1] - 10)
            for index, cell in enumerate(cells)
        ]
        for index, pieces in enumerate(zip_longest(*chunks, fillvalue="")):
            label = str(ordinal) + ("\n(" + tr("continuation") + ")" if index else "")
            table_rows.append([paragraph(label, "ordinal", ordinal), *pieces])
    if report["rows"]:
        table = LongTable(
            table_rows,
            colWidths=_WIDTHS,
            repeatRows=1,
            hAlign="LEFT",
            splitByRow=1,
            longTableOptimize=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf2")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f7f9fb")],
                    ),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#8493a1")),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#dce2e8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(table)
    else:
        story.append(paragraph(tr("empty")))
    explanations = []
    if cross_period:
        explanations.append(tr("cross_period"))
    for mark in sorted(quality):
        key = "quality_" + mark
        if key in english:
            explanations.append(tr(key))
    if _has_rounding_difference(report):
        explanations.append(tr("rounding"))
    if explanations:
        story.append(Spacer(1, 10))
        story.extend(paragraph(text) for text in explanations)

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FONT, 8)
        canvas.setFillColor(colors.HexColor("#536171"))
        canvas.drawString(32, A4[1] - 27, "Charge Tally")
        canvas.drawRightString(A4[0] - 32, 24, tr("page").format(page=doc.page))
        canvas.restoreState()

    document.build(
        story,
        onFirstPage=on_page,
        onLaterPages=on_page,
        canvasmaker=partial(Canvas, initialFontName=_FONT),
    )
    return output.getvalue()
