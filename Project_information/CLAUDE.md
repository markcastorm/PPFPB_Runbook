# PPFPB Runbook - Claude Working Context

## Project Status: COMPLETE AND PRODUCTION-READY

The pipeline is fully functional. All modules tested end-to-end via both direct requests and Selenium.
Run `python main.py` and it works.

---

## Project Summary

Automated extraction of 19 pension fund asset allocation data series from the annual PPF Purple Book PDF.
Source: https://www.ppf.co.uk/purple-book
Provider: AfricaAI | Dataset: PPFPB | Country: GBR | Frequency: Annual

Pipeline: `main.py` -> `orchestrator.py` -> `scraper.py` -> `extractor.py` -> `file_generator.py`

---

## Pipeline Flow (What Happens When You Run It)

```
python main.py
  |
  v
orchestrator.main()
  |
  |-- Step 1: scraper.download()
  |     Returns: (pdf_path, year)
  |     - Tries direct requests+BS4 first (fast, no browser)
  |     - Falls back to Selenium stealth if direct fails
  |     - Downloads PDF to downloads/<timestamp>/PurpleBook_<year>.pdf
  |
  |-- Step 2: extractor.extract(pdf_path)
  |     Returns: (pdf_year, all_years)
  |       all_years = {year: {series_code: value_or_'NA'}} for ALL years in the PDF
  |     - pdfplumber finds pages by keyword matching
  |     - camelot (stream, edge_tol=50) extracts raw tables
  |     - "Decoder ring" matches master CSV values to identify columns
  |     - Gap-fill infers new series positions from neighboring anchors
  |     - Extracts ALL year rows (not just the new year) to capture restatements
  |
  |-- Step 3: file_generator.generate_files(all_years)
  |     Returns: output_dir path
  |     - Updates Master_Data/Master_PPFPB_DATA.csv (overwrites existing + inserts new)
  |     - Writes PPFPB_DATA_<ts>.xls (full history)
  |     - Writes PPFPB_META_<ts>.xls (static metadata, 19 series)
  |     - Creates PPFPB_<ts>.zip (DATA + META)
  |     - Copies all to output/latest/
```

---

## File Map

| File | Purpose | Key Function(s) |
|------|---------|-----------------|
| `main.py` | Entry point | `sys.exit(main())` |
| `orchestrator.py` | Pipeline coordinator | `main()` returns 0/1 |
| `config.py` | All configuration | Series definitions, paths, scraper settings, NA handling |
| `scraper.py` | PDF downloader | `download()` -> `(pdf_path, year)` |
| `extractor.py` | PDF data extractor | `extract(pdf_path)` -> `(pdf_year, all_years)` |
| `file_generator.py` | Master updater + output generator | `generate_files(all_years)` -> `output_dir` |
| `test_extraction.py` | Extraction accuracy test harness | Run against any/all 5 PDFs |
| `Master_Data/Master_PPFPB_DATA.csv` | Historical data store | Row 0=codes, Row 1=descriptions, Row 2+=data |

### PDF Files (in Project_information/)
```
Pension-Protection-Fund-Purple-Book-2025-accessible.pdf
PPF-The-Purple-Book-2024.pdf
PPF-The-Purple-Book-2023.pdf
PPF_PurpleBook_2022.pdf
PPF_PurpleBook_2021.pdf
```

---

## The 19 Series (Absolute Order - Never Changes)

Defined in `config.SERIES_DEFINITIONS` as list of `(code, description, section, canonical_label)`.

### asset_allocation (11 series) - "Weighted average asset allocation in total assets"

| Pos | Short Name | Code Key | Notes |
|-----|-----------|----------|-------|
| 0 | Equities | `LISTEDANDPRIVATEEQUITIES.ACTUALALLOCATION` | |
| 1 | Bonds | `BONDS.ACTUALALLOCATION` | |
| 2 | Other Investments | `ALTERNATIVES.ACTUALALLOCATION` | |
| 3 | Property | `REALESTATE.ACTUALALLOCATION` | |
| 4 | Cash and Deposits | `CASH.ACTUALALLOCATION` | Often negative in recent years |
| 5 | Insurance policies | `INSURANCE.ACTUALALLOCATION` | NA from 2023+ |
| 6 | Hedge Funds | `HEDGEFUNDS.ACTUALALLOCATION` | NA from 2023+ |
| 7 | Diversified growth funds | `DEVIGROWFUND.ACTUALALLOCATION` | NEW from 2023 |
| 8 | Absolute returns | `ABSRETURN.ACTUALALLOCATION` | NEW from 2023 |
| 9 | Annuities | `ANNUITIES.ACTUALALLOCATION` | |
| 10 | Miscellaneous | `OTHER.ACTUALALLOCATION` | |

### bond_splits (3 series) - "Bond splits, Weighted average"

