"""
PDF text extraction test — pdfplumber only, no pdf2docx.

Strategy:
  1. pdfplumber finds pages (keywords + 4-year threshold)
  2. pdfplumber extract_text() gets clean text lines per page (instant)
  3. Parse text lines into rows: year + space-separated values
  4. Decoder ring (master value matching) identifies columns
  5. Extract target year data

Usage:
    python test_extraction_docx.py 2024          # test one PDF
    python test_extraction_docx.py               # test all five PDFs
    python test_extraction_docx.py 2024 strip    # strip target year from master
"""

import os
import re
import sys
import time

import pdfplumber
import pandas as pd

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MASTER_CSV = os.path.join(BASE_DIR, 'Master_Data', 'Master_PPFPB_DATA.csv')
PDF_DIR    = os.path.join(BASE_DIR, 'Project_information')
DEBUG_DIR  = os.path.join(BASE_DIR, 'debug')

PDFS = [
    os.path.join(PDF_DIR, 'Pension-Protection-Fund-Purple-Book-2025-accessible.pdf'),
    os.path.join(PDF_DIR, 'PPF-The-Purple-Book-2024.pdf'),
    os.path.join(PDF_DIR, 'PPF-The-Purple-Book-2023.pdf'),
    os.path.join(PDF_DIR, 'PPF_PurpleBook_2022.pdf'),
    os.path.join(PDF_DIR, 'PPF_PurpleBook_2021.pdf'),
]

from config import SERIES_DEFINITIONS, NA_OUTPUT_VALUE

SECTIONS = {
    'asset_allocation': [(c, d) for c, d, s, _ in SERIES_DEFINITIONS if s == 'asset_allocation'],
    'bond_splits':      [(c, d) for c, d, s, _ in SERIES_DEFINITIONS if s == 'bond_splits'],
    'equity_splits':    [(c, d) for c, d, s, _ in SERIES_DEFINITIONS if s == 'equity_splits'],
}

PAGE_KEYWORDS = {
    'asset_allocation': ['cash and deposits', 'annuities'],
    'bond_splits':      ['bond split', 'index-linked'],
    'equity_splits':    ['uk quoted', 'overseas quoted'],
}

_log_lines = []
def log(msg):
    print(msg)
    _log_lines.append(msg)


# ── Cell value cleaner ────────────────────────────────────────────────────────

NA_PATTERNS = {'', '--', '-', 'n/a', 'na', 'nan', '–', '—', '‒', '¿', '?'}

