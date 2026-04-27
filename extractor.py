"""
Extracts asset allocation, bond splits and equity splits from PPF Purple Book PDFs.

Strategy:
  1. pdfplumber  — locate the page containing each of the three sections
  2. camelot     — pull raw tables from those pages (stream flavor only)
  3. master CSV  — use prior-year known values as a decoder ring to identify
                   which column in each camelot table corresponds to which series.
                   No hardcoded column indices; no header text parsing.
  4. Extract the target year row using the confirmed column map.

This approach handles layout changes across PDF editions automatically because
the column identification is driven by value matching, not by header text.
"""

import os
import re
import logging

import pdfplumber
import camelot
import pandas as pd

import config

logger = logging.getLogger(__name__)

DEBUG_CSV = True


# ── Page-search keywords ──────────────────────────────────────────────────────
# ALL keywords in a list must appear in the page text for it to match.

_PAGE_KEYWORDS = {
    # 'cash and deposits' + 'annuities' uniquely identify the asset allocation
    # table across all PDF years; more reliable than the figure title
    'asset_allocation': ['cash and deposits', 'annuities'],
    'bond_splits':      ['bond split', 'index-linked'],
    'equity_splits':    ['uk quoted', 'overseas quoted'],
}

# Section -> list of (series_code, description) in definition order
_SECTIONS = {
    sec: [(c, d) for c, d, s, _ in config.SERIES_DEFINITIONS if s == sec]
    for sec in ('asset_allocation', 'bond_splits', 'equity_splits')
}

# Tolerance (percentage points) for value matching during column identification
_TOLERANCE = 0.15

# NA markers that parse_cell treats as missing
_NA_PATTERNS = {'', '--', '-', 'n/a', 'na', 'nan'}


# ── Cell value parser ─────────────────────────────────────────────────────────

def _parse_cell(raw):
    """
    Convert a raw camelot cell to float, or None if NA / non-numeric.
    Handles: '15.1%', '-7. 2%', '27. 8%', '7\\n.0%', '3 7.5%', 'n/a', '--', '–'
    """
    s = re.sub(r'\s+', '', str(raw)).replace('%', '').replace(',', '')
    if s.lower() in _NA_PATTERNS or s in ('+', '*'):
        return None
    if s in ('–', '—', '‒', '¿', '?'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── Master CSV loader ─────────────────────────────────────────────────────────

def _load_master():
    """
    Load master CSV into {year(int): {series_code: float_or_None}}.
    Returns empty dict if the master does not exist yet.
    """
    if not os.path.exists(config.MASTER_CSV):
        return {}
    try:
        df = pd.read_csv(config.MASTER_CSV, header=None, dtype=str).fillna('')
        codes = df.iloc[0, 1:].tolist()
        result = {}
        for _, row in df.iloc[2:].iterrows():
            yr_str = row.iloc[0].strip()
            if not re.match(r'^\d{4}$', yr_str):
                continue
            yr = int(yr_str)
            vals = {}
            for i, code in enumerate(codes):
                raw = row.iloc[i + 1].strip()
                vals[code] = _parse_cell(raw)
            result[yr] = vals
        return result
    except Exception as exc:
        logger.warning(f"Could not load master CSV: {exc}")
        return {}


def get_last_master_year():
    """Return the highest year already in the master CSV (int), or None."""
    master = _load_master()
    return max(master.keys()) if master else None


# ── pdfplumber page finder ────────────────────────────────────────────────────

def _find_section_pages(pdf_path):
    """
    Scan PDF text page by page using pdfplumber.
    Returns {section_name: first_matching_page (1-indexed)}.
    Requires 4+ distinct data years on a page to avoid false positives on
    executive-summary pages that only mention 1-2 years in narrative text.
    Skips the last 5 pages (likely index/TOC).
    """
    def norm(t):
        return re.sub(r'\s+', ' ', t.lower()).strip()

    found = {}
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        for page_num, page in enumerate(pdf.pages, start=1):
            if page_num > n_pages - 5:
                continue
            text = norm(page.extract_text() or '')
            years_on_page = set(re.findall(r'\b20(?:0[6-9]|1[0-9]|2[0-9])\b', text))
            if len(years_on_page) < 4:
                continue
            for section, keywords in _PAGE_KEYWORDS.items():
                if section in found:
                    continue
                if all(kw in text for kw in keywords):
                    found[section] = page_num
                    logger.info(f"  {section} -> page {page_num}")

    missing = [s for s in _PAGE_KEYWORDS if s not in found]
    if missing:
        logger.warning(f"Could not locate sections: {missing}")
    return found


# ── camelot table extractor ───────────────────────────────────────────────────

def _camelot_tables(pdf_path, page_num):
    """
    Extract tables from page_num using camelot stream flavor.
    Returns list of row-lists (each table is a list of row-lists).
    Saves debug CSVs to <BASE_DIR>/debug/ when DEBUG_CSV is True.
    """
    all_rows = []
    try:
        tables = camelot.read_pdf(
            pdf_path, pages=str(page_num), flavor='stream', edge_tol=50
        )
        for i, tbl in enumerate(tables):
            df = tbl.df
            if df.empty or len(df) < 3:
                continue
            if DEBUG_CSV:
                debug_dir = os.path.join(config.BASE_DIR, 'debug')
                os.makedirs(debug_dir, exist_ok=True)
                df.to_csv(
                    os.path.join(debug_dir, f'p{page_num}_stream_t{i}.csv'),
                    index=False,
                )
            all_rows.append(df.values.tolist())
    except Exception as exc:
        logger.warning(f"  camelot error page {page_num}: {exc}")
    return all_rows


def _load_page_tables(pdf_path, section_pages):
    """
    Load camelot tables for every unique page referenced in section_pages,
    plus the next page (tables can span two pages).
    Returns {page_num: [list-of-row-lists]}.
    """
    seen = set()
    result = {}
    for sec in ('asset_allocation', 'bond_splits', 'equity_splits'):
        pg = section_pages.get(sec)
        if pg is None:
            continue
        for p in (pg, pg + 1):
            if p not in seen:
                seen.add(p)
                result[p] = _camelot_tables(pdf_path, p)
    return result


def _tables_for(section, section_pages, page_tables):
    """Return combined row-list-of-tables for a section (primary + next page)."""
    pg = section_pages.get(section)
    if pg is None:
        return []
    return list(page_tables.get(pg, [])) + list(page_tables.get(pg + 1, []))


# ── Multi-value col-0 normalizer ──────────────────────────────────────────────

def _is_value_fragment(s):
    """True if s looks like a numeric value or an NA indicator."""
    s = s.strip()
    if not s:
        return False
    if s in ('-', '--', 'n/a', 'na', 'N/A', '–', '—', '‒'):
        return True
    return _parse_cell(s) is not None


def _split_embedded_values(text_after_year):
    """
    Parse values embedded after a year marker in col 0.
    Handles the camelot split-number artefact ('7' + '.6%' -> '7.6%') and
    strips leading annotation text ('restated*') that must not shift column
    positions relative to other year rows.
    """
    lines = [l.strip() for l in text_after_year.split('\n') if l.strip()]
    values = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'^-?\d+$', line) and (i + 1) < len(lines) and lines[i + 1].startswith('.'):
            values.append(line + lines[i + 1])
            i += 2
        else:
            values.append(line)
            i += 1
    while values and not _is_value_fragment(values[0]):
        values.pop(0)
    return values