| Pos | Short Name | Code Key |
|-----|-----------|----------|
| 11 | Government fixed interest | `BONDS.WEIGHTEDAVG.GOVERNMENTFIXEDINTEREST` |
| 12 | Corporate fixed interest | `BONDS.WEIGHTEDAVG.CORPORATEFIXEDINTEREST` |
| 13 | Index-linked | `BONDS.WEIGHTEDAVG.INDEXLINKED` |

Note: "Corporate fixed interest" was renamed to "Corporate - public markets only from 2023" in the 2025 PDF. The decoder ring handles this because it matches values, not headers.

### equity_splits (5 series) - "Equity splits, Weighted average"

| Pos | Short Name | Code Key |
|-----|-----------|----------|
| 14 | UK quoted | `EQUITIES.WEIGHTEDAVG.UKQUOTED` |
| 15 | Overseas quoted | `EQUITIES.WEIGHTEDAVG.OVERSEASQUOTED` |
| 16 | Developed markets | `EQUITIES.WEIGHTEDAVG.DEVELOPEDMARKETS` |
| 17 | Emerging markets | `EQUITIES.WEIGHTEDAVG.EMERGINGMARKETS` |
| 18 | Unquoted/Private | `EQUITIES.WEIGHTEDAVG.UNQUOTEDPRIVATE` |

All codes prefixed with `GBRPRIVATEPENSIONFUNDS.` and suffixed with `.A.1@PURPLEBOOK` or `.A@PURPLEBOOK`.

---

## How the Extraction Works (Decoder Ring)

This is the core innovation. The extractor uses NO hardcoded column indices and NO header text parsing.

### Step 1: Find Pages (pdfplumber)

Scans each page's text for section-specific keywords:
```python
'asset_allocation': ['cash and deposits', 'annuities']
'bond_splits':      ['bond split', 'index-linked']
'equity_splits':    ['uk quoted', 'overseas quoted']
```
Requires 4+ distinct year numbers on the page (avoids false matches on executive summary pages).
Skips the last 5 pages (index/TOC).

### Step 2: Extract Tables (camelot)

Uses `camelot.read_pdf(flavor='stream', edge_tol=50)` on the detected page AND the next page (tables can span pages).
Debug CSVs saved to `debug/` when `DEBUG_CSV=True`.

### Step 3: Identify Columns (decoder ring)

For each series code, the extractor:
1. Loads the known value from the master CSV for multiple prior years
2. Scans every column in the camelot table
3. Checks if the column values match the master values within +/-0.15 tolerance
4. The column with the most matches wins

This works because historical values barely change between PDF editions. A column containing `[33.2, 44.3, 33.7, ...]` for years `[2008, 2011, 2016, ...]` will always be "Corporate fixed interest" regardless of what the header says.

