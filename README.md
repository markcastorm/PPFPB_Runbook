# PPFPB Runbook - PPF Purple Book Data Pipeline

Automated extraction of 19 pension fund asset allocation data series from the annual PPF (Pension Protection Fund) Purple Book PDF.

Part of the SIMBA runbook family. Same architecture as TLIAD and RELPRCLVLINDX runbooks.

---

## Quick Start

```bash
# Run the full pipeline (download + extract + generate files)
python main.py

# Or step by step in Python:
from scraper import download
from extractor import extract
from file_generator import generate_files

pdf_path, year = download()
pdf_year, all_years = extract(pdf_path)
out_dir = generate_files(all_years)
```

---

## What It Does

1. **Downloads** the latest Purple Book PDF from https://www.ppf.co.uk/purple-book
2. **Extracts** 19 data series across 3 table sections from the PDF
3. **Updates** the master CSV with all year rows (overwrites restated historical values)
4. **Generates** timestamped DATA .xls, META .xls, and ZIP output files

---

## Pipeline Architecture

```
main.py
  -> orchestrator.py  (pipeline coordinator)
       -> scraper.py        (Step 1: download PDF)
       -> extractor.py      (Step 2: extract data from PDF)
       -> file_generator.py (Step 3: update master + generate output files)
```

All configuration lives in `config.py`. No hardcoded values in pipeline files.

---

## File Structure

```
PPFPB_Runbook/
|-- main.py                  Entry point
|-- orchestrator.py          Pipeline coordinator (scraper -> extractor -> file_generator)
|-- config.py                All configuration: paths, series definitions, scraper settings
|-- scraper.py               Downloads PDF from PPF website
|-- extractor.py             Extracts 19 series from PDF tables
|-- file_generator.py        Updates master CSV, generates DATA/META .xls + ZIP
|-- test_extraction.py       Test harness for validating extraction accuracy
|
|-- Master_Data/
|   |-- Master_PPFPB_DATA.csv   Ground truth + historical data (row 0=codes, row 1=descriptions, row 2+=data)
|
|-- downloads/               Timestamped PDF download folders
|   |-- 20260427_075625/
|       |-- PurpleBook_2025.pdf
|
|-- output/                  Timestamped output folders
|   |-- 20260427_075801/
|   |   |-- PPFPB_DATA_20260427_075801.xls
|   |   |-- PPFPB_META_20260427_075801.xls
|   |   |-- PPFPB_20260427_075801.zip
|   |-- latest/
|       |-- PPFPB_DATA_latest.xls
|       |-- PPFPB_META_latest.xls
|       |-- PPFPB_latest.zip
|
|-- debug/                   camelot debug CSVs (when DEBUG_CSV=True in extractor.py)
|
|-- Project_information/     Source PDFs, screenshots, original requirements
|   |-- Pension-Protection-Fund-Purple-Book-2025-accessible.pdf
|   |-- PPF-The-Purple-Book-2024.pdf
|   |-- PPF-The-Purple-Book-2023.pdf
|   |-- PPF_PurpleBook_2022.pdf
|   |-- PPF_PurpleBook_2021.pdf
|   |-- information.txt      Original project requirements
```

---

## The 19 Data Series

All defined in `config.SERIES_DEFINITIONS`. Order is absolute and never changes.

### Section 1: Asset Allocation (11 series)

Extracted from the "Weighted average asset allocation in total assets" table.

| # | Series | Code Suffix |
|---|--------|-------------|
| 0 | Equities | `LISTEDANDPRIVATEEQUITIES.ACTUALALLOCATION` |
| 1 | Bonds | `BONDS.ACTUALALLOCATION` |
| 2 | Other Investments | `ALTERNATIVES.ACTUALALLOCATION` |
| 3 | Property | `REALESTATE.ACTUALALLOCATION` |
| 4 | Cash and Deposits | `CASH.ACTUALALLOCATION` |
| 5 | Insurance policies | `INSURANCE.ACTUALALLOCATION` |
| 6 | Hedge Funds | `HEDGEFUNDS.ACTUALALLOCATION` |
| 7 | Diversified growth funds | `DEVIGROWFUND.ACTUALALLOCATION` |
| 8 | Absolute returns | `ABSRETURN.ACTUALALLOCATION` |
| 9 | Annuities | `ANNUITIES.ACTUALALLOCATION` |
| 10 | Miscellaneous | `OTHER.ACTUALALLOCATION` |

