import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printerpro_check.validator import ValidatorConfig, validate_folder  # noqa: E402
from tests.pdf_factory import make_order_xml, make_pdf  # noqa: E402


def _codes(issues):
    return {i.code for i in issues}


def _fail_codes(issues):
    return {i.code for i in issues if i.severity == "fail"}


def test_compliant_pdf_has_no_failures(tmp_path):
    folder = tmp_path / "order_ok"
    folder.mkdir()
    make_pdf(folder / "poster.pdf", trim_w_mm=100, trim_h_mm=100, bleed_mm=3, dpi=300, embed_font=True)
    make_order_xml(folder / "order.xml", "Affiches", 100, 100, "poster.pdf")

    report = validate_folder(folder, ValidatorConfig())
    res = report.results[0]
    assert _fail_codes(res.issues) == set()
    assert res.fix_attempted is False


def test_wrong_trim_size_same_aspect_gets_fixed(tmp_path):
    folder = tmp_path / "order_wrongsize"
    folder.mkdir()
    make_pdf(folder / "card.pdf", trim_w_mm=80, trim_h_mm=80, bleed_mm=3, dpi=300, embed_font=True)
    make_order_xml(folder / "order.xml", "Ansichtkaarten", 100, 100, "card.pdf")

    report = validate_folder(folder, ValidatorConfig())
    res = report.results[0]
    assert "trim_size_mismatch" in _fail_codes(res.issues)
    assert res.fix_attempted is True
    assert "trim_size_mismatch" not in _fail_codes(res.remaining_issues)


def test_wrong_trim_size_mismatched_aspect_is_skipped_not_distorted(tmp_path):
    folder = tmp_path / "order_badaspect"
    folder.mkdir()
    make_pdf(folder / "card.pdf", trim_w_mm=80, trim_h_mm=80, bleed_mm=3, dpi=300, embed_font=True)
    make_order_xml(folder / "order.xml", "Ansichtkaarten", 50, 150, "card.pdf")

    report = validate_folder(folder, ValidatorConfig())
    res = report.results[0]
    assert "trim_size_mismatch" in _fail_codes(res.issues)
    assert res.fix_attempted is True
    assert len(res.fixes_skipped) >= 1
    # must still be flagged -- we never silently distort the artwork
    assert "trim_size_mismatch" in _fail_codes(res.remaining_issues)


def test_missing_bleed_gets_added(tmp_path):
    folder = tmp_path / "order_nobleed"
    folder.mkdir()
    make_pdf(folder / "flyer.pdf", trim_w_mm=100, trim_h_mm=100, bleed_mm=0, dpi=300, embed_font=True)
    make_order_xml(folder / "order.xml", "Flyers", 100, 100, "flyer.pdf")

    report = validate_folder(folder, ValidatorConfig())
    res = report.results[0]
    assert "bleed_missing" in _fail_codes(res.issues)
    assert res.fix_attempted is True
    assert "bleed_missing" not in _fail_codes(res.remaining_issues)


def test_low_dpi_is_flagged_but_never_upscaled(tmp_path):
    folder = tmp_path / "order_lowdpi"
    folder.mkdir()
    make_pdf(folder / "poster.pdf", trim_w_mm=100, trim_h_mm=100, bleed_mm=3, dpi=72, embed_font=True)
    make_order_xml(folder / "order.xml", "Affiches", 100, 100, "poster.pdf")

    report = validate_folder(folder, ValidatorConfig())
    res = report.results[0]
    assert "dpi_too_low" in _fail_codes(res.issues)
    # dpi is the only failure -> not in the auto-fixable set -> no fix attempted
    assert res.fix_attempted is False
    assert "dpi_too_low" in _fail_codes(res.remaining_issues)