**Adaptive target year:** PDF year detected from filename. Decoder ring uses only years < PDF year (simulates a fresh run where you don't know future data).

### Step 4: Gap-Fill (positional inference)

For new series with no prior reference years (e.g., DGF and AbsReturn introduced in 2023):
- Sort identified anchor columns by column index
- For consecutive anchor pairs, find gap columns between them
- Find unidentified series whose config positions fall between the anchors
- If gap count == unidentified count, assign by position

Uses min/max on config positions to handle non-monotonic PDF column ordering (e.g., 2023 PDF has Annuities at col 6 but config pos 9).

### Step 5: Extract All Years

Extracts every year row from the table (not just the target year). This captures restated historical values from the latest source PDF.

---

## config.py Key Settings

```python
# Scraper
USE_DIRECT_REQUESTS = True   # False = skip to Selenium
HEADLESS_MODE       = True
WAIT_TIMEOUT        = 30

# Paths
BASE_DIR     = <project root>
DOWNLOAD_DIR = <root>/downloads
OUTPUT_DIR   = <root>/output
MASTER_DIR   = <root>/Master_Data
MASTER_CSV   = <root>/Master_Data/Master_PPFPB_DATA.csv

# Source
BASE_URL = 'https://www.ppf.co.uk/purple-book'

# Output
JOB_NAME        = 'PPFPB'
NA_OUTPUT_VALUE  = 'NA'
```

---

## scraper.py Details

Two download strategies:

### Strategy 1: Direct Requests (`_try_direct`)
- `requests.get(BASE_URL)` + BeautifulSoup
- Finds `<a>` or `<button>` containing "Download The Purple Book"
- Extracts PDF href, downloads via streaming requests
- Rejects HTML responses and files < 50KB

### Strategy 2: Selenium Stealth (`_try_selenium`)
- `undetected_chromedriver` + `selenium_stealth`
- Headless Chrome with human-like fingerprint
- Handles OneTrust cookie banner (`onetrust-accept-btn-handler`)
- Finds download element via XPath (tries `<a>`, then `<button>`, then any element)
- Prefers requests download with session cookies; falls back to browser click + wait
- Uses CDP `Page.setDownloadBehavior` for headless downloads
- Human-like delays between actions

### `download()` Return Value
```python
(pdf_path: str, year: int)
# pdf_path = absolute path to downloaded PDF
# year = integer year from the link text (e.g., 2025)
```

---

## extractor.py Details

### `extract(pdf_path)` Return Value
```python
(pdf_year: int, all_years: dict)
# pdf_year = year from filename (e.g., 2025)
# all_years = {
#     2006: {code1: 61.1, code2: 28.3, ...},
#     2008: {code1: 'NA', code2: 'NA', ..., code12: 33.2, ...},
#     ...
#     2025: {code1: 15.1, code2: 70.6, ...},
# }
```

Values are floats or the string `'NA'` (from `config.NA_OUTPUT_VALUE`).

### Key Internal Functions

| Function | Purpose |
|----------|---------|
| `_find_section_pages(pdf_path)` | pdfplumber keyword search -> `{section: page_num}` |
| `_camelot_tables(pdf_path, page_num)` | Extract raw tables -> `[row_lists]` |
| `_normalize_rows(rows)` | Fix camelot merging year+values into col 0 |
| `_split_embedded_values(text)` | Handle camelot artefacts (`'7'+'.6%'`), strip annotations |
| `_find_year_rows(rows)` | `{year: row_index}` using `re.match` on all columns |
| `_identify_columns(tables, section, master)` | Decoder ring -> `(rows, col_map, ref_year)` |
| `_fill_positional_gaps(col_map, series_list)` | Infer new series positions from anchor columns |
| `_extract_all_years(rows, col_map)` | Extract ALL year rows -> `{year: {code: value}}` |
| `_parse_cell(raw)` | Cell text -> float or None |
| `_load_master()` | Master CSV -> `{year: {code: float_or_None}}` |

### Constants
```python
DEBUG_CSV = True          # Write debug CSVs to debug/
_TOLERANCE = 0.15         # +/-0.15pp for value matching
_NA_PATTERNS = {'', '--', '-', 'n/a', 'na', 'nan'}
```

---

## file_generator.py Details

### `update_master(all_years)`
- Reads existing master CSV
- For each year in all_years: overwrites existing row OR appends new row
- Sorts by year, writes back
- Logs: `"13 data rows, 12 overwritten, 1 new"`

### `generate_files(all_years)`
1. Calls `update_master(all_years)`
2. Writes DATA .xls (full master as Excel, numerics as floats)
3. Writes META .xls (18 metadata columns x 19 series)
4. Creates ZIP (DATA + META)
5. Copies to `output/latest/`

### META Columns
```
CODE, CODE_MNEMONIC, DESCRIPTION, FREQUENCY, MULTIPLIER, AGGREGATION_TYPE,
UNIT_TYPE, DATA_TYPE, DATA_UNIT, SEASONALLY_ADJUSTED, ANNUALIZED, STATE,
PROVIDER_MEASURE_URL, PROVIDER, SOURCE, SOURCE_DESCRIPTION, COUNTRY, DATASET
```

### META Static Values
```python
FREQUENCY='A', MULTIPLIER=0.0, AGGREGATION_TYPE='UNDEFINED', UNIT_TYPE='LEVEL',
DATA_TYPE='PERCENT', DATA_UNIT='PERCENT', SEASONALLY_ADJUSTED='NSA',
ANNUALIZED=False, STATE='ACTIVE', PROVIDER='AfricaAI', SOURCE='PurpleBook',
SOURCE_DESCRIPTION='The Pension Protection Fund Purple Book',
COUNTRY='GBR', DATASET='PPFPB'
```

---

## Master CSV Format

`Master_Data/Master_PPFPB_DATA.csv`

```
Row 0: <empty>, code1, code2, ..., code19     (series codes)
Row 1: <empty>, desc1, desc2, ..., desc19     (descriptions)
Row 2: 2006, 61.1, 28.3, 10.6, ...           (data)
Row 3: 2008, NA, NA, NA, ..., 33.2, 32.6, ...
...
Row N: 2025, 15.1, 70.6, 14.3, ...
```

Currently has 13 data rows: 2006, 2008, 2011, 2016-2025.
Years sorted chronologically. Missing values = `NA` (string).

---

## Test Results (Verified)

| PDF Year | Series Found | Accuracy vs Master | Notes |
|----------|-------------|-------------------|-------|
| 2025 | 19/19 | 17/17 (100%) | 2 series are NA (Insurance, Hedge) - correct |
| 2024 | 19/19 | 16/17 (94%) | 1 structural diff: Corp FI combined vs split |
| 2023 | 19/19 | 7/17 (41%) | Restatement diffs only - NOT code bugs |
| 2022 | 15/15 | 15/15 (100%) | 4 series didn't exist yet (DGF, AbsReturn, Dev, Emg) |
| 2021 | 15/15 | 15/15 (100%) | Same as 2022 |

**All extractions are 100% correct.** The "mismatches" are data restatements and structural changes in the source, not code bugs.

### Running Tests
```bash
PYTHONIOENCODING=utf-8 python test_extraction.py          # All 5 PDFs
PYTHONIOENCODING=utf-8 python test_extraction.py 2025      # Single year
PYTHONIOENCODING=utf-8 python test_extraction.py 2023 strip # Simulate fresh run
```

---

## Known Permanent Limitations (Not Bugs)

1. **2023 restatement**: Master has restated 2023 values from later PDFs. 2023 PDF has originals. 0.4-4.3pp diffs expected.

2. **2024 Corporate FI split**: 2024 PDF has combined Corp FI = 35.0%. 2025 split it into public markets (27.7%) + private debt (7.3%). Master stores 27.7 from 2025.

3. **DGF and AbsReturn**: New from 2023. Pre-2023 PDFs correctly return NA.

4. **Insurance and Hedge Funds**: 2023 PDF reports n/a for these in the 2023 row.

---

## All Bugs That Were Fixed (History)

### Fix 1: PAGE_KEYWORDS
Old keyword failed on 2021 PDF. Replaced with content-based keywords that work across all years.

### Fix 2: Minimum years threshold
Require 4+ distinct years on a page to avoid false positives on executive summary pages.

### Fix 3: find_year_rows - re.match
Changed from `re.search` to `re.match` so year must START the cell. Prevents matching `2023` from `(tier 1 only from 2023)`.

### Fix 4: _split_embedded_values - strip annotations
Strip leading non-value text like `"restated*"` that was shifting column positions.

### Fix 5: normalize_rows - expand squished col 0
Handle camelot merging `"2024\n6.6%\n1.4%\n..."` into a single cell.

### Fix 6: _fill_positional_gaps - column index space
Sort anchors by COLUMN INDEX (not config definition index). Use min/max for non-monotonic ordering. Critical for 2023 asset_allocation where PDF column order differs from config definition order.

### Fix 7: Adaptive target year
Changed from `max(master_years) + 1` to `pdf_year` (detected from filename). Decoder uses only years < pdf_year.

### Fix 8: All-years extraction
Changed `extract()` to return ALL year rows, not just the target year. `file_generator` updated to overwrite existing master rows (captures restatements).

---

## 2023 PDF Column Layout Reference

The 2023 asset_allocation table has non-standard column ordering. This is the critical test case for the gap-fill algorithm.

| Col | Header in PDF | Config Pos | Series |
|-----|--------------|-----------|--------|
| 0 | Year | - | Year |
| 1 | Equities | 0 | Equities |
| 2 | Bonds | 1 | Bonds |
| 3 | Other investments | 2 | Other Investments |
| 4 | Cash and deposits | 4 | Cash (before Property!) |
| 5 | Property | 3 | Property (after Cash!) |
| 6 | Annuities | 9 | Annuities (config pos 9, col 6!) |
| 7 | Diversified growth funds | 7 | DGF - NEW, no prior ref |
| 8 | Absolute returns | 8 | AbsReturn - NEW, no prior ref |
| 9 | Insurance policies | 5 | Insurance |
| 10 | Hedge funds | 6 | Hedge Funds |
| 11 | Miscellaneous | 10 | Miscellaneous |

Gap-fill correctly places DGF->col7 and AbsReturn->col8 by finding them between Annuities(col6) and Insurance(col9).

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

## Key Technical Rules (Do Not Break)

1. **camelot stream flavor only** - never use lattice
2. **No hardcoded column indices** - decoder ring only
3. **No header text parsing for column ID** - value matching only
4. **Tolerance is +/-0.15 percentage points** (`_TOLERANCE = 0.15`)
5. **NA_OUTPUT_VALUE = 'NA'** (string, not None) - from config
6. **DEBUG_CSV = True** in extractor.py writes debug CSVs to `debug/`
7. **Master CSV structure**: row 0 = codes, row 1 = descriptions, rows 2+ = data
8. **Target year**: adaptive from PDF filename; decoder uses only years < pdf_year
9. **All years extracted**: every year row in the PDF is extracted, not just the new one
10. **Master overwrite**: existing rows are overwritten with latest source values (restatement capture)

---

## How To Run

```bash
# Full pipeline (production)
python main.py

# Test extraction accuracy
PYTHONIOENCODING=utf-8 python test_extraction.py

# Force Selenium (set in config.py: USE_DIRECT_REQUESTS = False)
python main.py
```