### Section 2: Bond Splits (3 series)

| # | Series | Code Suffix |
|---|--------|-------------|
| 11 | Government fixed interest | `BONDS.WEIGHTEDAVG.GOVERNMENTFIXEDINTEREST` |
| 12 | Corporate fixed interest | `BONDS.WEIGHTEDAVG.CORPORATEFIXEDINTEREST` |
| 13 | Index-linked | `BONDS.WEIGHTEDAVG.INDEXLINKED` |

### Section 3: Equity Splits (5 series)

| # | Series | Code Suffix |
|---|--------|-------------|
| 14 | UK quoted | `EQUITIES.WEIGHTEDAVG.UKQUOTED` |
| 15 | Overseas quoted | `EQUITIES.WEIGHTEDAVG.OVERSEASQUOTED` |
| 16 | Developed markets | `EQUITIES.WEIGHTEDAVG.DEVELOPEDMARKETS` |
| 17 | Emerging markets | `EQUITIES.WEIGHTEDAVG.EMERGINGMARKETS` |
| 18 | Unquoted/Private | `EQUITIES.WEIGHTEDAVG.UNQUOTEDPRIVATE` |

All codes are prefixed with `GBRPRIVATEPENSIONFUNDS.` and suffixed with `.A.1@PURPLEBOOK` or `.A@PURPLEBOOK`.

---

## Module Details

### config.py

Central configuration. Everything the pipeline needs is defined here.

| Setting | Value | Purpose |
|---------|-------|---------|
| `BASE_URL` | `https://www.ppf.co.uk/purple-book` | PPF website URL to scrape |
| `USE_DIRECT_REQUESTS` | `True` | `True` = try fast requests+BS4 first; `False` = skip straight to Selenium |
| `HEADLESS_MODE` | `True` | Run Chrome headless |
| `WAIT_TIMEOUT` | `30` | Selenium element wait timeout (seconds) |
| `JOB_NAME` | `PPFPB` | Prefix for output filenames |
| `NA_OUTPUT_VALUE` | `'NA'` | String written for missing/unavailable data |
| `SERIES_DEFINITIONS` | list of 19 tuples | `(code, description, section, canonical_label)` |
| `SERIES_CODES` | derived list | Just the codes, in order |
| `SERIES_DESCRIPTIONS` | derived list | Just the descriptions, in order |
| `*_ALIASES` dicts | 3 dicts | Map PDF label variants to canonical labels (not used by decoder ring, kept for reference) |

### scraper.py

Downloads the latest Purple Book PDF. Two strategies tried in order:

1. **Direct requests** (`_try_direct`) - Fast. Uses `requests` + `BeautifulSoup` to find the "Download The Purple Book YEAR" link in static HTML, then downloads the PDF directly. Works when the site serves the link without JavaScript.

2. **Selenium stealth** (`_try_selenium`) - Fallback. Uses `undetected_chromedriver` + `selenium_stealth` to render the page in headless Chrome, handle the cookie consent banner (`onetrust-accept-btn-handler`), find the download link/button, and download the PDF. Works even if the site requires JS or has bot protection.

**Key functions:**
- `download()` - Public entry point. Returns `(pdf_path, year)`.
- `_build_driver(download_dir)` - Creates stealth Chrome instance with CDP download behavior.
- `_handle_cookie_banner(driver)` - Clicks "Accept All Cookies" if the OneTrust banner appears.
- `_find_pdf_element(driver)` - Locates "Download The Purple Book YEAR" link or button.
- `_requests_download(url, dest_path, cookies)` - Streams PDF download. Rejects HTML responses and files < 50KB.
- `get_chrome_version()` - Reads Chrome version from Windows registry or Linux CLI.

