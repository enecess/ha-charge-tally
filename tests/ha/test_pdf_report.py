"""Validate actual searchable, localized report files with the shipped font."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from string import Formatter

import pytest
from pypdf import PdfReader

from custom_components.charge_tally import pdf_report

COMPONENT = Path(__file__).parents[2] / "custom_components" / "charge_tally"
LANGUAGES = ("en", "zh-Hans", "de", "fr", "pl", "it")


def report_fixture():
    return {
        "schema_version": 1,
        "generated_at": "2026-10-27T01:02:03+00:00",
        "data_version": 7,
        "currency": "CNY",
        "timezone": "Asia/Shanghai",
        "scope": {
            "calendar_period": "monthly",
            "calendar": "2026-10",
            "start": None,
            "end": None,
            "point_id": None,
            "identity_id": None,
            "point_name": None,
            "identity_name": None,
        },
        "summary": {
            "energy_kwh": "1.2345",
            "known_cost": "1.005",
            "cost_complete": True,
            "has_energy_data": True,
            "has_known_cost": True,
            "active_count": 0,
            "completed_count": 1,
            "matched_count": 1,
            "quality": [],
            "bucket_period": "day",
            "buckets": [],
        },
        "rows": [
            {
                "record": {
                    "id": "r1",
                    "point_id": "p1",
                    "identity_id": "i1",
                    "start": "2026-10-01T01:00:00+00:00",
                    "end": "2026-10-01T02:00:00+00:00",
                    "timezone": "Asia/Shanghai",
                    "status": "completed",
                    "quality": ["missing_energy"],
                    "note": "Hello 中文",
                },
                "range_start": "2026-10-01T01:00:00+00:00",
                "range_end": "2026-10-01T02:00:00+00:00",
                "energy_kwh": "1.2345",
                "known_cost": "1.005",
                "cost_complete": True,
                "has_energy_data": True,
                "has_known_cost": True,
                "quality": [],
                "point_name": "Garage",
                "identity_name": "Zażółć gęślą jaźń",
            }
        ],
    }


def read_pdf(report=None, language="en"):
    data = pdf_report.render_pdf(report or report_fixture(), language)
    assert data.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(data))
    return reader, "\n".join(page.extract_text() for page in reader.pages)


def compact(text):
    return re.sub(r"\s+", "", text)


@pytest.mark.parametrize(
    "language,reason",
    [
        ("en", "Ended after the source remained unavailable for 5 minutes"),
        ("zh-Hans", "设备持续离线5分钟，记账结束时间为离线起点"),
    ],
)
def test_pdf_explains_source_unavailable_end(language, reason):
    report = report_fixture()
    report["rows"][0]["record"]["end_reason"] = "source_unavailable"
    _, text = read_pdf(report, language)
    assert compact(reason) in compact(text)


@pytest.mark.parametrize(
    "language,energy,cost,page",
    [
        ("en", "Period energy", "Period cost", "Page 1"),
        ("zh-Hans", "本期用量", "本期费用", "第 1 页"),
        ("de", "Verbrauch im Zeitraum", "Kosten im Zeitraum", "Seite 1"),
        ("fr", "Énergie de la période", "Coût de la période", "Page 1"),
        ("pl", "Energia w okresie", "Koszt w okresie", "Strona 1"),
        ("it", "Energia del periodo", "Costo del periodo", "Pagina 1"),
    ],
)
def test_pdf_six_languages_has_extractable_text(language, energy, cost, page):
    reader, text = read_pdf(language=language)
    for expected in ("Zażółć gęślą jaźń", "Hello 中文", energy, cost, page, "CNY"):
        assert compact(expected) in compact(text)
    fonts = []
    for pdf_page in reader.pages:
        assert float(pdf_page.mediabox.width) == pytest.approx(595.276, abs=0.01)
        assert float(pdf_page.mediabox.height) == pytest.approx(841.89, abs=0.01)
        for font in pdf_page["/Resources"]["/Font"].values():
            font = font.get_object()
            if "/FontDescriptor" in font:
                assert "/FontFile2" in font["/FontDescriptor"]
                fonts.append(str(font["/BaseFont"]))
    assert fonts and all("Sarasa-UI-SC-Regular" in name for name in fonts)
    assert "Bold" not in str(reader.trailer)


def column_text(reader, left, right):
    pieces = []
    for page in reader.pages:

        def collect(text, cm, tm, font, size):
            if left <= cm[4] + tm[4] < right and cm[5] + tm[5] > 42:
                pieces.append(text)

        page.extract_text(visitor_text=collect)
    return compact("".join(pieces))


def test_pdf_long_notes_repeat_headers_and_preserve_text():
    report = report_fixture()
    row = report["rows"][0]
    long_name = "LongUnspacedName" * 30
    note = "备注" * 995 + "FINALNOTE!"
    assert len(note) == 2000
    row["identity_name"] = long_name
    row["record"]["note"] = note
    report["rows"] = [deepcopy(row) for _ in range(101)]
    for ordinal, item in enumerate(report["rows"], 1):
        item["record"]["id"] = f"r{ordinal}"
        if ordinal != 1:
            item["record"]["note"] = f"Row {ordinal} Zażółć gęślą jaźń 中文"
            item["identity_name"] = "Driver"
    report["summary"]["matched_count"] = 101
    reader, text = read_pdf(report)
    assert len(reader.pages) > 3
    notes = column_text(reader, 410, 575).replace("Status/notes", "")
    names = column_text(reader, 60, 150).replace("Identity/chargingpoint", "")
    assert compact(note) in notes
    assert compact(long_name) in names
    for ordinal in range(2, 102):
        assert compact(f"Row {ordinal} Zażółć gęślą jaźń 中文") in compact(text)
    for number, page in enumerate(reader.pages, 1):
        extracted = compact(page.extract_text())
        assert "Periodenergy" in extracted
        assert f"Page{number}" in extracted
    assert "1(cont.)" in compact(text)
    ordinals = []
    for page in reader.pages:
        page.extract_text(
            visitor_text=lambda text, cm, tm, font, size: (
                ordinals.append(text) if 32 <= cm[4] + tm[4] < 65 else None
            )
        )
    assert "101\n" in ordinals
    assert any("(cont.)" in text for text in ordinals)


def test_pdf_user_markup_is_literal_and_unicode_is_nfc():
    report = report_fixture()
    report["rows"][0]["record"]["note"] = "<b>&</b> Cafe\u0301\nNext line"
    report["scope"]["identity_name"] = "<img src=x>"
    _, text = read_pdf(report)
    assert "<b>&</b> Café" in text
    assert "<img src=x>" in text
    assert "Next line" in text


def test_pdf_note_preserves_significant_whitespace_without_compaction():
    report = report_fixture()
    report["rows"][0]["record"]["note"] = "Left  Middle\tRight\n  Indented end  "
    _, text = read_pdf(report)
    # A tab occupies four spaces; extraction may encode protected spaces as NBSP.
    text = text.replace("\u00a0", " ")
    assert "Left  Middle    Right\n  Indented end  \n" in text


@pytest.mark.parametrize("target", ["summary", "row"])
@pytest.mark.parametrize(
    "value",
    ["1e100000", "-1e100000", "1." + "2" * 1024],
    ids=["compact-positive", "compact-negative", "coefficient-precision"],
)
def test_pdf_rejects_numeric_work_before_formatting_or_layout(
    monkeypatch, target, value
):
    report = report_fixture()
    item = report["summary"] if target == "summary" else report["rows"][0]
    item["known_cost"] = value
    before = deepcopy(report)

    def no_layout(*args):
        pytest.fail("Numeric work must be rejected before formatting or layout")

    monkeypatch.setattr(pdf_report, "_render", no_layout)
    with pytest.raises(pdf_report.PdfReportError, match="^export_too_large$"):
        pdf_report.render_pdf(report, "en")
    assert report == before


def test_pdf_rejects_cumulative_numeric_work_before_layout(monkeypatch):
    report = report_fixture()
    report["rows"][0].update(known_cost="1e100", energy_kwh="1e100")
    report["rows"] *= 5000

    def no_layout(*args):
        pytest.fail("Cumulative numeric work must be rejected before layout")

    monkeypatch.setattr(pdf_report, "_render", no_layout)
    with pytest.raises(pdf_report.PdfReportError, match="^export_too_large$"):
        pdf_report.render_pdf(report, "en")


@pytest.mark.parametrize(
    "language,positive,negative,energy",
    [
        ("en", "1.01", "-1.01", "1.235"),
        ("zh_CN", "1.01", "-1.01", "1.235"),
        ("de-AT", "1,01", "-1,01", "1,235"),
        ("fr-CA", "1,01", "-1,01", "1,235"),
        ("pl-PL", "1,01", "-1,01", "1,235"),
        ("it_IT", "1,01", "-1,01", "1,235"),
    ],
)
def test_pdf_decimal_half_up_matches_card(language, positive, negative, energy):
    report = report_fixture()
    report["rows"][0]["known_cost"] = "-1.005"
    report["rows"][0]["energy_kwh"] = "-1.2345"
    _, text = read_pdf(report, language)
    for expected in (positive, negative, energy, "-" + energy):
        assert expected in compact(text)


def test_pdf_unknown_zero_period_quality_and_active_query_bound():
    report = report_fixture()
    row = report["rows"][0]
    _, text = read_pdf(report)
    assert "Missing energy" not in text
    row["record"]["status"] = "active"
    row["record"]["end"] = None
    row["range_end"] = "2026-11-01T00:00:00+00:00"
    row["quality"] = ["provisional", "missing_price"]
    row["cost_complete"] = False
    row["has_known_cost"] = False
    row["has_energy_data"] = False
    report["summary"].update(
        has_known_cost=False,
        has_energy_data=False,
        cost_complete=False,
        quality=row["quality"],
    )
    _, text = read_pdf(report)
    assert "Active / provisional" in text
    assert "Unknown" in text
    assert "Missing price" in text
    assert "End: Active / provisional" in text
    assert "Periodcoverage" in compact(text)
    assert "2026-11-01" in text
    assert "Known subtotal" in text
    row.update(
        has_known_cost=True, known_cost="0", has_energy_data=True, energy_kwh="0"
    )
    _, text = read_pdf(report)
    assert "0.00" in text
    assert "0 kWh" in text


def test_pdf_cross_period_timezone_and_conditional_rounding_explanations():
    report = report_fixture()
    row = report["rows"][0]
    row["record"]["timezone"] = "Asia/Kolkata"
    row["range_start"] = "2026-10-01T01:30:00+00:00"
    row["energy_kwh"] = "1.2344"
    row["known_cost"] = "1.004"
    report["summary"].update(energy_kwh="2.4688", known_cost="2.008")
    report["rows"].append(deepcopy(row))
    _, text = read_pdf(report)
    assert "2026-10-01 09:00" in text
    assert "2026-10-0110:00" in compact(text)
    assert "2026-10-0109:30" in compact(text)
    assert "Asia/Shanghai" in text and "+08:00" in text
    assert "Asia/Kolkata" not in text and "+05:30" not in text
    assert "Period coverage" in text
    assert "Rounding" in text
    report = report_fixture()
    report["rows"][0].update(energy_kwh="1", known_cost="1")
    report["summary"].update(energy_kwh="1", known_cost="1")
    _, text = read_pdf(report)
    assert "Rounding" not in text and "Period coverage" not in text


def test_pdf_extreme_finite_values_empty_report_and_fallback():
    report = report_fixture()
    huge = "12345678901234567890123456789012345678901234567890.005"
    report["rows"][0]["known_cost"] = huge
    report["summary"]["known_cost"] = huge
    _, text = read_pdf(report, "xx-Unknown")
    assert "12345678901234567890123456789012345678901234567890.01" in compact(
        text
    ).replace(",", "")
    assert "Charging report" in text
    report["rows"] = []
    report["summary"].update(
        matched_count=0, completed_count=0, has_known_cost=False, has_energy_data=False
    )
    _, text = read_pdf(report)
    assert "No records in this range" in text
    assert "Unknown" in text


@pytest.mark.parametrize(
    "field,setup,row",
    [
        ("note", lambda r: r["rows"][0]["record"].update(note="Private 😀"), 1),
        ("identity", lambda r: r["rows"][0].update(identity_name="Secret 😀"), 1),
        ("point", lambda r: r["scope"].update(point_name="Secret 😀"), None),
        ("point", lambda r: r["rows"][0].update(point_name="Secret 😀"), 1),
    ],
)
def test_pdf_missing_glyph_is_actionable_without_private_text(field, setup, row):
    report = report_fixture()
    setup(report)
    with pytest.raises(pdf_report.PdfReportError) as caught:
        read_pdf(report)
    error = caught.value
    assert isinstance(error, ValueError)
    assert str(error) == error.code == "export_missing_glyph"
    assert error.details == {"field": field, "row": row, "codepoints": ["U+1F600"]}
    assert "Private" not in str(error.details) and "Secret" not in str(error.details)


def test_pdf_resource_limit_is_explicit():
    report = report_fixture()
    report["rows"] *= 5001
    with pytest.raises(ValueError, match="^export_too_large$"):
        read_pdf(report)


def test_pdf_catalogs_keys_placeholders_and_actual_font_are_complete():
    catalogs = [
        json.loads((COMPONENT / "report_locales" / f"{tag}.json").read_text())
        for tag in LANGUAGES
    ]
    for catalog in catalogs:
        assert catalog.keys() == catalogs[0].keys()
        for key, value in catalog.items():
            assert value

            def fields(text):
                return {
                    name
                    for _, name, _, _ in Formatter().parse(text)
                    if name is not None
                }

            assert fields(value) == fields(catalogs[0][key])
        report = report_fixture()
        report["rows"][0]["record"]["note"] = "\n".join(catalog.values())
        read_pdf(report)


def test_pdf_parallel_calls_keep_language_and_snapshot_isolated():
    report = report_fixture()
    before = deepcopy(report)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(
            executor.map(lambda tag: read_pdf(report, tag)[1], ("en", "pl", "zh-Hans"))
        )
    assert "Charging report" in results[0]
    assert "Raport ładowania" in results[1]
    assert "充电统计报表" in results[2]
    assert report == before


def test_pdf_unresolved_selected_filter_is_unknown_not_all():
    report = report_fixture()
    report["scope"].update(point_id="unresolved", point_name=None)
    report["rows"] = []
    report["summary"].update(
        matched_count=0, completed_count=0, has_energy_data=False, has_known_cost=False
    )
    _, text = read_pdf(report)
    assert "Charging point: Unknown" in text
    assert "Identity: All" in text
