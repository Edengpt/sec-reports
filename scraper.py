import re
import time
import requests
from datetime import datetime, timedelta
from database import report_exists, insert_report, clear_old_reports

# SEC EDGAR full-text search API (EFTS)
EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EXCHANGE_DATA_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

# SEC requires a User-Agent with contact info
HEADERS = {
    "User-Agent": "SEC-Reports-Monitor contact@example.com",
    "Accept": "application/json",
}

# Only include companies from these exchanges
ALLOWED_EXCHANGES = {"NYSE", "AMEX", "ARCA", "Nasdaq"}

# Cache: CIK -> exchange
_exchange_cache = {}

# ── Catalyst categories ──────────────────────────────────────────────
# Each category has: Hebrew name, form types to search, search terms,
# and optional exclude phrases.

CATALYSTS = [
    {
        "category": "קניות אינסיידרים",
        "forms": "4",
        "terms": ['"Purchase"', '"bought"'],
        "exclude": ["sale", "disposed", "gift"],
    },
    {
        "category": "משקיעים אקטיביסטים",
        "forms": "SC 13D,SC 13D/A",
        "terms": ['*'],
        "exclude": [],
    },
    {
        "category": "אישורי FDA",
        "forms": "8-K,6-K",
        "terms": [
            '"FDA approval"',
            '"FDA approved"',
            '"FDA clearance"',
            '"FDA cleared"',
            '"breakthrough designation"',
            '"fast track designation"',
        ],
        "exclude": [],
    },
    {
        "category": "מיזוגים ורכישות",
        "forms": "8-K,SC TO-T,SC TO-C,DEFM14A",
        "terms": [
            '"merger agreement"',
            '"acquisition of"',
            '"tender offer"',
            '"going private"',
            '"business combination"',
        ],
        "exclude": [],
    },
    {
        "category": "חוזים וזכיות",
        "forms": "8-K",
        "terms": [
            '"contract award"',
            '"awarded a contract"',
            '"government contract"',
            '"defense contract"',
            '"task order"',
            '"purchase order"',
        ],
        "exclude": ["termination", "terminated"],
    },
    {
        "category": "הסכמים ושיתופי פעולה",
        "forms": "8-K",
        "terms": [
            '"strategic partnership"',
            '"strategic alliance"',
            '"collaboration agreement"',
            '"joint venture"',
            '"license agreement"',
            '"supply agreement"',
        ],
        "exclude": ["termination", "terminated"],
    },
    {
        "category": "רכישה עצמית (Buyback)",
        "forms": "8-K",
        "terms": [
            '"share repurchase"',
            '"stock repurchase"',
            '"buyback program"',
            '"repurchase program"',
        ],
        "exclude": [],
    },
    {
        "category": "הפתעות ברווחים",
        "forms": "8-K",
        "terms": [
            '"exceeded expectations"',
            '"beat estimates"',
            '"record revenue"',
            '"record earnings"',
            '"raised guidance"',
            '"raises guidance"',
            '"increased guidance"',
            '"raises full-year"',
        ],
        "exclude": [],
    },
    {
        "category": "Spinoff / פיצול חברה",
        "forms": "8-K",
        "terms": [
            '"spin-off"',
            '"spinoff"',
            '"spin off"',
            '"separation of"',
        ],
        "exclude": [],
    },
]


