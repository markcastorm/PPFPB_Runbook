import sys
import logging

from scraper        import download
from extractor      import extract
from file_generator import generate_files

logger = logging.getLogger(__name__)


def main():
    """Run the full PPFPB pipeline. Returns 0 on success, 1 on failure."""
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    try:
        logger.info('=== PPFPB pipeline started ===')

        logger.info('Step 1: Downloading Purple Book PDF...')
        pdf_path, scraper_year = download()
        logger.info(f'  PDF: {pdf_path}  (year hint from scraper: {scraper_year})')

        logger.info('Step 2: Extracting data from PDF...')
        pdf_year, all_years = extract(pdf_path)
        logger.info(f'  Extracted pdf_year={pdf_year}, {len(all_years)} years: {sorted(all_years.keys())}')

        if not all_years:
            logger.error('No data extracted — aborting')
            return 1

        logger.info('Step 3: Generating output files...')
        out_dir = generate_files(all_years)
        logger.info(f'  Output: {out_dir}')

        logger.info('=== PPFPB pipeline completed successfully ===')
        return 0

    except Exception as exc:
        logger.exception(f'Pipeline failed: {exc}')
        return 1
