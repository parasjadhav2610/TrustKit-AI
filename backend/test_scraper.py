"""Test script for the listing scraper.

Run from the backend/ directory:
    python test_scraper.py

Tests each scraping strategy individually and shows detailed output
so you can see exactly where the scraping is failing.
"""

import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

ADDRESS = "195 Webster Ave, Apt 2, Jersey City, NJ 07307"

TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def fmt(address: str) -> str:
    cleaned = re.sub(r"[,.\#\!]", "", address.strip())
    return re.sub(r"\s+", "-", cleaned)


def test_zillow_direct():
    """Test 1: Direct Zillow page request."""
    print("\n" + "=" * 60)
    print("TEST 1: Direct Zillow Page")
    print("=" * 60)

    query = fmt(ADDRESS)
    url = f"https://www.zillow.com/homes/{query}_rb/"
    print(f"  URL: {url}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        print(f"  Status: {resp.status_code}")
        print(f"  Content-Length: {len(resp.text)} chars")
        print(f"  Has __NEXT_DATA__: {'__NEXT_DATA__' in resp.text}")

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            title = soup.find("title")
            print(f"  Page Title: {title.string if title else 'N/A'}")

            meta = soup.find("meta", {"name": "description"})
            if meta:
                print(f"  Meta Description: {meta.get('content', '')[:200]}")

            script = soup.find("script", {"id": "__NEXT_DATA__"})
            if script and script.string:
                data = json.loads(script.string)
                print(f"  __NEXT_DATA__ keys: {list(data.keys())}")
                props = data.get("props", {}).get("pageProps", {})
                print(f"  pageProps keys: {list(props.keys())[:10]}")
        else:
            print(f"  Response headers: {dict(list(resp.headers.items())[:5])}")
            print(f"  Body preview: {resp.text[:500]}")

    except Exception as e:
        print(f"  ERROR: {e}")

    print(f"  RESULT: {'PASS' if resp.status_code == 200 else 'FAIL'}")


def test_zillow_session():
    """Test 2: Zillow with session/cookies."""
    print("\n" + "=" * 60)
    print("TEST 2: Zillow Session (cookies)")
    print("=" * 60)

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # Step 1: Get cookies from homepage
        print("  Step 1: Fetching Zillow homepage...")
        home = session.get("https://www.zillow.com/", timeout=TIMEOUT)
        print(f"  Homepage status: {home.status_code}")
        print(f"  Cookies received: {len(session.cookies)} cookies")
        for c in session.cookies:
            print(f"    - {c.name}: {c.value[:30]}...")

        # Step 2: Search with cookies
        query = fmt(ADDRESS)
        url = f"https://www.zillow.com/homes/{query}_rb/"
        session.headers["Referer"] = "https://www.zillow.com/"
        session.headers["Sec-Fetch-Site"] = "same-origin"

        print(f"\n  Step 2: Searching {url}")
        resp = session.get(url, timeout=TIMEOUT)
        print(f"  Search status: {resp.status_code}")
        print(f"  Content-Length: {len(resp.text)} chars")

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            title = soup.find("title")
            print(f"  Page Title: {title.string if title else 'N/A'}")

            meta = soup.find("meta", {"name": "description"})
            if meta:
                print(f"  Meta Description: {meta.get('content', '')[:200]}")

    except Exception as e:
        print(f"  ERROR: {e}")

    print(f"  RESULT: {'PASS' if resp.status_code == 200 else 'FAIL'}")


def test_zillow_autocomplete():
    """Test 3: Zillow autocomplete API."""
    print("\n" + "=" * 60)
    print("TEST 3: Zillow Autocomplete API")
    print("=" * 60)

    api_url = "https://www.zillowstatic.com/autocomplete/v3/suggestions"
    params = {"q": ADDRESS, "resultTypes": "allAddress", "resultCount": 3}
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Referer": "https://www.zillow.com/",
        "Origin": "https://www.zillow.com",
    }

    try:
        resp = requests.get(api_url, params=params, headers=headers, timeout=TIMEOUT)
        print(f"  Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            print(f"  Results found: {len(results)}")
            for i, r in enumerate(results):
                print(f"\n  Result {i + 1}:")
                print(f"    Display: {r.get('display', 'N/A')}")
                meta = r.get("metaData", {})
                print(f"    zpid: {meta.get('zpid', 'N/A')}")
                print(f"    lat/lng: {meta.get('lat', 'N/A')}, {meta.get('lng', 'N/A')}")
                print(f"    city: {meta.get('city', 'N/A')}")
                print(f"    state: {meta.get('state', 'N/A')}")
        else:
            print(f"  Body: {resp.text[:500]}")

    except Exception as e:
        print(f"  ERROR: {e}")

    print(f"  RESULT: {'PASS' if resp.status_code == 200 else 'FAIL'}")


def test_google_search():
    """Test 4: Google search for Zillow listing."""
    print("\n" + "=" * 60)
    print("TEST 4: Google Search Fallback")
    print("=" * 60)

    query = quote_plus(f"site:zillow.com {ADDRESS}")
    url = f"https://www.google.com/search?q={query}&num=3"

    try:
        resp = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=TIMEOUT)
        print(f"  Status: {resp.status_code}")
        print(f"  Content-Length: {len(resp.text)} chars")

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Find Zillow links
            found_links = []
            for link in soup.find_all("a"):
                href = link.get("href", "")
                if "zillow.com" in href:
                    found_links.append(href[:100])
            print(f"  Zillow links found: {len(found_links)}")
            for lnk in found_links[:3]:
                print(f"    - {lnk}")

            # Find snippets with listing data
            snippets = []
            for div in soup.find_all(["div", "span"]):
                text = div.get_text(strip=True)
                if re.search(r"\d+\s*(bed|bd|bath|ba|sqft)", text, re.IGNORECASE) and len(text) < 500:
                    snippets.append(text[:200])
            print(f"\n  Listing snippets found: {len(snippets)}")
            for s in snippets[:3]:
                print(f"    - {s}")
        else:
            print(f"  Body: {resp.text[:300]}")

    except Exception as e:
        print(f"  ERROR: {e}")

    print(f"  RESULT: {'PASS' if resp.status_code == 200 else 'FAIL'}")


def test_full_scraper():
    """Test 5: Run the actual scraper module."""
    print("\n" + "=" * 60)
    print("TEST 5: Full Scraper Module")
    print("=" * 60)

    try:
        from modules.listing_scraper import scrape_zillow_listing
        result = scrape_zillow_listing(ADDRESS)
        print(f"  Found: {result['found']}")
        print(f"  Address: {result['address']}")
        print(f"  Price: {result['price']}")
        print(f"  Bedrooms: {result['bedrooms']}")
        print(f"  Bathrooms: {result['bathrooms']}")
        print(f"  Sqft: {result['sqft']}")
        print(f"  Type: {result['listing_type']}")
        print(f"  Year Built: {result['year_built']}")
        print(f"  Description: {result['description'][:200]}")
        print(f"  URL: {result['listing_url']}")
        print(f"  Error: {result['error']}")
        print(f"\n  RESULT: {'PASS' if result['found'] else 'FAIL'}")
    except Exception as e:
        print(f"  ERROR: {e}")
        print(f"  RESULT: FAIL")


if __name__ == "__main__":
    print(f"Testing scraper with address: {ADDRESS}")
    print(f"{'=' * 60}")

    test_zillow_direct()
    test_zillow_session()
    test_zillow_autocomplete()
    test_google_search()
    test_full_scraper()

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60)
