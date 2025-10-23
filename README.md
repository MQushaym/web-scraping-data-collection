# Web Scraping for Data Collection

This repository contains a Python script designed to efficiently and responsibly scrape publicly available structured information from a specific public portal. The primary goal is to collect the raw HTML content of individual detail pages for further processing and analysis.

**Note on Privacy:** The target website's base URL is intentionally omitted from the script's code. The script requires the user to input this information interactively upon execution to ensure responsible use and respect privacy.


---

## ⚙️ Methodology & Key Features

This script showcases several best practices for robust and polite web scraping:

1.  **Interactive Configuration:**
    * The script interactively prompts the user for the target **base URL** and **output directory** upon execution using Python's `input()` function. This prevents hardcoding sensitive information and ensures user awareness.

2.  **Respectful Scraping (`robots.txt` & Delays):**
    * It strictly adheres to web standards by automatically fetching and parsing the target site's `robots.txt` file using `urllib.robotparser`.
    * Before fetching any page, it checks if the path is allowed for the script's User-Agent.
    * Random delays (`random.uniform(DELAY_MIN, DELAY_MAX)`) are implemented between all HTTP requests.

3.  **Resilience & Error Handling:**
    * A `polite_get` function handles HTTP requests using `requests.Session` with automatic retries and exponential backoff for temporary errors (5xx, 429).
    * Robust error logging (`logging`) tracks progress and issues.

4.  **Dynamic Pagination Handling:**
    * The script can automatically detect the total number of pages (`find_last_page_number`) if the end page is not specified during execution (though the current implementation defaults to auto-detect).

5.  **Efficient Data Extraction (`BeautifulSoup`):**
    * Uses `BeautifulSoup4` with `lxml` to efficiently extract unique identifiers and detail page URLs from listing pages (`parse_listing_for_items`).

6.  **Checkpointing / Resumability:**
    * Skips pages if the corresponding output JSON file (`page_XXX.json`) already exists, allowing scraping to be resumed.

7.  **Structured Output:**
    * Saves the raw HTML content of detail pages into JSON files (`save_page_json`), organized by page number, mapping unique identifiers to HTML.

---

## 🛠️ Requirements

* Python 3.6+
* Required Python libraries (install via `pip install -r requirements.txt`):
    * `requests`
    * `beautifulsoup4`
    * `lxml`
    * `fake-useragent` (Optional, for User-Agent randomization)

---

## 🚀 Usage

When you run the script, it will interactively ask for the necessary information:

1.  **Run the script:**
    ```bash
    python scraper.py
    ```

2.  **Enter Base URL:**
    The script will prompt:
    `Please enter the target base URL (e.g., https://example.com):`
    Enter the full base URL of the site you intend to scrape.

3.  **Enter Output Directory:**
    The script will prompt:
    `Please enter the directory to save output files (e.g., ./scraped_data):`
    Enter the path where you want the JSON files to be saved. The script will create the directory if it doesn't exist.

4.  **Scraping Begins:**
    The script will then proceed with the scraping process, using the provided URL and directory. It will attempt to auto-detect the last page number.

**Important Note:** This script was tailored for the specific structure of a particular public portal (as of late 2025). Significant modifications might be needed for other websites or if the site's structure changes. Always scrape responsibly.

---

## 🔗 Link to Dataset

The clean, processed dataset resulting from this scraping effort is publicly available on Kaggle:
**[https://www.kaggle.com/datasets/meshalfalah/ksa-drug-database-metadata-pils-and-spcs-aren](https://www.kaggle.com/datasets/meshalfalah/ksa-drug-database-metadata-pils-and-spcs-aren)**
