import os

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')
OUTPUT_DIR   = os.path.join(BASE_DIR, 'output')
MASTER_DIR   = os.path.join(BASE_DIR, 'Master_Data')
MASTER_CSV   = os.path.join(MASTER_DIR, 'Master_PPFPB_DATA.csv')

# ── Source ────────────────────────────────────────────────────────────────────
BASE_URL = 'https://www.ppf.co.uk/purple-book'

# ── Browser ───────────────────────────────────────────────────────────────────
USE_DIRECT_REQUESTS = True   # Try fast requests+BS4 before Selenium; False = skip to Selenium
HEADLESS_MODE       = True
WAIT_TIMEOUT        = 30

# ── Job identity ──────────────────────────────────────────────────────────────
JOB_NAME = 'PPFPB'

# ── NA / blank handling (edit here to change behaviour) ──────────────────────
NA_SOURCE_VALUES = ['n/a', 'N/A', 'na', 'NA', '-', '–', '—', '']
BLANK_AS_NA      = True
NA_OUTPUT_VALUE  = 'NA'

# ── Series definitions (absolute order — never changes) ───────────────────────
# Tuple: (series_code, description, section, row_label_canonical)
#   section: 'asset_allocation' | 'bond_splits' | 'equity_splits'
SERIES_DEFINITIONS = [
    (
        'GBRPRIVATEPENSIONFUNDS.LISTEDANDPRIVATEEQUITIES.ACTUALALLOCATION.NONE.A.1@PURPLEBOOK',
        'Weighted average asset allocation in total assets, Equities',
        'asset_allocation',
        'Equities',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.BONDS.ACTUALALLOCATION.NONE.A.1@PURPLEBOOK',
        'Weighted average asset allocation in total assets, Bonds',
        'asset_allocation',
        'Bonds',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.ALTERNATIVES.ACTUALALLOCATION.NONE.A.1@PURPLEBOOK',
        'Weighted average asset allocation in total assets, Other Investments',
        'asset_allocation',
        'Other Investments',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.REALESTATE.ACTUALALLOCATION.NONE.A.1@PURPLEBOOK',
        'Weighted average asset allocation in total assets, Property',
        'asset_allocation',
        'Property',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.CASH.ACTUALALLOCATION.NONE.A.1@PURPLEBOOK',
        'Weighted average asset allocation in total assets, Cash and Deposits',
        'asset_allocation',
        'Cash and Deposits',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.INSURANCE.ACTUALALLOCATION.NONE.A.1@PURPLEBOOK',
        'Weighted average asset allocation in total assets, Insurance policies',
        'asset_allocation',
        'Insurance policies',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.HEDGEFUNDS.ACTUALALLOCATION.NONE.A.1@PURPLEBOOK',
        'Weighted average asset allocation in total assets, Hedge Funds',
        'asset_allocation',
        'Hedge Funds',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.DEVIGROWFUND.ACTUALALLOCATION.NONE.A.1@PURPLEBOOK',
        'Weighted average asset allocation in total assets, Diversified growth funds',
        'asset_allocation',
        'Diversified growth funds',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.ABSRETURN.ACTUALALLOCATION.NONE.A.1@PURPLEBOOK',
        'Weighted average asset allocation in total assets, Absolute returns',
        'asset_allocation',
        'Absolute returns',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.ANNUITIES.ACTUALALLOCATION.NONE.A.1@PURPLEBOOK',
        'Weighted average asset allocation in total assets, Annuities',
        'asset_allocation',
        'Annuities',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.OTHER.ACTUALALLOCATION.NONE.A.1@PURPLEBOOK',
        'Weighted average asset allocation in total assets, Miscellaneous',
        'asset_allocation',
        'Miscellaneous',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.BONDS.WEIGHTEDAVG.GOVERNMENTFIXEDINTEREST.A@PURPLEBOOK',
        'Bonds splits, Bonds, Weighted average, Government fixed interest',
        'bond_splits',
        'Government fixed interest',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.BONDS.WEIGHTEDAVG.CORPORATEFIXEDINTEREST.A@PURPLEBOOK',
        'Bonds splits, Bonds, Weighted average, Corporate fixed interest',
        'bond_splits',
        'Corporate fixed interest',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.BONDS.WEIGHTEDAVG.INDEXLINKED.A@PURPLEBOOK',
        'Bonds splits, Bonds, Weighted average, Index-linked',
        'bond_splits',
        'Index-linked',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.EQUITIES.WEIGHTEDAVG.UKQUOTED.A@PURPLEBOOK',
        'Equity splits, Equities, Weighted average, UK quoted',
        'equity_splits',
        'UK quoted',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.EQUITIES.WEIGHTEDAVG.OVERSEASQUOTED.A@PURPLEBOOK',
        'Equity splits, Equities, Weighted average, Overseas quoted',
        'equity_splits',
        'Overseas quoted',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.EQUITIES.WEIGHTEDAVG.DEVELOPEDMARKETS.A@PURPLEBOOK',
        'Equity splits, Equities, Weighted average, Developed markets',
        'equity_splits',
        'Developed markets',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.EQUITIES.WEIGHTEDAVG.EMERGINGMARKETS.A@PURPLEBOOK',
        'Equity splits, Equities, Weighted average, Emerging markets',
        'equity_splits',
        'Emerging markets',
    ),
    (
        'GBRPRIVATEPENSIONFUNDS.EQUITIES.WEIGHTEDAVG.UNQUOTEDPRIVATE.A@PURPLEBOOK',
        'Equity splits, Equities, Weighted average, Unquoted/Private',
        'equity_splits',
        'Unquoted/Private',
    ),
]

