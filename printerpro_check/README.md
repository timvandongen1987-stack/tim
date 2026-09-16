# PrinterPro bestandscontrole

A Windows tool that checks the artwork PDF(s) in a printerpro.nl order folder
against the delivery specs from
[printerpro.nl/aanleverspecificaties](https://www.printerpro.nl/aanleverspecificaties),
and writes an automatically corrected PDF for the issues it can safely fix.

It reads the order XML in the same folder as the artwork, works out which
PDF belongs to which product, checks trim size, bleed, image DPI, embedded
fonts, page count and a few other things, and reports the rest (safety
margin, border width, rich-black value) as manual-review reminders because
they can't be checked reliably from the PDF alone.

## Important limitations -- read before relying on this

- **The specs in `specs.json` were only confirmed for 3 of the ~40 product
  categories** (Affiches, Ansichtkaarten, Balie displays) by pasting the
  text from the website, because this tool was built in a sandbox that
  could not reach printerpro.nl directly. All other categories currently
  *inherit* those same values (`"confirmed": false` in `specs.json`) since
  the three confirmed categories happened to be identical to each other.
  **Before trusting a result for another category, open
  `https://www.printerpro.nl/aanleverspecificaties/#<anchor>` for that
  product and correct `specs.json` if it differs** (e.g. books/brochures
  likely have binding-specific page-count rules that aren't modeled yet).
- **No real printerpro.nl order XML sample was available**, so
  `xml_order.py` is a generic parser that maps arbitrary XML tag names to
  the concepts it needs via alias lists in `xml_field_map.json`. It has
  been tested against hand-written sample XML, not a real export. Once you
  have a real order XML, open it, find the actual tag names, and put them
  **first** in each alias list in `xml_field_map.json` -- no code changes
  needed.
- Only what can be checked deterministically from the PDF is auto-checked:
  trim size, bleed, image DPI, embedded fonts, PDF version, page count,
  RGB vs CMYK image mode. Safety margin (content too close to the edge),
  border width, and the recommended rich-black CMYK value are reported as
  reminders only -- flagging them reliably would require interpreting
  design intent, which isn't safe to automate.
- Low image DPI is **never upscaled** -- it's reported so you can request a
  better file. Upscaling fabricates detail, it doesn't fix the problem.
- Adding missing bleed **rasterizes the affected page** (mirrors the edge
  pixels outward). This is a reasonable automatic fallback but loses
  vector sharpness and searchable text on that page -- for anything
  critical, add bleed by hand in the design file instead.
- If the ordered size and the PDF's trim size have a different aspect
  ratio, the tool **will not stretch the artwork** to fit -- it flags the
  mismatch for a human instead.

## How it works

```
order_folder/
  order.xml         <- parsed for product name, size, pages, sides, quantity
  artwork.pdf        <- checked against the matched product's specs
  artwork_corrected.pdf   <- written if anything auto-fixable was wrong
  _printerpro_report.txt  <- human-readable report
  _printerpro_report.json <- same report, machine-readable
```

1. `xml_order.py` parses the order XML into `OrderItem`s (product, size,
   pages, sides, quantity, which artwork file it belongs to).
2. `specs.py` matches each item's product name to a `ProductSpec` from
   `specs.json`.
3. `pdf_inspect.py` (PyMuPDF) reads the PDF's actual trim/bleed box sizes,
   page count, image DPI/colorspace, embedded fonts and PDF version.
4. `validator.py` compares the two and produces a list of issues.
5. `pdf_fix.py` fixes what it safely can (missing bleed, wrong trim size
   with matching aspect ratio, wrong page count) into a `*_corrected.pdf`,
   and the file is re-checked to confirm what's still outstanding.

## Running it

```bash
pip install -r requirements.txt

# GUI
python main.py

# CLI, single order folder
python -m printerpro_check.cli path\to\order_folder

# CLI, a folder containing many order subfolders
python -m printerpro_check.cli path\to\orders --batch

# report only, don't write corrected PDFs
python -m printerpro_check.cli path\to\order_folder --no-fix
```

## Building the Windows .exe

Run this **on Windows** (PyInstaller doesn't cross-compile reliably):

```
build\build_windows.bat
```

This creates `dist\PrinterProChecker.exe` -- a standalone executable that
bundles `specs.json` and `xml_field_map.json`, so it can be copied anywhere
without a Python install. (The build and packaging logic was verified in
this sandbox by freezing the same code with PyInstaller for Linux; only the
final Windows binary itself needs to be produced on a Windows machine.)

## Running the tests

```bash
pip install pytest
python -m pytest tests/ -v
```

The tests synthesize PDFs with PyMuPDF/Pillow (correct file, wrong trim
size, missing bleed, low DPI, wrong page count, non-embedded fonts, no
matching XML, multi-item orders, batch mode) rather than relying on real
printerpro.nl exports, for the same reason noted above.

## Files you'll likely want to edit as you learn more about the real system

- `specs.json` -- per-product delivery specs (confirm the other ~39
  categories against the website).
- `xml_field_map.json` -- tag-name aliases for the order XML parser (tighten
  once you have a real sample export).
