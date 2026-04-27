"""
Generates DATA .xls, META .xls, ZIP, updates master CSV, manages timestamped
and latest output folders.

DATA layout  (mirrors master CSV exactly):
    Row 0  : '' + series codes
    Row 1  : '' + descriptions
    Row 2+ : year + values  (all historical years, chronological)

META layout:
    Row 0  : column headers
    Row 1+ : one row per series (19 rows)
"""

import os
import re
import shutil
import logging
import zipfile
from datetime import datetime

import xlwt
import pandas as pd

import config

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mnemonic(code):
    """Strip frequency/dataset suffix from a series code to get the mnemonic."""
    return re.sub(r'\.A(\.\d+)?@\w+$', '', code)


META_COLUMNS = [
    'CODE', 'CODE_MNEMONIC', 'DESCRIPTION', 'FREQUENCY', 'MULTIPLIER',
    'AGGREGATION_TYPE', 'UNIT_TYPE', 'DATA_TYPE', 'DATA_UNIT',
    'SEASONALLY_ADJUSTED', 'ANNUALIZED', 'STATE', 'PROVIDER_MEASURE_URL',
    'PROVIDER', 'SOURCE', 'SOURCE_DESCRIPTION', 'COUNTRY', 'DATASET',
]

META_STATIC = {
    'FREQUENCY':            'A',
    'MULTIPLIER':           0.0,
    'AGGREGATION_TYPE':     'UNDEFINED',
    'UNIT_TYPE':            'LEVEL',
    'DATA_TYPE':            'PERCENT',
    'DATA_UNIT':            'PERCENT',
    'SEASONALLY_ADJUSTED':  'NSA',
    'ANNUALIZED':           False,
    'STATE':                'ACTIVE',
    'PROVIDER_MEASURE_URL': config.BASE_URL,
    'PROVIDER':             'AfricaAI',
    'SOURCE':               'PurpleBook',
    'SOURCE_DESCRIPTION':   'The Pension Protection Fund Purple Book',
    'COUNTRY':              'GBR',
    'DATASET':              'PPFPB',
}


# ── Master CSV ────────────────────────────────────────────────────────────────

def _read_master_raw():
    """Return the master CSV as a list-of-lists (all rows, no conversion)."""
    if not os.path.exists(config.MASTER_CSV):
        return None
    df = pd.read_csv(config.MASTER_CSV, header=None, dtype=str)
    return df.fillna('').values.tolist()


def update_master(all_years):
    """
    Update the master CSV with data for ALL extracted years.
    Overwrites existing year rows with new values (captures restatements),
    inserts new year rows, and preserves any years not in all_years.
    Returns the full updated rows (list-of-lists).
    """
    rows = _read_master_raw()

    if rows is None:
        # Bootstrap master from scratch
        codes_row = [''] + config.SERIES_CODES
        descs_row = [''] + config.SERIES_DESCRIPTIONS
        rows = [codes_row, descs_row]

    # Build lookup of existing data rows by year string
    existing = {}  # year_str -> row index in rows
    for i, r in enumerate(rows[2:], start=2):
        yr_str = str(r[0]).strip()
        if yr_str:
            existing[yr_str] = i

    updated = 0
    inserted = 0

    for year, data in all_years.items():
        year_str = str(year)
        new_row = [year_str] + [str(data.get(c, config.NA_OUTPUT_VALUE)) for c in config.SERIES_CODES]

        if year_str in existing:
            rows[existing[year_str]] = new_row
            updated += 1
        else:
            rows.append(new_row)
            inserted += 1

    # Write back (sort data rows by year so master stays ordered)
    header_rows = rows[:2]
    data_rows   = sorted(rows[2:], key=lambda r: int(r[0]) if str(r[0]).isdigit() else 0)
    all_rows    = header_rows + data_rows

    os.makedirs(config.MASTER_DIR, exist_ok=True)
    with open(config.MASTER_CSV, 'w', newline='', encoding='utf-8') as fh:
        import csv
        writer = csv.writer(fh)
        writer.writerows(all_rows)

    logger.info(f"Master CSV updated: {config.MASTER_CSV} "
                f"({len(data_rows)} data rows, {updated} overwritten, {inserted} new)")
    return all_rows