def test_wrong_page_count_gets_fixed(tmp_path):
    folder = tmp_path / "order_pages"
    folder.mkdir()
    make_pdf(folder / "card.pdf", trim_w_mm=100, trim_h_mm=100, bleed_mm=3, dpi=300, embed_font=True, n_pages=1)
    make_order_xml(folder / "order.xml", "Ansichtkaarten", 100, 100, "card.pdf", sides=2)

    report = validate_folder(folder, ValidatorConfig())
    res = report.results[0]
    assert "page_count_mismatch" in _fail_codes(res.issues)
    assert res.fix_attempted is True
    assert "page_count_mismatch" not in _fail_codes(res.remaining_issues)


def test_non_embedded_font_is_flagged_and_not_auto_fixable_alone(tmp_path):
    folder = tmp_path / "order_font"
    folder.mkdir()
    make_pdf(folder / "poster.pdf", trim_w_mm=100, trim_h_mm=100, bleed_mm=3, dpi=300, embed_font=False)
    make_order_xml(folder / "order.xml", "Affiches", 100, 100, "poster.pdf")

    report = validate_folder(folder, ValidatorConfig())
    res = report.results[0]
    assert "fonts_not_embedded" in _fail_codes(res.issues)
    assert res.fix_attempted is False
    assert "fonts_not_embedded" in _fail_codes(res.remaining_issues)


def test_orphan_pdf_without_xml_still_gets_checked_via_filename(tmp_path):
    folder = tmp_path / "order_noxml"
    folder.mkdir()
    make_pdf(folder / "Visitekaartjes_ontwerp.pdf", trim_w_mm=85, trim_h_mm=55, bleed_mm=3, dpi=300, embed_font=True)

    report = validate_folder(folder, ValidatorConfig())
    assert len(report.results) == 1
    res = report.results[0]
    assert res.product_key == "visitekaartjes"
    assert any("Geen order-XML" in w for w in report.general_warnings)


def test_multi_item_xml_maps_each_pdf_by_filename_hint(tmp_path):
    folder = tmp_path / "order_multi"
    folder.mkdir()
    make_pdf(folder / "poster.pdf", trim_w_mm=100, trim_h_mm=100, bleed_mm=3, dpi=300, embed_font=True)
    make_pdf(folder / "card.pdf", trim_w_mm=85, trim_h_mm=55, bleed_mm=3, dpi=300, embed_font=True)
    xml_path = folder / "order.xml"
    xml_path.write_text(
        """<order>
  <ordernummer>PP-2</ordernummer>
  <item>
    <productnaam>Affiches</productnaam>
    <breedte>100</breedte><hoogte>100</hoogte>
    <zijdig>1</zijdig><aantal>5</aantal>
    <bestandsnaam>poster.pdf</bestandsnaam>
  </item>
  <item>
    <productnaam>Visitekaartjes</productnaam>
    <breedte>85</breedte><hoogte>55</hoogte>
    <zijdig>1</zijdig><aantal>500</aantal>
    <bestandsnaam>card.pdf</bestandsnaam>
  </item>
</order>
""",
        encoding="utf-8",
    )

    report = validate_folder(folder, ValidatorConfig())
    by_name = {r.pdf_path: r for r in report.results}
    assert by_name["poster.pdf"].product_key == "affiches"
    assert by_name["card.pdf"].product_key == "visitekaartjes"
    assert _fail_codes(by_name["poster.pdf"].issues) == set()
    assert _fail_codes(by_name["card.pdf"].issues) == set()


def test_batch_mode_processes_each_subfolder(tmp_path):
    from printerpro_check.cli import main as cli_main

    root = tmp_path / "batch_root"
    for name, size in [("orderA", 100), ("orderB", 60)]:
        folder = root / name
        folder.mkdir(parents=True)
        make_pdf(folder / "art.pdf", trim_w_mm=size, trim_h_mm=size, bleed_mm=3, dpi=300, embed_font=True)
        make_order_xml(folder / "order.xml", "Affiches", size, size, "art.pdf")

    rc = cli_main([str(root), "--batch"])
    assert rc == 0
    assert (root / "orderA" / "_printerpro_report.txt").exists()
    assert (root / "orderB" / "_printerpro_report.txt").exists()