def load_exchange_data():
    """Load CIK-to-exchange mapping from SEC."""
    global _exchange_cache
    if _exchange_cache:
        return
    try:
        print("Loading exchange data from SEC...")
        resp = requests.get(EXCHANGE_DATA_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for row in data.get("data", []):
            cik = str(row[0])
            exchange = row[3] if len(row) > 3 else None
            if exchange:
                _exchange_cache[cik] = exchange
        print(f"  Loaded {len(_exchange_cache)} companies with exchange info.")
    except Exception as e:
        print(f"  Error loading exchange data: {e}")


def is_on_allowed_exchange(cik):
    """Check if a CIK is listed on an allowed exchange."""
    cik_clean = cik.lstrip("0")
    exchange = _exchange_cache.get(cik_clean, "")
    return exchange in ALLOWED_EXCHANGES


def parse_company_and_ticker(display_name):
    """Extract company name and ticker from EDGAR display_name format."""
    if not display_name:
        return "", ""
    name = re.sub(r"\s*\(CIK\s+\d+\)\s*", "", display_name).strip()
    ticker_match = re.search(r"\(([A-Z0-9, ]+)\)", name)
    ticker = ticker_match.group(1).split(",")[0].strip() if ticker_match else ""
    company = re.sub(r"\s*\([A-Z0-9, ]+\)\s*", "", name).strip()
    return company, ticker


def build_filing_url(adsh, cik):
    """Build URL to the SEC filing index page."""
    if not adsh or not cik:
        return ""
    cik_clean = cik.lstrip("0")
    adsh_nodash = adsh.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/{adsh_nodash}/{adsh}-index.htm"


def should_exclude(text, exclude_phrases):
    """Check if text contains any exclude phrase."""
    if not exclude_phrases or not text:
        return False
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in exclude_phrases)


def fetch_filings(query, forms, date_from, date_to, start=0):
    """Fetch filings from SEC EDGAR full-text search API."""
    params = {
        "dateRange": "custom",
        "startdt": date_from.strftime("%Y-%m-%d"),
        "enddt": date_to.strftime("%Y-%m-%d"),
        "forms": forms,
        "from": start,
    }
    if query and query != "*":
        params["q"] = query

    try:
        resp = requests.get(EDGAR_SEARCH_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  Error fetching '{query}' ({forms}): {e}")
        return None


def process_reports(days_back=1):
    """Fetch and save matching filings from SEC EDGAR across all catalyst categories."""
    load_exchange_data()

    date_from = datetime.now() - timedelta(days=days_back)
    date_to = datetime.now()

    print(f"Fetching filings from {date_from.date()} to {date_to.date()}...")

    total_new = 0
    total_excluded = 0
    seen_ids = set()

    for catalyst in CATALYSTS:
        category = catalyst["category"]
        forms = catalyst["forms"]
        terms = catalyst["terms"]
        exclude = catalyst.get("exclude", [])

        print(f"\n-- {category} --")

        for term in terms:
            start = 0
            while True:
                data = fetch_filings(term, forms, date_from, date_to, start)
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

                    # Parse company info
                    display_names = source.get("display_names", [])
                    display_name = display_names[0] if display_names else ""
                    company, ticker = parse_company_and_ticker(display_name)

                    # Filter by exchange
                    ciks = source.get("ciks", [])
                    cik = ciks[0] if ciks else ""
                    if not is_on_allowed_exchange(cik):
                        total_excluded += 1
                        continue

                    filing_type = source.get("file_type", "") or source.get("form", "")
                    filed_date = source.get("file_date", "")
                    title = source.get("title", "") or category

                    # Exclude unwanted
                    if should_exclude(title, exclude):
                        total_excluded += 1
                        continue

                    filing_url = build_filing_url(adsh, cik)

                    insert_report(
                        {
                            "id": adsh,
                            "company_name": company,
                            "ticker": ticker,
                            "title": title,
                            "category": category,
                            "filing_type": filing_type,
                            "filed_date": filed_date,
                            "url": filing_url,
                            "matched_keywords": term.strip('"'),
                        }
                    )
                    total_new += 1
                    print(f"  [NEW] {company} ({ticker}): {category}")

                total_hits = data.get("hits", {}).get("total", {}).get("value", 0)
                start += len(hits)
                if start >= total_hits or start >= 50 or len(hits) < 10:
                    break

            # Rate limiting - SEC asks for max 10 requests/sec
            time.sleep(0.15)

    clear_old_reports(days=30)

    print(f"\nDone. {total_new} new, {total_excluded} excluded.")
    return total_new


if __name__ == "__main__":
    from database import init_db

    init_db()
    process_reports(days_back=7)
