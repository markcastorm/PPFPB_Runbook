import os
import re
import sys
import time
import random
import logging
import requests
import subprocess
import urllib3
from datetime import datetime

import config

logger = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.ppf.co.uk/',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _human_delay(lo=0.8, hi=2.2):
    time.sleep(random.uniform(lo, hi))


def get_chrome_version():
    if sys.platform == 'win32':
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Google\Chrome\BLBeacon',
            )
            return int(winreg.QueryValueEx(key, 'version')[0].split('.')[0])
        except Exception:
            pass
    for cmd in ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']:
        try:
            out = subprocess.check_output(
                [cmd, '--version'], stderr=subprocess.DEVNULL
            ).decode()
            return int(out.strip().split()[-1].split('.')[0])
        except Exception:
            continue
    return None


def _build_driver(download_dir):
    import undetected_chromedriver as uc
    from selenium_stealth import stealth

    opts = uc.ChromeOptions()
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--lang=en-US,en;q=0.9')
    opts.add_experimental_option('prefs', {
        'download.default_directory': download_dir,
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
        'plugins.always_open_pdf_externally': True,
        'safebrowsing.enabled': True,
    })

    version = get_chrome_version()
    kwargs = {'options': opts, 'use_subprocess': True}
    if version:
        kwargs['version_main'] = version

    driver = uc.Chrome(**kwargs)

    stealth(
        driver,
        languages=['en-US', 'en'],
        vendor='Google Inc.',
        platform='Win32',
        webgl_vendor='Intel Inc.',
        renderer='Intel Iris OpenGL Engine',
        fix_hairline=True,
    )

    # Allow downloads in headless via CDP
    driver.execute_cdp_cmd(
        'Page.setDownloadBehavior',
        {'behavior': 'allow', 'downloadPath': download_dir},
    )
    return driver


def _handle_cookie_banner(driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    try:
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, 'onetrust-accept-btn-handler'))
        )
        _human_delay(0.5, 1.2)
        btn.click()
        logger.info('Cookie banner: accepted')
        _human_delay(0.8, 1.5)
    except Exception:
        logger.info('Cookie banner: not present or already dismissed')


def _extract_link_info(element):
    """Return (href, year) from a link/button element."""
    text = (element.get_attribute('textContent') or '').strip()
    href = element.get_attribute('href') or ''
    year_m = re.search(r'\b(20\d{2})\b', text)
    year = int(year_m.group(1)) if year_m else None
    return href, year


def _find_pdf_element(driver):
    """
    Locate the 'Download The Purple Book YEAR' link or button.
    Returns (element, href, year).
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    # Wait for the download text to appear anywhere on the page
    WebDriverWait(driver, config.WAIT_TIMEOUT).until(
        EC.presence_of_element_located((
            By.XPATH,
            "//*[contains(normalize-space(.), 'Download The Purple Book')]",
        ))
    )
    _human_delay(0.5, 1.0)

    # Prefer <a> with a direct PDF href
    for xpath in [
        "//a[contains(normalize-space(.), 'Download The Purple Book')]",
        "//button[contains(normalize-space(.), 'Download The Purple Book')]",
        "//*[contains(normalize-space(.), 'Download The Purple Book')]",
    ]:
        elements = driver.find_elements(By.XPATH, xpath)
        if elements:
            element = elements[0]
            href, year = _extract_link_info(element)
            logger.info(f"Found download element: text='{element.text.strip()}' href='{href}'")
            return element, href, year

    raise RuntimeError("'Download The Purple Book' link/button not found on page")


def _build_pdf_url(href):
    """Convert relative or absolute href to a full HTTPS URL."""
    if not href:
        return None
    if href.startswith('http'):
        return href
    return 'https://www.ppf.co.uk' + (href if href.startswith('/') else '/' + href)


def _requests_download(url, dest_path, cookies=None):
    """Download PDF via requests. Returns True on success."""
    try:
        resp = requests.get(
            url,
            headers=_HEADERS,
            cookies=cookies or {},
            stream=True,
            timeout=90,
            verify=False,
        )
        resp.raise_for_status()
        content_type = resp.headers.get('Content-Type', '')
        if 'html' in content_type and 'pdf' not in content_type:
            logger.warning(f"Response looks like HTML, not PDF (Content-Type: {content_type})")
            return False

        with open(dest_path, 'wb') as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)

        size = os.path.getsize(dest_path)
        if size < 50_000:
            logger.warning(f"Downloaded file is suspiciously small: {size} bytes")
            return False

        logger.info(f"Downloaded {size:,} bytes → {dest_path}")
        return True
    except Exception as exc:
        logger.warning(f"requests download failed: {exc}")
        return False


def _wait_for_download(download_dir, timeout=120):
    """Poll download_dir until a .pdf file appears (no partial .crdownload)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pdfs = [
            f for f in os.listdir(download_dir)
            if f.lower().endswith('.pdf') and not f.endswith('.crdownload')
        ]
        if pdfs:
            path = os.path.join(download_dir, pdfs[0])
            logger.info(f"Browser download complete: {path}")
            return path
        time.sleep(1)
    raise TimeoutError(f"PDF did not appear in '{download_dir}' within {timeout}s")


