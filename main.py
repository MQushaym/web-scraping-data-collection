import json
import random
import time
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Dict, List, Tuple, Optional
import requests
from bs4 import BeautifulSoup
import urllib.robotparser as robotparser

# =========================
# General Settings
# =========================
LIST_URL_TEMPLATE = BASE_URL + "/home/DrugSearch?page={page}"  # Pagination page
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REQUEST_TIMEOUT = 30
DELAY_MIN, DELAY_MAX = 0.6, 1.2      # Random delay between requests (politeness)
MAX_LIST_RETRIES = 3
MAX_DETAIL_RETRIES = 3
STOP_ON_CONSECUTIVE_LIST_FAILS = 5   # Stop if we fail to fetch this many consecutive list pages

# =========================
# Simple Logging Setup
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# =========================
# User-Agent Handling
# =========================
def get_user_agent() -> str:
    """
    Attempts to use fake_useragent if available, otherwise falls back to a default UA.
    """
    try:
        from fake_useragent import UserAgent
        return UserAgent().random
    except Exception:
        return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# =========================
# robots.txt Parser
# =========================
def init_robots_parser(base_url: str) -> robotparser.RobotFileParser:
    """Initializes a robotparser for the given base URL."""
    rp = robotparser.RobotFileParser()
    robots_url = urljoin(base_url, "/robots.txt")
    try:
        rp.set_url(robots_url)
        rp.read()
        logging.info("Loaded robots.txt from %s", robots_url)
    except Exception as e:
        logging.warning("Couldn't load robots.txt (%s). Proceeding cautiously.", e)
    return rp

def can_fetch(rp: robotparser.RobotFileParser, ua: str, path_or_url: str) -> bool:
    """
    Checks if a given path or full URL is allowed by robots.txt.
    """
    try:
        # path_or_url can be a full URL or a relative path
        full_path = path_or_url if path_or_url.startswith("http") else urljoin(BASE_URL, path_or_url)
        return rp.can_fetch(ua, full_path)
    except Exception:
        # Fail open (assume allowed) if parser fails
        return True