def _normalize_rows(rows):
    """
    Expand rows where camelot merged year + multiple values into col 0.
    Example before: col0 = '2024\\n6.6%\\n1.4%\\n41.7%...'
    Example after:  col0 = '2024', col1 = '6.6%', col2 = '1.4%', ...
    No-op if no such merging is detected.
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


# ── Year-row finder ───────────────────────────────────────────────────────────

def _find_year_rows(rows):
    """
    Return {year(int): row_index}.
    Scans all columns; accepts only cells where the year appears at the START
    of the cell value (avoids false matches on header cells such as
    '(tier 1 only from 2023)').  Handles tables where the year column is not
    col 0 (e.g. the 2021 combined bond/equity table).
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


# ── Positional gap-fill ──────────────────────────────────────────────────────

def _fill_positional_gaps(col_map, series_list):
    """
    After the decoder-ring pass, fill in series that could not be identified
    (no prior reference years) by positional inference.

    Anchors are sorted by COLUMN INDEX (not config definition index).  For each
    consecutive column pair (col_a, col_b), we look for gap columns between them
    and unidentified series whose config positions fall between the two anchors'
    config positions (using min/max so non-monotonic PDF vs config ordering is
    handled correctly).
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


# ── Master-based column identification ───────────────────────────────────────

def _identify_columns(all_table_rows, section, master_data):
    """
    For each camelot table on the section's page(s), score every column against
    historical master values to find which column corresponds to which series.

    Returns (best_rows, col_map {col_idx: series_code}, ref_year_used).
    """
    series_list = _SECTIONS[section]

    best_table_rows = None
    best_col_map    = {}
    best_score      = 0
    best_ref_year   = None

    for rows in all_table_rows:
        rows      = _normalize_rows(rows)
        year_rows = _find_year_rows(rows)
        n_cols    = len(rows[0]) if rows else 0

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
                    cv = _parse_cell(str(rows[row_idx][col_idx]))
                    if cv is not None and abs(cv - mv) <= _TOLERANCE:
                        hits += 1
                if hits > best_hits:
                    best_hits = hits
                    best_col  = col_idx

            if best_col is not None and best_hits >= 1 and best_col not in col_map:
                col_map[best_col] = code
                if ref_year is None:
                    ref_year = common[0]

        # Positional gap-fill for series with no prior reference years
        col_map = _fill_positional_gaps(col_map, series_list)

        score = len(col_map)
        if score > best_score:
            best_score      = score
            best_col_map    = col_map
            best_table_rows = rows
            best_ref_year   = ref_year

    return best_table_rows, best_col_map, best_ref_year


# ── Extract target year from mapped table ─────────────────────────────────────

def _extract_year_data(rows, col_map, target_year):
    """
    Find the target_year row in rows and extract series values using col_map.
    Falls back to the latest year present if target_year is not in the table.
    Returns ({series_code: value_or_NA}, found_year).
    """
    year_rows = _find_year_rows(rows)
    if not year_rows:
        return {}, None

    if target_year and target_year in year_rows:
        row_idx    = year_rows[target_year]
        found_year = target_year
    else:
        found_year = max(year_rows)
        row_idx    = year_rows[found_year]
        if target_year:
            logger.warning(
                f"Year {target_year} not found in table; using latest={found_year}"
            )

    data_row = rows[row_idx]
    result   = {}
    for col_idx, code in col_map.items():
        if col_idx < len(data_row):
            val = _parse_cell(str(data_row[col_idx]))
            result[code] = val if val is not None else config.NA_OUTPUT_VALUE
        else:
            result[code] = config.NA_OUTPUT_VALUE
    return result, found_year


def _extract_all_years(rows, col_map):
    """
    Extract data for ALL year rows in the table using col_map.
    Returns {year(int): {series_code: value_or_NA}}.
    """
    year_rows = _find_year_rows(rows)
    if not year_rows:
        return {}

    all_years = {}
    for yr, row_idx in year_rows.items():
        data_row = rows[row_idx]
        result = {}
        for col_idx, code in col_map.items():
            if col_idx < len(data_row):
                val = _parse_cell(str(data_row[col_idx]))
                result[code] = val if val is not None else config.NA_OUTPUT_VALUE
            else:
                result[code] = config.NA_OUTPUT_VALUE
        all_years[yr] = result
    return all_years


# ── Public entry point ────────────────────────────────────────────────────────

def extract(pdf_path):
    """
    Full extraction pipeline for one Purple Book PDF.

    Extracts ALL year rows from each section table so the master can be
    updated with any restated historical values from the latest source.

    Returns:
        (pdf_year: int, all_years: dict {year: {series_code: value_or_NA}})

    Raises:
        RuntimeError if no usable data could be extracted.
    """
    logger.info(f"=== extractor: {os.path.basename(pdf_path)} ===")

    # Detect PDF year from filename (adaptive)
    yr_m = re.search(r'(20\d{2})', os.path.basename(pdf_path))
    pdf_year = int(yr_m.group(1)) if yr_m else None

    master_data = _load_master()
    target_year = pdf_year  # extract the PDF's own year

    # Decoder ring uses ONLY years BEFORE the PDF year
    if target_year:
        decoder_master = {yr: v for yr, v in master_data.items() if yr < target_year}
    else:
        decoder_master = master_data

    logger.info(f"PDF year: {pdf_year}  target: {target_year}  "
                f"decoder years: {sorted(decoder_master.keys())}")

    # 1. Locate pages
    section_pages = _find_section_pages(pdf_path)

    # 2. Load camelot tables for those pages (+1)
    page_tables = _load_page_tables(pdf_path, section_pages)

    # 3. Identify columns and extract ALL years for each section
    all_years = {}  # {year: {code: value}}

    for section in ('asset_allocation', 'bond_splits', 'equity_splits'):
        tables = _tables_for(section, section_pages, page_tables)
        if not tables:
            logger.warning(f"{section}: no tables loaded")
            continue

        rows, col_map, ref_yr = _identify_columns(tables, section, decoder_master)

        if not col_map:
            logger.warning(f"{section}: could not identify any columns")
            continue

        logger.info(f"{section}: ref_year={ref_yr}, {len(col_map)} columns identified")

        section_years = _extract_all_years(rows, col_map)
        for yr, data in section_years.items():
            if yr not in all_years:
                all_years[yr] = {}
            all_years[yr].update(data)

    if not all_years:
        raise RuntimeError("extract(): no data extracted from any section")

    # Fill NA for any series not identified in any table (per year)
    for yr in all_years:
        for code, _, section, _ in config.SERIES_DEFINITIONS:
            if code not in all_years[yr]:
                all_years[yr][code] = config.NA_OUTPUT_VALUE

    years_found = sorted(all_years.keys())
    logger.info(f"=== extraction complete: pdf_year={pdf_year}, "
                f"{len(years_found)} years extracted: {years_found} ===")
    return pdf_year, all_years