# Derived lookups (built once at import)
SERIES_CODES        = [s[0] for s in SERIES_DEFINITIONS]
SERIES_DESCRIPTIONS = [s[1] for s in SERIES_DEFINITIONS]

# ── Row-label aliases per section ─────────────────────────────────────────────
# Maps any variant found in PDF (lowercased, stripped) → canonical label above.

ASSET_ALLOC_ALIASES = {
    'equities':                  'Equities',
    'bonds':                     'Bonds',
    'other investments':         'Other Investments',
    'alternatives':              'Other Investments',
    'property':                  'Property',
    'real estate':               'Property',
    'cash and deposits':         'Cash and Deposits',
    'cash':                      'Cash and Deposits',
    'insurance policies':        'Insurance policies',
    'insurance':                 'Insurance policies',
    'hedge funds':               'Hedge Funds',
    'hedge fund':                'Hedge Funds',
    'diversified growth funds':  'Diversified growth funds',
    'diversified growth fund':   'Diversified growth funds',
    'dgf':                       'Diversified growth funds',
    'absolute returns':          'Absolute returns',
    'absolute return':           'Absolute returns',
    'annuities':                 'Annuities',
    'miscellaneous':             'Miscellaneous',
    'other':                     'Miscellaneous',
}

BOND_LABEL_ALIASES = {
    'government fixed interest':   'Government fixed interest',
    'government fixed-interest':   'Government fixed interest',
    'government fixed interest ':  'Government fixed interest',
    'government':                  'Government fixed interest',
    'corporate fixed interest':    'Corporate fixed interest',
    'corporate fixed-interest':    'Corporate fixed interest',
    # 2023+ naming change
    'corporate – public markets':  'Corporate fixed interest',
    'corporate - public markets':  'Corporate fixed interest',
    'corporate -  public markets': 'Corporate fixed interest',
    'corporate- public markets':   'Corporate fixed interest',
    'corporate public markets':    'Corporate fixed interest',
    'corporate–public markets':    'Corporate fixed interest',
    'index-linked':                'Index-linked',
    'index linked':                'Index-linked',
    'index - linked':              'Index-linked',
}

EQUITY_LABEL_ALIASES = {
    'uk quoted':           'UK quoted',
    'uk listed':           'UK quoted',
    'uk equities':         'UK quoted',
    'overseas quoted':     'Overseas quoted',
    'overseas listed':     'Overseas quoted',
    'developed markets':   'Developed markets',
    'emerging markets':    'Emerging markets',
    'unquoted/private':    'Unquoted/Private',
    'unquoted / private':  'Unquoted/Private',
    'unquoted':            'Unquoted/Private',
    'private equity':      'Unquoted/Private',
}

# ── Metadata defaults (used by file_generator) ────────────────────────────────
METADATA_DEFAULTS = {
    'FREQUENCY':    'A',
    'MULTIPLIER':   '1',
    'UNIT':         '%',
    'COUNTRY':      'GBR',
    'SOURCE':       'PPF',
    'PROVIDER':     'AfricaAI',
    'STATUS':       'A',
    'DECIMALS':     '1',
    'CALENDAR':     'A',
    'DATABASE':     'PURPLEBOOK',
}