# ── Strategy 1: pure requests (no browser) ───────────────────────────────────

def _try_direct(run_dir):
    """
    Scrape the page with requests + BS4 — fastest, no browser overhead.
    Returns (pdf_path, year) or (None, None).
    """
    from bs4 import BeautifulSoup

    try:
        resp = requests.get(config.BASE_URL, headers=_HEADERS, timeout=30, verify=False)
        resp.raise_for_status()
    except Exception as exc:
        logger.info(f"Direct requests page fetch failed: {exc}")
        return None, None

    soup = BeautifulSoup(resp.text, 'html.parser')
    for tag in soup.find_all(['a', 'button']):
        text = tag.get_text(' ', strip=True)
        if 'Download The Purple Book' in text:
            href = tag.get('href', '')
            year_m = re.search(r'\b(20\d{2})\b', text)
            year = int(year_m.group(1)) if year_m else None
            if '.pdf' in href.lower():
                pdf_url = _build_pdf_url(href)
                filename = f'PurpleBook_{year}.pdf' if year else 'PurpleBook.pdf'
                dest = os.path.join(run_dir, filename)
                if _requests_download(pdf_url, dest):
                    return dest, year
    logger.info('Direct approach: no PDF link found in static HTML')
    return None, None


# ── Strategy 2: Selenium stealth ─────────────────────────────────────────────

def _try_selenium(run_dir):
    """
    Full Selenium stealth browser approach.
    Returns (pdf_path, year) or raises.
    """
    driver = None
    try:
        driver = _build_driver(run_dir)
        logger.info(f"Browser navigating to {config.BASE_URL}")
        driver.get(config.BASE_URL)
        _human_delay(2.0, 4.0)

        _handle_cookie_banner(driver)

        element, href, year = _find_pdf_element(driver)

        # If element has a direct PDF href, prefer requests download
        if href and '.pdf' in href.lower():
            pdf_url = _build_pdf_url(href)
            filename = f'PurpleBook_{year}.pdf' if year else 'PurpleBook.pdf'
            dest = os.path.join(run_dir, filename)

            # Use session cookies so the server recognises consent etc.
            session_cookies = {c['name']: c['value'] for c in driver.get_cookies()}
            if _requests_download(pdf_url, dest, session_cookies):
                return dest, year

        # Fallback: actually click and let the browser download
        logger.info('Clicking download element and waiting for browser download')
        _human_delay(0.5, 1.2)
        driver.execute_script('arguments[0].click();', element)
        _human_delay(1.0, 2.0)

        pdf_path = _wait_for_download(run_dir, timeout=120)

        if year is None:
            m = re.search(r'(20\d{2})', os.path.basename(pdf_path))
            year = int(m.group(1)) if m else None

        return pdf_path, year

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ── Public entry point ────────────────────────────────────────────────────────

def download():
    """
    Download the latest Purple Book PDF.
    Returns (pdf_path, year: int).
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(config.DOWNLOAD_DIR, timestamp)
    os.makedirs(run_dir, exist_ok=True)

    if config.USE_DIRECT_REQUESTS:
        logger.info('=== Scraper: trying direct requests approach ===')
        pdf_path, year = _try_direct(run_dir)
        if pdf_path:
            logger.info(f'Direct download succeeded: year={year}, path={pdf_path}')
            return pdf_path, year
    else:
        logger.info('=== Scraper: direct requests disabled in config ===')

    logger.info('=== Scraper: falling back to Selenium stealth ===')
    pdf_path, year = _try_selenium(run_dir)
    logger.info(f'Selenium download succeeded: year={year}, path={pdf_path}')
    return pdf_path, year