# ── XLS writers ──────────────────────────────────────────────────────────────

def _write_data_xls(path, master_rows):
    """Write DATA .xls from the full master rows (list-of-lists)."""
    wb = xlwt.Workbook()
    ws = wb.add_sheet('DATA')

    for r_idx, row in enumerate(master_rows):
        for c_idx, val in enumerate(row):
            if val == '' or val is None:
                ws.write(r_idx, c_idx, '')
                continue
            # Try writing as float for numeric cells (data rows col 1+)
            if r_idx >= 2 and c_idx >= 1 and val != config.NA_OUTPUT_VALUE:
                try:
                    ws.write(r_idx, c_idx, float(val))
                    continue
                except (ValueError, TypeError):
                    pass
            ws.write(r_idx, c_idx, val)

    wb.save(path)
    logger.info(f"DATA .xls written: {path}")


def _write_meta_xls(path):
    """Write META .xls using static metadata for all 19 series."""
    wb = xlwt.Workbook()
    ws = wb.add_sheet('META')

    # Header row
    for c_idx, col in enumerate(META_COLUMNS):
        ws.write(0, c_idx, col)

    # One row per series
    for r_idx, (code, desc, _, _) in enumerate(config.SERIES_DEFINITIONS, start=1):
        row_data = {
            'CODE':         code,
            'CODE_MNEMONIC': _mnemonic(code),
            'DESCRIPTION':  desc,
            **META_STATIC,
        }
        for c_idx, col in enumerate(META_COLUMNS):
            ws.write(r_idx, c_idx, row_data[col])

    wb.save(path)
    logger.info(f"META .xls written: {path}")


# ── ZIP ───────────────────────────────────────────────────────────────────────

def _make_zip(zip_path, data_path, meta_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(data_path, os.path.basename(data_path))
        zf.write(meta_path, os.path.basename(meta_path))
    logger.info(f"ZIP created: {zip_path}")


# ── Public entry point ────────────────────────────────────────────────────────

def generate_files(all_years):
    """
    Full file-generation step.

    1. Updates master CSV with ALL extracted years (overwrites restated values).
    2. Writes DATA .xls  (full history, from updated master).
    3. Writes META .xls  (static metadata).
    4. Zips DATA + META.
    5. Copies all three to output/latest/.

    Returns the timestamped output directory path.
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # ── Timestamped run folder ──────────────────────────────────────────────
    run_dir = os.path.join(config.OUTPUT_DIR, timestamp)
    os.makedirs(run_dir, exist_ok=True)

    # ── Step 1: Update master CSV ───────────────────────────────────────────
    master_rows = update_master(all_years)

    # ── Step 2: Build output file paths ────────────────────────────────────
    base        = f'{config.JOB_NAME}'
    data_name   = f'{base}_DATA_{timestamp}.xls'
    meta_name   = f'{base}_META_{timestamp}.xls'
    zip_name    = f'{base}_{timestamp}.zip'

    data_path   = os.path.join(run_dir, data_name)
    meta_path   = os.path.join(run_dir, meta_name)
    zip_path    = os.path.join(run_dir, zip_name)

    # ── Step 3: Write files ─────────────────────────────────────────────────
    _write_data_xls(data_path, master_rows)
    _write_meta_xls(meta_path)
    _make_zip(zip_path, data_path, meta_path)

    # ── Step 4: Copy to latest/ ─────────────────────────────────────────────
    latest_dir = os.path.join(config.OUTPUT_DIR, 'latest')
    os.makedirs(latest_dir, exist_ok=True)

    shutil.copy2(data_path, os.path.join(latest_dir, f'{base}_DATA_latest.xls'))
    shutil.copy2(meta_path, os.path.join(latest_dir, f'{base}_META_latest.xls'))
    shutil.copy2(zip_path,  os.path.join(latest_dir, f'{base}_latest.zip'))

    logger.info(f"Output in: {run_dir}")
    logger.info(f"Latest  in: {latest_dir}")
    return run_dir
