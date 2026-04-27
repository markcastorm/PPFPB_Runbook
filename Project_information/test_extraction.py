"""
Extraction analysis & accuracy test.

Strategy: use PRIOR YEARS in the master CSV as a decoder ring to identify
which column in each camelot table corresponds to which series code.
No header parsing. No hardcoded column indices.

Usage:
    python test_extraction.py 2025          # test one PDF
    python test_extraction.py               # test all five PDFs
    python test_extraction.py 2025 strip    # strip target year from master before test
"""

import os
import re
import sys
import csv as csv_mod

import pdfplumber
import camelot
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

# Section definitions: which series belong to each section
from config import SERIES_DEFINITIONS, NA_OUTPUT_VALUE

SECTIONS = {
    'asset_allocation': [(c, d) for c, d, s, _ in SERIES_DEFINITIONS if s == 'asset_allocation'],
    'bond_splits':      [(c, d) for c, d, s, _ in SERIES_DEFINITIONS if s == 'bond_splits'],
    'equity_splits':    [(c, d) for c, d, s, _ in SERIES_DEFINITIONS if s == 'equity_splits'],
}

# pdfplumber page search keywords
PAGE_KEYWORDS = {
    # 'cash and deposits' + 'annuities' uniquely identifies the asset allocation table
    # across all PDF years and is more reliably extracted than the figure title
    'asset_allocation': ['cash and deposits', 'annuities'],
    'bond_splits':      ['bond split', 'index-linked'],
    'equity_splits':    ['uk quoted', 'overseas quoted'],
}


# ── Cell value cleaner ────────────────────────────────────────────────────────

NA_PATTERNS = {'', '--', '-', 'n/a', 'na', 'nan'}