**Dependencies:** `requests`, `beautifulsoup4`, `undetected-chromedriver`, `selenium-stealth`, `urllib3`

### extractor.py

The core extraction engine. Fully adaptive to any PDF year.

**Extraction strategy (the "decoder ring" approach):**

1. **Page detection** (`_find_section_pages`): Uses `pdfplumber` to scan page text. Matches keywords per section. Requires 4+ distinct year numbers on a page to avoid false positives on narrative pages.

2. **Table extraction** (`_camelot_tables`): Uses `camelot` stream flavor with `edge_tol=50`. Extracts raw tables from the detected page and the next page (tables can span two pages).

3. **Column identification** (`_identify_columns`): The "decoder ring". For each series, loads known values from the master CSV for prior years. Scans every table column to find which one matches the historical values within +/-0.15 tolerance. No header text parsing. No hardcoded column indices.

4. **Gap-fill** (`_fill_positional_gaps`): For new series with no prior reference years (e.g., DGF and AbsReturn introduced in 2023), infers their column position from neighboring identified anchor columns. Works in column-index space with min/max to handle non-monotonic PDF vs config ordering.

5. **All-year extraction** (`_extract_all_years`): Extracts data for EVERY year row in the table (not just the new year). This captures restated historical values from the latest source.

**Key functions:**
- `extract(pdf_path)` - Public entry point. Returns `(pdf_year, all_years)` where `all_years = {year: {series_code: value_or_'NA'}}`.
- `_parse_cell(raw)` - Converts camelot cell text to float. Handles: `'15.1%'`, `'-7. 2%'`, `'7\n.0%'`, `'n/a'`, `'--'`.
- `_load_master()` - Loads master CSV into `{year: {code: float_or_None}}`.
- `_normalize_rows(rows)` - Expands rows where camelot merged year + values into col 0.
- `_split_embedded_values(text)` - Handles camelot artefacts like `'7' + '.6%'` and strips annotation text like `'restated*'`.
- `_find_year_rows(rows)` - Finds `{year: row_index}`. Uses `re.match` (year at START of cell). Scans all columns.

**Adaptive target year:** The PDF year is detected from the filename (`re.search(r'(20\d{2})')`). The decoder ring uses only master data from years BEFORE the PDF year. This means you can run the extractor against any historical PDF and it works correctly.

**Page detection keywords:**
```python
'asset_allocation': ['cash and deposits', 'annuities']
'bond_splits':      ['bond split', 'index-linked']
'equity_splits':    ['uk quoted', 'overseas quoted']
```

**Dependencies:** `pdfplumber`, `camelot-py[cv]`, `pandas`

### file_generator.py

Updates the master CSV and generates output files.

**`update_master(all_years)`:**
- Accepts `{year: {series_code: value}}` for ALL extracted years
- Overwrites existing year rows with new values (captures restatements from newer PDFs)
- Inserts new year rows
- Preserves any years not in the extraction
- Sorts data rows by year
- Writes back to `Master_Data/Master_PPFPB_DATA.csv`

**`generate_files(all_years)`:**
1. Calls `update_master(all_years)`
2. Writes `PPFPB_DATA_<timestamp>.xls` - Full history from updated master. Row 0 = series codes, Row 1 = descriptions, Row 2+ = year data with numeric values as floats.
3. Writes `PPFPB_META_<timestamp>.xls` - Static metadata for all 19 series (18 columns: CODE, CODE_MNEMONIC, DESCRIPTION, FREQUENCY, etc.)
4. Creates ZIP containing DATA + META
5. Copies all three to `output/latest/`

**Dependencies:** `xlwt`, `pandas`

### orchestrator.py

Simple pipeline coordinator. Wires scraper -> extractor -> file_generator.

```python
pdf_path, scraper_year = download()
pdf_year, all_years = extract(pdf_path)
out_dir = generate_files(all_years)
```