def parse_cell(raw):
    """Convert raw token to float, or None if NA/non-numeric."""
    s = str(raw).strip().replace('%', '').replace(',', '')
    s = s.replace('\u2013', '-').replace('\u2014', '-')  # en/em dash -> minus
    if s.lower() in NA_PATTERNS or s in ('+', '*'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── Master loader ─────────────────────────────────────────────────────────────

def load_master(exclude_from_year=None):
    if not os.path.exists(MASTER_CSV):
        return {}
    df = pd.read_csv(MASTER_CSV, header=None, dtype=str).fillna('')
    codes = df.iloc[0, 1:].tolist()
    result = {}
    for _, row in df.iloc[2:].iterrows():
        yr_str = row.iloc[0].strip()
        if not re.match(r'^\d{4}$', yr_str):
            continue
        yr = int(yr_str)
        if exclude_from_year and yr >= exclude_from_year:
            continue
        vals = {}
        for i, code in enumerate(codes):
            vals[code] = parse_cell(row.iloc[i + 1].strip())
        result[yr] = vals
    return result


# ── pdfplumber page finder ────────────────────────────────────────────────────

def find_pages(pdf_path):
    """Returns {section: page_index_0based}."""
    found = {}
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            if i > n_pages - 5:
                continue
            text = re.sub(r'\s+', ' ', (page.extract_text() or '').lower())
            years = set(re.findall(r'\b20(?:0[6-9]|1[0-9]|2[0-9])\b', text))
            if len(years) < 4:
                continue
            for sec, kws in PAGE_KEYWORDS.items():
                if sec not in found and all(k in text for k in kws):
                    found[sec] = i
    return found


# ── Text-based table extraction ───────────────────────────────────────────────

def _extract_text_table(pdf_path, page_idx, section, n_series):
    """
    Extract a table from a PDF page using pdfplumber text extraction.

    Returns list of rows, where each row is [year_str, val1, val2, ...].
    Only returns rows that start with a year (20xx).

    The page text has lines like:
      2024 15.5% 69.8% 14.7% -5.4% 5.9% 9.7% 1.0% 2.6% – – 0.9%

    For bond/equity splits, the weighted average and simple average are on the
    same line. We use n_series to know how many values belong to weighted avg.
    """
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_idx]
        text = page.extract_text() or ''

    rows = []
    seen_years = set()

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue

        # Must start with a year
        m = re.match(r'^(20\d{2})\b', line)
        if not m:
            continue

        yr = m.group(1)
        if yr in seen_years:
            continue  # skip duplicate year lines (from right-side tables)

        # Extract all tokens after the year (skip "restated*" etc.)
        rest = line[m.end():].strip()
        # Remove trailing non-value junk (e.g. "Bond category All Tier 1...")
        # by only keeping tokens that look like values
        tokens = rest.split()

        values = [yr]
        for tok in tokens:
            v = parse_cell(tok)
            if v is not None:
                values.append(tok)
            elif tok.lower() in ('n/a', 'na', '–', '—', '-', '‒', '¿'):
                values.append(tok)
            elif tok.endswith('%'):
                values.append(tok)  # might be parseable after cleanup
            else:
                # Non-value token — could be start of right-side table text
                # Only stop if we already have enough values
                if len(values) - 1 >= n_series:
                    break
                # Otherwise it's junk in the middle, skip it
                continue

        # Only accept rows with at least 2 values (year + 1 data point)
        if len(values) >= 2:
            seen_years.add(yr)
            rows.append(values)

    return rows


def _text_rows_to_grid(rows):
    """
    Convert text rows (variable-length lists) to a uniform grid.
    Pads shorter rows with empty strings.
    """
    if not rows:
        return []
    max_cols = max(len(r) for r in rows)
    return [r + [''] * (max_cols - len(r)) for r in rows]


# ── Year-row finder ───────────────────────────────────────────────────────────

def find_year_rows(rows):
    """Return {year(int): row_index} — year must START the cell."""
    result = {}
    for i, row in enumerate(rows):
        for cell in row:
            s = str(cell).strip()
            m = re.match(r'^(20\d{2})', s)
            if m:
                yr = int(m.group(1))
                if yr not in result:
                    result[yr] = i
                break
    return result


# ── Master-based column identification (decoder ring) ─────────────────────────

def identify_columns(all_table_rows, section, master_data, tolerance=0.15):
    """
    For each table, match series values against master to identify columns.
    Returns (best_rows, col_map: {col_idx: series_code}, ref_year_used)
    """
    series_list = SECTIONS[section]

    best_table_rows = None
    best_col_map    = {}
    best_score      = 0
    best_ref_year   = None

    for rows in all_table_rows:
        year_rows = find_year_rows(rows)
        n_cols    = max(len(r) for r in rows) if rows else 0

        common = sorted(set(year_rows) & set(master_data), reverse=True)
        if not common:
            continue

        col_map  = {}
        ref_year = None

        for code, _ in series_list:
            ref_pairs = []
            for yr in common:
                mv = master_data[yr].get(code)
                if mv is None:
                    continue
                ref_pairs.append((mv, year_rows[yr]))
            if not ref_pairs:
                continue

            best_col  = None
            best_hits = 0
            for col_idx in range(1, n_cols):
                hits = 0
                for mv, row_idx in ref_pairs:
                    if col_idx < len(rows[row_idx]):
                        cv = parse_cell(str(rows[row_idx][col_idx]))
                        if cv is not None and abs(cv - mv) <= tolerance:
                            hits += 1
                if hits > best_hits:
                    best_hits = hits
                    best_col  = col_idx

            if best_col is not None and best_hits >= 1:
                if best_col not in col_map:
                    col_map[best_col] = code
                    if ref_year is None:
                        ref_year = common[0]

        col_map = _fill_positional_gaps(col_map, series_list)

        score = len(col_map)
        if score > best_score:
            best_score      = score
            best_col_map    = col_map
            best_table_rows = rows
            best_ref_year   = ref_year

    return best_table_rows, best_col_map, best_ref_year