def parse_cell(raw):
    """
    Convert raw camelot cell to float, or None if NA / non-numeric.
    Handles: '15.1%', '-7. 2%', '27. 8%', '7\n.0%', '3 7.5%', 'n/a', '--'
    """
    s = str(raw).strip()
    # Collapse all whitespace (including embedded newlines) and remove %
    s = re.sub(r'\s+', '', s).replace('%', '').replace(',', '')
    if s.lower() in NA_PATTERNS or s in ('+', '*'):
        return None
    # Handle unicode dashes
    if s in ('–', '—', '‒', '¿', '?'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── Master loader ─────────────────────────────────────────────────────────────

def load_master(exclude_from_year=None):
    """
    Returns {year(int): {series_code: float_or_None}}.
    exclude_from_year: exclude this year AND all later years (simulates fresh run).
    """
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
            raw = row.iloc[i + 1].strip()
            vals[code] = parse_cell(raw)   # None if NA
        result[yr] = vals
    return result


# ── pdfplumber page finder ────────────────────────────────────────────────────

def find_pages(pdf_path):
    """Returns {section: first_real_data_page} — skips index/TOC pages."""
    def norm(t):
        return re.sub(r'\s+', ' ', t.lower()).strip()

    found = {}
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        for page_num, page in enumerate(pdf.pages, start=1):
            # Skip the last 5 pages (likely index/TOC)
            if page_num > n_pages - 5:
                continue
            text = norm(page.extract_text() or '')
            # Require 4+ distinct data years on page — filters out exec-summary pages
            # that mention 1-2 years in narrative context
            years_on_page = set(re.findall(r'\b20(?:0[6-9]|1[0-9]|2[0-9])\b', text))
            if len(years_on_page) < 4:
                continue
            for section, keywords in PAGE_KEYWORDS.items():
                if section in found:
                    continue
                if all(kw in text for kw in keywords) if len(keywords) > 1 else any(kw in text for kw in keywords):
                    found[section] = page_num
    return found


# ── camelot extractor ─────────────────────────────────────────────────────────

def extract_tables(pdf_path, page_num, out_dir, label):
    """Run camelot stream on page_num, save CSVs, return list of row-lists."""
    all_rows = []
    try:
        tables = camelot.read_pdf(pdf_path, pages=str(page_num),
                                  flavor='stream', edge_tol=50)
        for i, tbl in enumerate(tables):
            df = tbl.df
            if df.empty or len(df) < 3:
                continue
            path = os.path.join(out_dir, f'{label}_p{page_num}_t{i}.csv')
            df.to_csv(path, index=False, encoding='utf-8')
            rows = df.values.tolist()
            all_rows.append(rows)
    except Exception as exc:
        log(f"  camelot ERROR page {page_num}: {exc}")
    return all_rows


# ── Year-row finder ───────────────────────────────────────────────────────────

def find_year_rows(rows):
    """
    Return {year(int): row_index} scanning ALL columns.
    A cell qualifies as a year-label only when the year appears at the START of
    the cell value (e.g. '2023', '2023 restated*') — this prevents false matches
    on header cells that merely mention a year in descriptive text
    (e.g. '(tier 1 only from 2023)').
    Scanning all columns handles tables where the year is not in col 0,
    such as the 2021 combined bond/equity table where col 0 is sidebar text.
    """
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


# ── Multi-value col-0 normalizer ─────────────────────────────────────────────

def _is_value_fragment(s):
    """True if s looks like a numeric value or an NA indicator."""
    s = s.strip()
    if not s:
        return False
    if s in ('-', '--', 'n/a', 'na', 'N/A', 'n/A', '–', '—', '‒'):
        return True
    return parse_cell(s) is not None


def _split_embedded_values(text_after_year):
    """
    Parse the text following a year marker in col 0, returning a list of
    raw value strings.  Handles:
    - The camelot split-number artefact: '7' + '.6%' -> '7.6%'
    - Leading annotation text ('restated*') that must be ignored so col
      positions stay consistent across all year rows (e.g. 2022 vs 2023).
    """
    lines = [l.strip() for l in text_after_year.split('\n') if l.strip()]
    values = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Digit-only fragment followed by a line starting with '.' -> rejoin
        if re.match(r'^-?\d+$', line) and (i + 1) < len(lines) and lines[i + 1].startswith('.'):
            values.append(line + lines[i + 1])
            i += 2
        else:
            values.append(line)
            i += 1
    # Drop any leading non-value annotation text (e.g. "restated*", "*")
    # so that col positions match between rows with and without annotations.
    while values and not _is_value_fragment(values[0]):
        values.pop(0)
    return values


def normalize_rows(rows):
    """
    Expands year rows where camelot has merged year + multiple values into col 0
    (happens when the PDF has tightly-packed columns with no clear separator).

    Example col-0 before:  '2024\\n6.6%\\n1.4%\\n41.7%\\n6.7%\\n43.6%\\n17.7%'
    After expansion  col 0: '2024'
                     col 1:  '6.6%'
                     col 2:  '1.4%'  ...  (original cols 1+ shift right)

    No-op when no such merging is detected.
    """
    expansions = {}
    for i, row in enumerate(rows):
        cell = str(row[0])
        m = re.search(r'\b(20\d{2})\b', cell)
        if not m or '\n' not in cell:
            continue
        after = cell[m.end():].strip()
        if not after:
            continue
        embedded = _split_embedded_values(after)
        # Only trigger when at least 2 of the fragments look like values/NAs
        if sum(1 for v in embedded if _is_value_fragment(v)) >= 2:
            expansions[i] = embedded

    if not expansions:
        return rows

    max_expanded = max(len(v) for v in expansions.values())

    new_rows = []
    for i, row in enumerate(rows):
        cell = str(row[0])
        m = re.search(r'\b(20\d{2})\b', cell)
        if m and i in expansions:
            embedded = expansions[i]
            padded = embedded + [''] * (max_expanded - len(embedded))
            new_row = [cell[:m.end()]] + padded + list(row[1:])
        else:
            new_row = [cell] + [''] * max_expanded + list(row[1:])
        new_rows.append(new_row)

    return new_rows


# ── Master-based column identification (the core intelligence) ────────────────

def identify_columns(all_table_rows, section, master_data, tolerance=0.15):
    """
    For each camelot table returned for this page, try to match series values
    against master historical data to identify which column = which series.

    Returns (best_rows, col_map: {col_idx: series_code}, ref_year_used)
    """
    series_list = SECTIONS[section]   # [(code, desc), ...]

    best_table_rows = None
    best_col_map    = {}
    best_score      = 0
    best_ref_year   = None

    for rows in all_table_rows:
        rows      = normalize_rows(rows)
        year_rows = find_year_rows(rows)
        n_cols    = len(rows[0]) if rows else 0

        # Common years between this table and the master
        common = sorted(set(year_rows) & set(master_data), reverse=True)
        if not common:
            continue

        col_map   = {}
        ref_year  = None

        # Build column map: for each series, find the column that matches
        # across the most reference years
        for code, _ in series_list:
            # Gather (master_val, row_in_table) for years where master has a value
            ref_pairs = []
            for yr in common:
                mv = master_data[yr].get(code)
                if mv is None:
                    continue
                ref_pairs.append((mv, year_rows[yr]))

            if not ref_pairs:
                continue

            # Score each column
            best_col   = None
            best_hits  = 0
            for col_idx in range(1, n_cols):
                hits = 0
                for mv, row_idx in ref_pairs:
                    cv = parse_cell(str(rows[row_idx][col_idx]))
                    if cv is not None and abs(cv - mv) <= tolerance:
                        hits += 1
                if hits > best_hits:
                    best_hits = hits
                    best_col  = col_idx

            if best_col is not None and best_hits >= 1:
                # Avoid assigning the same column to two different series
                if best_col not in col_map:
                    col_map[best_col] = code
                    if ref_year is None:
                        ref_year = common[0]

        # Positional gap-fill for series that have no prior reference years
        # (e.g. Dev/Emg equity and DGF/AbsReturn introduced in 2023).
        # If identified anchor columns bracket an exact number of gap columns
        # equal to the number of unidentified series between those anchors,
        # assign them in definition order.
        col_map = _fill_positional_gaps(col_map, series_list)

        score = len(col_map)
        if score > best_score:
            best_score      = score
            best_col_map    = col_map
            best_table_rows = rows   # already normalize_rows'd
            best_ref_year   = ref_year

    return best_table_rows, best_col_map, best_ref_year


def _fill_positional_gaps(col_map, series_list):
    """
    After the decoder-ring pass, fill in series that could not be identified
    (no prior reference years) by positional inference.

    Anchors are sorted by COLUMN INDEX (not config definition index).  For each
    consecutive column pair (col_a, col_b), we look for gap columns between them
    and unidentified series whose config positions fall between the two anchors'
    config positions (using min/max so non-monotonic PDF vs config ordering is
    handled correctly).

    Example (equity_splits): UK->col1, OS->col2, Unquoted->col5.
      Pair (col2, col5): gaps=[3,4]. Dev(def2) and Emg(def3) between def1 and def4.
      Count match 2==2 -> fill Dev->col3, Emg->col4.

    Example (asset_allocation 2023): Annuities->col6(def9), Insurance->col9(def5).
      Pair (col6, col9): gaps=[7,8]. DGF(def7) and AbsReturn(def8) between def5
      and def9. Count match 2==2 -> fill DGF->col7, AbsReturn->col8.
      This works even though col order and config order disagree (Annuities is
      col6 in the PDF but definition index 9 in config).
    """
    if not col_map:
        return col_map

    codes_in_order = [code for code, _ in series_list]
    code_to_col    = {code: idx for idx, code in col_map.items()}

    # Sort identified anchors by COLUMN INDEX
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
        # col_a < col_b guaranteed because anchors are sorted by column index

        # Gap columns between col_a and col_b that are not yet assigned
        gaps = [c for c in range(col_a + 1, col_b) if c not in col_map]
        if not gaps:
            continue

        # Unidentified series whose config positions fall strictly between the
        # two anchors' config positions (min/max handles reversed config vs col order)
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


# ── Extract target year from mapped table ─────────────────────────────────────

def extract_year_data(rows, col_map, target_year):
    """
    Find target_year row in rows, return {series_code: value_or_NA}.
    Falls back to latest year if target not found.
    """
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


# ── Accuracy check against master ────────────────────────────────────────────

def check_accuracy(extracted, master_data, year):
    """Compare extracted values against master for given year. Returns (match, miss, total)."""
    if year not in master_data:
        return None, None, None
    ref    = master_data[year]
    match  = 0
    miss   = []
    total  = 0
    for code in SECTIONS['asset_allocation'] + SECTIONS['bond_splits'] + SECTIONS['equity_splits']:
        code_str = code[0]
        master_v = ref.get(code_str)
        if master_v is None:
            continue
        total += 1
        ext_v = extracted.get(code_str)
        if ext_v == NA_OUTPUT_VALUE or ext_v is None:
            miss.append(f"{code_str[-30:]}  master={master_v}  extracted=NA")
            continue
        try:
            diff = abs(float(ext_v) - float(master_v))
            if diff <= 0.15:
                match += 1
            else:
                miss.append(f"{code_str[-30:]}  master={master_v}  extracted={ext_v}  diff={diff:.2f}")
        except (ValueError, TypeError):
            miss.append(f"{code_str[-30:]}  master={master_v}  extracted={ext_v}  (parse error)")
    return match, miss, total


# ── Logging ───────────────────────────────────────────────────────────────────

_log_lines = []

def log(msg):
    """Print and buffer for summary."""
    print(msg)
    _log_lines.append(msg)


# ── Per-PDF driver ────────────────────────────────────────────────────────────

def analyse_pdf(pdf_path, master_data, full_master, strip_year=None):
    name   = os.path.basename(pdf_path)
    yr_m   = re.search(r'(202\d)', name)
    pdf_yr = int(yr_m.group(1)) if yr_m else 0

    out_dir = os.path.join(DEBUG_DIR, str(pdf_yr))
    os.makedirs(out_dir, exist_ok=True)

    log(f"\n{'='*68}")
    log(f"PDF : {name}  (year={pdf_yr})")
    if strip_year:
        log(f"Mode: master WITHOUT year {strip_year} (simulating fresh run)")
    log('='*68)

    # Target year = the PDF's own year (adaptive)
    target_year = pdf_yr
    # Decoder ring uses ONLY years BEFORE the PDF year — simulates a fresh run
    decoder_master = {yr: v for yr, v in master_data.items() if yr < target_year}
    log(f"Master years for decoder: {sorted(decoder_master.keys())}")
    log(f"Target year to extract : {target_year}")

    # 1. Find pages
    pages = find_pages(pdf_path)
    log(f"Pages found : {pages}")
    if not pages:
        log("  ERROR: no pages found")
        return

    # 2. Load camelot tables per page
    page_tables = {}
    seen = set()
    for section, pg in pages.items():
        for p in (pg, pg + 1):
            if p not in seen:
                seen.add(p)
                page_tables[p] = extract_tables(pdf_path, p, out_dir, f'{section}')

    # Helper: tables for a section (primary + overflow page)
    def tables_for(sec):
        pg = pages.get(sec)
        if pg is None:
            return []
        return list(page_tables.get(pg, [])) + list(page_tables.get(pg + 1, []))

    # 3. Identify columns + extract target year for each section
    all_extracted = {}

    for section in ('asset_allocation', 'bond_splits', 'equity_splits'):
        log(f"\n-- Section: {section} --")
        all_rows = tables_for(section)
        log(f"  Tables available: {len(all_rows)}")

        rows, col_map, ref_yr = identify_columns(all_rows, section, decoder_master)

        if not col_map:
            log(f"  WARNING: could not identify any columns for {section}")
            continue

        log(f"  Reference year used : {ref_yr}")
        log(f"  Column map ({len(col_map)} series):")
        for ci, code in sorted(col_map.items()):
            log(f"    col[{ci}] -> {code[code.rfind('.')+1:]}")

        extracted, found_yr = extract_year_data(rows, col_map, target_year)
        log(f"  Extracted year: {found_yr}")
        for code, val in extracted.items():
            log(f"    {code[code.rfind('.')+1:]:40s} = {val}")

        all_extracted.update(extracted)

    # 4. Accuracy check against full master for the PDF year
    check_year = pdf_yr
    log(f"\n-- Accuracy vs full master for year {check_year} --")
    match, miss_list, total = check_accuracy(all_extracted, full_master, check_year)
    if match is None:
        log(f"  Year {check_year} not in master — cannot validate")
    else:
        pct = 100.0 * match / total if total else 0
        log(f"  Result: {match}/{total} series matched  ({pct:.0f}%)")
        if miss_list:
            log(f"  Mismatches / missing:")
            for m in miss_list:
                log(f"    {m}")
        else:
            log("  All series match master EXACTLY")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    strip_year = None
    yr_arg     = None

    for arg in sys.argv[1:]:
        if arg == 'strip':
            pass  # handled below with yr_arg
        elif re.match(r'^\d{4}$', arg):
            yr_arg = int(arg)

    # If 'strip' is in args, exclude the target year from master
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

    for pdf in pdfs:
        if not os.path.exists(pdf):
            print(f"[SKIP] {pdf}")
            continue
        analyse_pdf(pdf, master_data, full_master, strip_year)

    # Write summary log
    summary = os.path.join(DEBUG_DIR, 'test_results.txt')
    with open(summary, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(_log_lines))
    print(f"\nFull log written to: {summary}")
