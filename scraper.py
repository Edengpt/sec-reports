import re
import requests
from datetime import datetime, timedelta
from database import report_exists, insert_report, clear_old_reports

# SEC EDGAR full-text search API (EFTS)
EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# SEC requires a User-Agent with contact info
HEADERS = {
    "User-Agent": "SEC-Reports-Monitor contact@example.com",
    "Accept": "application/json",
}

# 8-K item number descriptions
ITEM_DESCRIPTIONS = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.03": "Creation of a Direct Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

# Search terms to query EDGAR with
SEARCH_TERMS = [
    '"material definitive agreement"',
    '"contract award"',
    '"awarded a contract"',
    '"purchase order"',
    '"government contract"',
    '"supply agreement"',
    '"new customer"',
    '"strategic partnership"',
    '"joint venture"',
    '"collaboration agreement"',
    '"license agreement"',
    '"task order"',
    '"defense contract"',
]

# Exclude filings that ONLY have these item numbers (no relevant items)
EXCLUDE_ONLY_ITEMS = {"1.02", "1.03", "2.05", "2.06", "5.02", "5.03"}

# Relevant item numbers we want to see
RELEVANT_ITEMS = {"1.01", "2.01", "7.01", "8.01"}


def parse_company_and_ticker(display_name):
    """Extract company name and ticker from EDGAR display_name format.
    e.g. 'EchoStar CORP  (SATS)  (CIK 0001415404)' -> ('EchoStar CORP', 'SATS')
    """
    if not display_name:
        return "", ""
    # Remove CIK part
    name = re.sub(r"\s*\(CIK\s+\d+\)\s*", "", display_name).strip()
    # Extract ticker
    ticker_match = re.search(r"\(([A-Z0-9, ]+)\)", name)
    ticker = ticker_match.group(1).split(",")[0].strip() if ticker_match else ""
    # Clean company name
    company = re.sub(r"\s*\([A-Z0-9, ]+\)\s*", "", name).strip()
    return company, ticker


def build_filing_url(adsh, cik):
    """Build URL to the SEC filing index page."""
    if not adsh or not cik:
        return ""
    # Remove leading zeros from CIK
    cik_clean = cik.lstrip("0")
    # Accession number without dashes for the path
    adsh_nodash = adsh.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/{adsh_nodash}/{adsh}-index.htm"


def build_title(items):
    """Build a human-readable title from 8-K item numbers."""
    if not items:
        return "8-K Filing"
    descriptions = []
    for item in items:
        desc = ITEM_DESCRIPTIONS.get(item, f"Item {item}")
        descriptions.append(desc)
    return " | ".join(descriptions)


def is_relevant_filing(items):
    """Check if filing has at least one relevant item (not only exclusion items)."""
    item_set = set(items) if items else set()
    # If the filing only contains excluded items, skip it
    if item_set and item_set.issubset(EXCLUDE_ONLY_ITEMS):
        return False
    return True


def fetch_filings(query, date_from, date_to, start=0):
    """Fetch filings from SEC EDGAR full-text search API."""
    params = {
        "q": query,
        "dateRange": "custom",
        "startdt": date_from.strftime("%Y-%m-%d"),
        "enddt": date_to.strftime("%Y-%m-%d"),
        "forms": "8-K",
        "from": start,
    }

    try:
        resp = requests.get(EDGAR_SEARCH_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  Error fetching '{query}': {e}")
        return None


def process_reports(days_back=1):
    """Fetch and save matching filings from SEC EDGAR."""
    date_from = datetime.now() - timedelta(days=days_back)
    date_to = datetime.now()

    print(f"Fetching filings from {date_from.date()} to {date_to.date()}...")

    total_new = 0
    total_excluded = 0
    seen_ids = set()

    for term in SEARCH_TERMS:
        start = 0
        while True:
            data = fetch_filings(term, date_from, date_to, start)
            if not data:
                break

            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            for hit in hits:
                source = hit.get("_source", {})
                adsh = source.get("adsh", "")

                if not adsh or adsh in seen_ids:
                    continue
                seen_ids.add(adsh)

                if report_exists(adsh):
                    continue

                # Parse company info from first display_name
                display_names = source.get("display_names", [])
                display_name = display_names[0] if display_names else ""
                company, ticker = parse_company_and_ticker(display_name)

                # Get filing metadata
                items = source.get("items", [])
                filing_type = source.get("file_type", "") or source.get("form", "8-K")
                filed_date = source.get("file_date", "")

                # Build title from items
                title = build_title(items)

                # Filter out irrelevant filings by item type
                if not is_relevant_filing(items):
                    total_excluded += 1
                    continue

                # Build filing URL
                ciks = source.get("ciks", [])
                cik = ciks[0] if ciks else ""
                filing_url = build_filing_url(adsh, cik)

                insert_report(
                    {
                        "id": adsh,
                        "company_name": company,
                        "ticker": ticker,
                        "title": title,
                        "filing_type": filing_type,
                        "filed_date": filed_date,
                        "url": filing_url,
                        "matched_keywords": term.strip('"'),
                    }
                )
                total_new += 1
                print(f"  [NEW] {company} ({ticker}): {title}")

            total_hits = data.get("hits", {}).get("total", {}).get("value", 0)
            start += len(hits)
            if start >= total_hits or len(hits) < 10:
                break

    # Cleanup old reports
    clear_old_reports(days=30)

    print(f"Done. {total_new} new, {total_excluded} excluded.")
    return total_new


if __name__ == "__main__":
    from database import init_db

    init_db()
    process_reports(days_back=30)