def _fill_positional_gaps(col_map, series_list):
    """Fill unidentified series by positional inference between anchors."""
    if not col_map:
        return col_map

    codes_in_order = [code for code, _ in series_list]
    code_to_col    = {code: idx for idx, code in col_map.items()}

    anchors = sorted(
        [(col, codes_in_order.index(code), code)
         for col, code in col_map.items()
         if code in codes_in_order],
        key=lambda x: x[0]
    )

    if len(anchors) < 2:
        return col_map

    for k in range(len(anchors) - 1):
        col_a, def_a, _ = anchors[k]
        col_b, def_b, _ = anchors[k + 1]

        gaps = [c for c in range(col_a + 1, col_b) if c not in col_map]
        if not gaps:
            continue

        def_min = min(def_a, def_b)
        def_max = max(def_a, def_b)
        unid = [codes_in_order[j]
                for j in range(def_min + 1, def_max)
                if codes_in_order[j] not in code_to_col]

        if len(unid) == len(gaps):
            for code, col in zip(unid, gaps):
                col_map[col] = code
                code_to_col[code] = col

    return col_map


# ── Extract target year ───────────────────────────────────────────────────────

def extract_year_data(rows, col_map, target_year):
    """Find target year row, return {series_code: value_or_NA}."""
    year_rows = find_year_rows(rows)
    if not year_rows:
        return {}, None

    if target_year in year_rows:
        row_idx    = year_rows[target_year]
        found_year = target_year
    else:
        found_year = max(year_rows)
        row_idx    = year_rows[found_year]
        log(f"  Year {target_year} not in table, using latest={found_year}")

    data_row = rows[row_idx]
    result   = {}
    for col_idx, code in col_map.items():
        if col_idx < len(data_row):
            val = parse_cell(str(data_row[col_idx]))
            result[code] = val if val is not None else NA_OUTPUT_VALUE
        else:
            result[code] = NA_OUTPUT_VALUE
    return result, found_year


# ── Accuracy check ────────────────────────────────────────────────────────────

def check_accuracy(extracted, master_data, year):
    if year not in master_data:
        return None, None, None
    ref   = master_data[year]
    match = 0
    miss  = []
    total = 0
    for code, _ in SECTIONS['asset_allocation'] + SECTIONS['bond_splits'] + SECTIONS['equity_splits']:
        mv = ref.get(code)
        if mv is None:
            continue
        total += 1
        ev = extracted.get(code)
        if ev == NA_OUTPUT_VALUE or ev is None:
            miss.append(f"{code[-30:]}  master={mv}  extracted=NA")
            continue
        try:
            diff = abs(float(ev) - float(mv))
            if diff <= 0.15:
                match += 1
            else:
                miss.append(f"{code[-30:]}  master={mv}  extracted={ev}  diff={diff:.2f}")
        except (ValueError, TypeError):
            miss.append(f"{code[-30:]}  master={mv}  extracted={ev}  (parse error)")
    return match, miss, total


# ── Per-PDF driver ────────────────────────────────────────────────────────────