Returns 0 on success, 1 on failure. All exceptions caught and logged.

### test_extraction.py

Standalone test harness for validating extraction accuracy against the master CSV.

```bash
# Test all 5 PDFs
PYTHONIOENCODING=utf-8 python test_extraction.py

# Test single year
PYTHONIOENCODING=utf-8 python test_extraction.py 2025

# Strip mode: remove target year from decoder master (simulates fresh run)
PYTHONIOENCODING=utf-8 python test_extraction.py 2023 strip
```

Output: `debug/test_results.txt`

---

## Master CSV Format

`Master_Data/Master_PPFPB_DATA.csv`

```
Row 0: ,<series_code_1>,<series_code_2>,...,<series_code_19>
Row 1: ,<description_1>,<description_2>,...,<description_19>
Row 2: 2006,61.1,28.3,10.6,...
Row 3: 2008,,,,,...,33.2,32.6,33.9,...
...
Row N: 2025,15.1,70.6,14.3,...
```

- Column 0 = year (or empty for header rows)
- Columns 1-19 = series values
- Missing values stored as `NA` (the string, not blank)
- Years sorted chronologically
- Updated in-place on every pipeline run (existing rows overwritten, new rows inserted)

---

## Output Files

Generated in `output/<timestamp>/` and copied to `output/latest/`.

| File | Content |
|------|---------|
| `PPFPB_DATA_<ts>.xls` | Full master data (all years, all 19 series) |
| `PPFPB_META_<ts>.xls` | Static metadata for 19 series (code, mnemonic, description, frequency, etc.) |
| `PPFPB_<ts>.zip` | ZIP containing DATA + META |

---

## Configuration Reference

### Changing scraper behavior

In `config.py`:
- `USE_DIRECT_REQUESTS = False` - Force Selenium (skip fast requests approach)
- `HEADLESS_MODE = False` - Show browser window (for debugging)
- `WAIT_TIMEOUT = 60` - Increase wait time for slow connections

### Changing NA handling

In `config.py`:
- `NA_OUTPUT_VALUE = 'NA'` - What to write for missing values in output

### Debug mode

In `extractor.py`:
- `DEBUG_CSV = True` - Saves raw camelot tables to `debug/` as CSV files for inspection

---

## Dependencies

```
requests
beautifulsoup4
pdfplumber
camelot-py[cv]
pandas
xlwt
undetected-chromedriver
selenium-stealth
urllib3
```

---

## Tested PDF Years

| PDF Year | Series Found | Accuracy vs Master |
|----------|-------------|-------------------|
| 2025 | 19/19 | 17/17 matched (100%) |
| 2024 | 19/19 | 16/17 matched (94%) - 1 structural diff (Corp FI combined vs split) |
| 2023 | 19/19 | 7/17 matched (41%) - restatement diffs, not code bugs |
| 2022 | 15/15 | 15/15 matched (100%) |
| 2021 | 15/15 | 15/15 matched (100%) |

All extractions are correct. The "mismatches" in 2023 and 2024 are data restatements and structural changes in the source PDF, not code bugs.

---

## Known Permanent Limitations

1. **2023 restatement diffs**: Master holds restated 2023 values from later PDFs. The 2023 PDF has original values. Diffs of 0.4-4.3pp are expected.

2. **2024 Corporate FI split**: 2024 PDF has combined Corporate FI = 35.0%. 2025 PDF split this into "Corporate public markets" (27.7%) + "Corporate private debt" (7.3%). Master stores 27.7.

3. **DGF and AbsReturn**: These categories didn't exist before 2023. Pre-2023 PDFs correctly return NA for them.

4. **Insurance and Hedge Funds**: The 2023 PDF reports n/a for these in the 2023 row. Correct behaviour.

---

## Environment

- **Development**: Windows 11, Python 3.11, Chrome required for Selenium
- **Production**: Docker Linux (same code, os.path.join handles path differences)
- Part of SIMBA runbook family at `D:\Projects\SIMBA-RUNBOOKS\`