# =========================
# HTTP Session & Polite GET
# =========================
def build_session() -> requests.Session:
    """Builds a requests.Session with default headers."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": get_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ar,en;q=0.9",
        "Connection": "keep-alive",
    })
    return s

def polite_get(session: requests.Session, url: str, retries: int) -> Optional[requests.Response]:
    """
    Performs a GET request with random delay and exponential backoff on temporary errors.
    """
    for attempt in range(1, retries + 1):
        try:
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)

            # Retry on server errors or rate limiting
            if resp.status_code in (429,) or resp.status_code >= 500:
                backoff = 1.5 * attempt
                logging.warning("Got %s from %s. Backoff %.1fs", resp.status_code, url, backoff)
                time.sleep(backoff)
                continue
            
            return resp
        
        except requests.RequestException as e:
            backoff = 1.5 * attempt
            logging.warning("Request error on %s (%s). Backoff %.1fs", url, e, backoff)
            time.sleep(backoff)
            
    logging.error("Failed after %d retries: %s", retries, url)
    return None

# =========================
# Parser: Listing Page (Collects Registration Nos. & Detail URLs)
# =========================
def parse_listing_for_items(html: str) -> List[Tuple[str, str]]:
    """
    Returns [(registration_number, detail_url_absolute), ...]
    based on the table inside div.table-responsive
    - First <td> = registration number
    - 'View' column contains <a href="/home/Result?drugId=XXXX">
    """
    soup = BeautifulSoup(html, "lxml")
    tbody = soup.select_one("div.table-responsive table.table.s-row tbody")
    if not tbody:
        logging.warning("Couldn't find results <tbody> in listing page.")
        return []

    items = []
    for tr in tbody.select("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        
        reg_no = (tds[0].get_text(strip=True) or "").strip()
        view_link = tds[-1].select_one("a[href]")
        
        if not reg_no or not view_link:
            continue
            
        detail_url = urljoin(BASE_URL, view_link["href"])
        items.append((reg_no, detail_url))
        
    return items

def find_last_page_number(html: str) -> Optional[int]:
    """
    Tries to detect the last page number from the pagination bar:
    - Searches inside <ul class="pagination"> for the last <a> with a number.
    - If the current page is a <span>, take the max number found.
    """
    soup = BeautifulSoup(html, "lxml")
    ul = soup.select_one("ul.pagination")
    if not ul:
        return None

    nums = []
    for a in ul.find_all("a", href=True):
        txt = a.get_text(strip=True)
        if txt.isdigit():
            nums.append(int(txt))
    
    # If no <a> numbers, sometimes the current page is in a <span>
    sp = ul.find("span")
    if sp and sp.get_text(strip=True).isdigit():
        nums.append(int(sp.get_text(strip=True)))
        
    return max(nums) if nums else None

# =========================
# Detail HTML Fetcher
# =========================
def fetch_detail_html(session: requests.Session, detail_url: str) -> Optional[str]:
    """Fetches the raw HTML content of a single detail page."""
    resp = polite_get(session, detail_url, retries=MAX_DETAIL_RETRIES)
    if not resp or resp.status_code != 200:
        return None
    return resp.text

# =========================
# Single Page Storage
# =========================
def save_page_json(page_index: int, mapping: Dict[str, str]) -> Path:
    """Saves a dictionary of {reg_no: html_content} to a JSON file."""
    fname = OUTPUT_DIR / f"page_{page_index:03d}.json"
    with fname.open("w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False)
    logging.info("Saved %s (%d items)", fname, len(mapping))
    return fname

# =========================
# Page Processor (Fetches details and saves file)
# =========================
def process_one_page(session: requests.Session, rp: robotparser.RobotFileParser, ua: str, page_index: int) -> bool:
    """
    Returns True if the page file was saved (even if some items failed),
    False if the listing page itself failed to fetch.
    """
    list_url = LIST_URL_TEMPLATE.format(page=page_index)

    # Check robots.txt for the listing path
    if not can_fetch(rp, ua, "/home/DrugSearch"):
        logging.error("robots disallows /home/DrugSearch — aborting page %d", page_index)
        return False

    logging.info("Fetching listing page %d: %s", page_index, list_url)
    resp = polite_get(session, list_url, retries=MAX_LIST_RETRIES)
    if not resp or resp.status_code != 200:
        logging.error("Failed listing page %d", page_index)
        return False

    items = parse_listing_for_items(resp.text)
    logging.info("Page %d: found %d items", page_index, len(items))
    if not items:
        # This could be the last page, which might be empty/unexpected
        logging.warning("No items found on page %d", page_index)

    # Fetch details for each item and put them in a map
    result_map: Dict[str, str] = {}
    for reg_no, detail_url in items:
        
        # Check robots.txt for the detail path (usually /home/Result)
        path = urlparse(detail_url).path
        if not can_fetch(rp, ua, path):
            logging.warning("robots disallows %s — skip", detail_url)
            continue

        html = fetch_detail_html(session, detail_url)
        if html:
            result_map[reg_no] = html

    save_page_json(page_index, result_map)
    return True

# =========================
# Range Runner (with auto-detection and checkpointing)
# =========================
def run_range(start_page: int = 1, end_page: Optional[int] = None) -> None:
    """
    - If end_page=None: Detects the last page from the first fetched page.
    - Skips any pre-existing files (automatic checkpointing).
    - Stops if too many consecutive listing page failures occur.
    """
    ua = get_user_agent()
    rp = init_robots_parser(BASE_URL)

    # Check general paths once
    if not can_fetch(rp, ua, "/home/DrugSearch"):
        logging.error("robots disallows /home/DrugSearch — abort.")
        return
    if not can_fetch(rp, ua, "/home/Result"):
        logging.error("robots disallows /home/Result — abort.")
        return

    session = build_session()
    consecutive_list_fails = 0

    # If end_page is unknown, fetch page 1 to auto-detect the last page
    if end_page is None:
        logging.info("end_page not set. Attempting to auto-detect last page...")
        first_url = LIST_URL_TEMPLATE.format(page=start_page)
        resp = polite_get(session, first_url, retries=MAX_LIST_RETRIES)
        if not resp or resp.status_code != 200:
            logging.error("Failed to fetch start page %d to detect last page.", start_page)
            return
            
        last = find_last_page_number(resp.text)
        if not last:
            logging.warning("Couldn't detect last page automatically; will assume '%d' only.", start_page)
            last = start_page
        end_page = last
        logging.info("Detected last page: %d", end_page)

        # Since we already fetched page 1 for detection, let's process it:
        # If its file isn't saved, process it. Otherwise, skip.
        out_file = OUTPUT_DIR / f"page_{start_page:03d}.json"
        if out_file.exists():
            logging.info("Skip page %d (already exists)", start_page)
        else:
            logging.info("Processing pre-fetched page %d...", start_page)
            # We assume the items from the fetched page 'resp.text' should be processed here.
            # (Note: The original code logic re-fetches the page inside process_one_page, which is fine)
            ok = process_one_page(session, rp, ua, start_page) 
            if not ok:
                consecutive_list_fails += 1
            else:
                consecutive_list_fails = 0
        start_page += 1  # Continue after the first page

    # Loop through the rest of the pages
    for page in range(start_page, end_page + 1):
        out_file = OUTPUT_DIR / f"page_{page:03d}.json"
        if out_file.exists():
            logging.info("Skip page %d (already exists)", page)
            continue

        ok = process_one_page(session, rp, ua, page)
        
        if not ok:
            consecutive_list_fails += 1
            logging.warning("Consecutive listing failures: %d", consecutive_list_fails)
            if consecutive_list_fails >= STOP_ON_CONSECUTIVE_LIST_FAILS:
                logging.error("Too many consecutive listing failures. Stopping.")
                break
        else:
            consecutive_list_fails = 0

# =========================
# Main Execution
# =========================
if __name__ == "__main__":
    
    # --- Get Required Inputs from User ---
    
    # Get Base URL
    while True:
        user_base_url = input("Please enter the target base URL (e.g., https://example.com): ").strip()
        if user_base_url.startswith("http://") or user_base_url.startswith("https://"):
            BASE_URL = user_base_url
            break
        else:
            print("Invalid URL format. Please include http:// or https://")
            
    # Get Output Directory
    while True:
        user_output_dir = input("Please enter the directory to save output files (e.g., ./sfda_data): ").strip()
        try:
            OUTPUT_DIR = Path(user_output_dir)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True) # Try creating it
            break
        except Exception as e:
            print(f"Error creating directory '{user_output_dir}': {e}. Please try a different path.")

    # --- Set up global variables based on input ---
    LIST_URL_TEMPLATE = BASE_URL.rstrip('/') + "/home/DrugSearch?page={page}" 

    logging.info(f"Target Base URL set to: {BASE_URL}")
    logging.info(f"Output Directory set to: {OUTPUT_DIR}")

    # --- Run the scraper ---
    # You can still add argparse here for optional start/end pages if needed,
    # or just run with auto-detect by default.
    
    # Example: Run with auto-detection for end page
    print("\nStarting the scraping process...")
    run_range(start_page=1, end_page=None) 
    
    # Example: Ask user for start/end pages too (optional)
    # try:
    #     start = int(input("Enter start page (default 1): ") or "1")
    #     end_str = input("Enter end page (leave blank for auto-detect): ")
    #     end = int(end_str) if end_str else None
    #     print("\nStarting the scraping process...")
    #     run_range(start_page=start, end_page=end)
    # except ValueError:
    #     print("Invalid page number entered. Exiting.")
        
    print("\nScraping process finished.")