def analyse_pdf(pdf_path, master_data, full_master, strip_year=None):
    name   = os.path.basename(pdf_path)
    yr_m   = re.search(r'(202\d)', name)
    pdf_yr = int(yr_m.group(1)) if yr_m else 0

    out_dir = os.path.join(DEBUG_DIR, f'{pdf_yr}_text')
    os.makedirs(out_dir, exist_ok=True)

    log(f"\n{'='*68}")
    log(f"PDF : {name}  (year={pdf_yr})")
    log('='*68)

    master_years = sorted(master_data.keys())
    target_year  = (max(master_years) + 1) if master_years else pdf_yr
    log(f"Master years : {master_years}")
    log(f"Target year  : {target_year}")

    # 1. Find pages
    t0 = time.time()
    pages = find_pages(pdf_path)
    log(f"Pages found  : {pages}  ({time.time()-t0:.1f}s)")
    if not pages:
        log("  ERROR: no pages found")
        return

    # 2. Extract text tables from each section page
    t0 = time.time()
    section_n_series = {
        'asset_allocation': len(SECTIONS['asset_allocation']),  # 11
        'bond_splits':      len(SECTIONS['bond_splits']),        # 3
        'equity_splits':    len(SECTIONS['equity_splits']),      # 5
    }

    all_extracted = {}
    found_year    = None

    for section in ('asset_allocation', 'bond_splits', 'equity_splits'):
        log(f"\n-- Section: {section} --")
        pidx = pages.get(section)
        if pidx is None:
            log(f"  SKIP: page not found for {section}")
            continue

        n_series = section_n_series[section]
        text_rows = _extract_text_table(pdf_path, pidx, section, n_series)
        grid = _text_rows_to_grid(text_rows)

        log(f"  Page {pidx}, {len(grid)} year-rows, max {max(len(r) for r in grid) if grid else 0} cols")

        # Debug: save parsed grid
        debug_path = os.path.join(out_dir, f'{section}_text_grid.csv')
        with open(debug_path, 'w', encoding='utf-8') as f:
            for row in grid:
                f.write(','.join(str(c) for c in row) + '\n')

        # Wrap in list for identify_columns (expects list of tables)
        rows, col_map, ref_yr = identify_columns([grid], section, master_data)

        if not col_map:
            log(f"  WARNING: could not identify columns for {section}")
            continue

        log(f"  Ref year: {ref_yr}, Columns mapped: {len(col_map)}")
        for ci, code in sorted(col_map.items()):
            log(f"    col[{ci}] -> {code[code.rfind('.')+1:]}")

        extracted, fy = extract_year_data(rows, col_map, target_year)
        found_year = fy
        log(f"  Extracted year: {fy}")
        for code, val in extracted.items():
            log(f"    {code[code.rfind('.')+1:]:40s} = {val}")

        all_extracted.update(extracted)

    elapsed = time.time() - t0
    log(f"\nExtraction time: {elapsed:.1f}s")

    # 4. Accuracy — compare against the year actually extracted
    check_yr = found_year if found_year else target_year
    log(f"\n-- Accuracy vs master for year {check_yr} --")
    match, miss_list, total = check_accuracy(all_extracted, full_master, check_yr)
    if match is None:
        log(f"  Year {check_yr} not in master — cannot validate")
    else:
        pct = 100.0 * match / total if total else 0
        log(f"  Result: {match}/{total} matched  ({pct:.0f}%)")
        if miss_list:
            log(f"  Mismatches:")
            for m in miss_list:
                log(f"    {m}")
        else:
            log("  ALL MATCH")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    strip_year = None
    yr_arg     = None

    for arg in sys.argv[1:]:
        if arg == 'strip':
            pass
        elif re.match(r'^\d{4}$', arg):
            yr_arg = int(arg)

    if 'strip' in sys.argv:
        strip_year = yr_arg

    full_master = load_master()
    master_data = load_master(exclude_from_year=strip_year)

    log(f"Full master years : {sorted(full_master.keys())}")
    log(f"Working master    : {sorted(master_data.keys())}")

    pdfs = PDFS
    if yr_arg:
        pdfs = [p for p in PDFS if str(yr_arg) in p]
        if not pdfs:
            print(f"No PDF found for year {yr_arg}")
            sys.exit(1)

    t_total = time.time()
    for pdf in pdfs:
        if not os.path.exists(pdf):
            print(f"[SKIP] {pdf}")
            continue
        analyse_pdf(pdf, master_data, full_master, strip_year)

    log(f"\n{'='*68}")
    log(f"TOTAL TIME: {time.time()-t_total:.1f}s")
    log('='*68)

    summary = os.path.join(DEBUG_DIR, 'test_results_text.txt')
    os.makedirs(DEBUG_DIR, exist_ok=True)
    with open(summary, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(_log_lines))
    print(f"\nFull log: {summary}")
