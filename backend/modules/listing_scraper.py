"""TrustKit AI — Listing Scraper.

Scrapes property listing details using multiple strategies:
1. Zillow autocomplete API → get zpid → Zillow internal property API
2. Redfin search + stingray API (lighter bot protection)
3. Google search snippet parsing as last resort

Falls back gracefully if all methods fail — the pipeline
continues with whatever the user typed manually.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional
from urllib.parse import quote_plus, quote

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TIMEOUT = 15  # seconds

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Core scraper — tries strategies in order
# ---------------------------------------------------------------------------


def scrape_zillow_listing(address: str) -> Dict[str, Any]:
    """Scrape listing details for the given address.

    Strategies:
    1. Zillow autocomplete → zpid → internal property API
    2. Redfin search + stingray detail API
    3. Google search snippet extraction

    Returns a dict with listing details or error.
    """
    if not address or not address.strip():
        return _empty_result(address, error="No address provided")

    # Strategy 1: Zillow autocomplete → property detail API
    print(f"[listing_scraper] Strategy 1: Zillow autocomplete + property API")
    result = _try_zillow_autocomplete_pipeline(address)
    if result and result.get("found") and result.get("description", "").startswith("Property at") is False:
        return result

    # Strategy 2: Redfin (lighter bot protection)
    print(f"[listing_scraper] Strategy 2: Redfin search")
    result = _try_redfin(address)
    if result and result.get("found"):
        return result

    # Strategy 3: Google search snippet
    print(f"[listing_scraper] Strategy 3: Google search")
    result = _try_google_search(address)
    if result and result.get("found"):
        return result

    # If we at least got the Zillow autocomplete data, return that
    print(f"[listing_scraper] Strategy 4: Zillow autocomplete (basic)")
    result = _try_zillow_autocomplete_basic(address)
    if result and result.get("found"):
        return result

    return _empty_result(address, error="Could not find listing data (all strategies failed)")


# ---------------------------------------------------------------------------
# Strategy 1: Zillow autocomplete → property detail API
# ---------------------------------------------------------------------------


def _try_zillow_autocomplete_pipeline(address: str) -> Optional[Dict]:
    """Get zpid from autocomplete, then try internal APIs for details."""
    try:
        # Step 1: Get zpid from autocomplete
        api_url = "https://www.zillowstatic.com/autocomplete/v3/suggestions"
        params = {"q": address, "resultTypes": "allAddress", "resultCount": 1}
        headers = {
            "User-Agent": _BROWSER_UA,
            "Referer": "https://www.zillow.com/",
            "Origin": "https://www.zillow.com",
        }

        resp = requests.get(api_url, params=params, headers=headers, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None

        first = results[0]
        display = first.get("display", "")
        meta = first.get("metaData", {})
        zpid = meta.get("zpid", "")

        if not zpid:
            return None

        print(f"[listing_scraper] Found zpid={zpid} for '{display}'")

        # Step 2: Try Zillow's internal property details API
        # This endpoint is used by Zillow's frontend and may not be behind PerimeterX
        detail_apis = [
            f"https://www.zillow.com/graphql/?zpid={zpid}",
            f"https://zm.zillow.com/api/public/v2/mobile-search/homes/lookup?zpid={zpid}",
        ]

        for api in detail_apis:
            try:
                detail_headers = {
                    "User-Agent": _BROWSER_UA,
                    "Referer": "https://www.zillow.com/",
                    "Origin": "https://www.zillow.com",
                    "Accept": "application/json",
                }
                dr = requests.get(api, headers=detail_headers, timeout=_TIMEOUT)
                if dr.status_code == 200:
                    try:
                        detail_data = dr.json()
                        parsed = _parse_zillow_api_response(detail_data, display)
                        if parsed:
                            parsed["listing_url"] = f"https://www.zillow.com/homedetails/{zpid}_zpid/"
                            return parsed
                    except (json.JSONDecodeError, ValueError):
                        pass
            except Exception:
                continue

        return None

    except Exception as exc:
        print(f"[listing_scraper] Zillow autocomplete pipeline failed: {exc}")
        return None


def _parse_zillow_api_response(data: dict, address: str) -> Optional[Dict]:
    """Parse a Zillow API JSON response for property details."""
    # Try various known response structures
    prop = data
    for path in [["data", "property"], ["property"], ["results", 0]]:
        temp = data
        for key in path:
            if isinstance(temp, dict):
                temp = temp.get(key, {})
            elif isinstance(temp, list) and isinstance(key, int) and len(temp) > key:
                temp = temp[key]
            else:
                temp = {}
                break
        if temp and isinstance(temp, dict) and any(k in temp for k in ["bedrooms", "price", "description"]):
            prop = temp
            break

    if not prop or not isinstance(prop, dict):
        return None

    desc = prop.get("description", "")
    if not desc:
        return None

    return {
        "found": True,
        "address": prop.get("streetAddress", address),
        "price": str(prop.get("price", "N/A")),
        "bedrooms": str(prop.get("bedrooms", "N/A")),
        "bathrooms": str(prop.get("bathrooms", "N/A")),
        "sqft": str(prop.get("livingArea", "N/A")),
        "description": desc,
        "listing_type": prop.get("homeStatus", "Unknown"),
        "year_built": str(prop.get("yearBuilt", "N/A")),
        "listing_url": "",
        "error": None,
    }


# ---------------------------------------------------------------------------
# Strategy 2: Redfin
# ---------------------------------------------------------------------------


def _try_redfin(address: str) -> Optional[Dict]:
    """Search Redfin for the listing — lighter bot protection than Zillow."""
    try:
        # Step 1: Redfin autocomplete to find the property URL
        search_url = "https://www.redfin.com/stingray/do/location-autocomplete"
        params = {"location": address, "v": 2}
        headers = {
            "User-Agent": _BROWSER_UA,
            "Referer": "https://www.redfin.com/",
        }

        resp = requests.get(search_url, params=params, headers=headers, timeout=_TIMEOUT)
        print(f"[listing_scraper] Redfin autocomplete: {resp.status_code}")

        if resp.status_code != 200:
            return None

        # Redfin wraps JSON in {}&&{...}
        text = resp.text
        if text.startswith("{}&&"):
            text = text[4:]

        data = json.loads(text)
        payload = data.get("payload", {})
        sections = payload.get("sections", [])

        property_url = None
        display_name = address

        for section in sections:
            rows = section.get("rows", [])
            for row in rows:
                if row.get("type") == "1":  # Address type
                    property_url = row.get("url", "")
                    display_name = row.get("name", address)
                    break
            if property_url:
                break

        if not property_url:
            # Try exactMatch
            exact = payload.get("exactMatch", {})
            if exact:
                property_url = exact.get("url", "")
                display_name = exact.get("name", address)

        if not property_url:
            print("[listing_scraper] Redfin: no property URL found")
            return None

        # Step 2: Fetch the property page
        full_url = f"https://www.redfin.com{property_url}"
        print(f"[listing_scraper] Redfin property page: {full_url}")

        page_resp = requests.get(full_url, headers=headers, timeout=_TIMEOUT)
        print(f"[listing_scraper] Redfin page: {page_resp.status_code}")

        if page_resp.status_code != 200:
            return None

        soup = BeautifulSoup(page_resp.text, "html.parser")

        # Extract data from meta tags
        description = ""
        price = "N/A"

        og_desc = soup.find("meta", {"property": "og:description"})
        if og_desc:
            description = og_desc.get("content", "")

        meta_desc = soup.find("meta", {"name": "description"})
        if meta_desc and not description:
            description = meta_desc.get("content", "")

        title = soup.find("title")
        if title and title.string:
            price_match = re.search(r"\$[\d,]+", title.string)
            if price_match:
                price = price_match.group(0)

        if not description:
            return None

        # Parse bed/bath/sqft from description
        beds = "N/A"
        baths = "N/A"
        sqft = "N/A"

        bed_match = re.search(r"(\d+)\s*(?:bed|bd|bedroom|br)", description, re.IGNORECASE)
        bath_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:bath|ba|bathroom)", description, re.IGNORECASE)
        sqft_match = re.search(r"([\d,]+)\s*(?:sq\s*ft|sqft|square\s*feet|sf)", description, re.IGNORECASE)

        if bed_match:
            beds = bed_match.group(1)
        if bath_match:
            baths = bath_match.group(1)
        if sqft_match:
            sqft = sqft_match.group(1)

        return {
            "found": True,
            "address": display_name,
            "price": price,
            "bedrooms": beds,
            "bathrooms": baths,
            "sqft": sqft,
            "description": description,
            "listing_type": "Unknown",
            "year_built": "N/A",
            "listing_url": full_url,
            "error": None,
        }

    except Exception as exc:
        print(f"[listing_scraper] Redfin strategy failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Strategy 3: Google search
# ---------------------------------------------------------------------------


def _try_google_search(address: str) -> Optional[Dict]:
    """Search Google for listing info and parse snippets."""
    try:
        query = quote_plus(f"{address} zillow OR redfin listing beds baths")
        url = f"https://www.google.com/search?q={query}&num=5"

        headers = {
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
        print(f"[listing_scraper] Google: {resp.status_code}")

        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Collect all text snippets from the page
        all_text = []
        for tag in soup.find_all(["div", "span", "em"]):
            text = tag.get_text(" ", strip=True)
            if 20 < len(text) < 600:
                all_text.append(text)

        # Find snippets containing property-like data
        best_snippet = ""
        price = "N/A"
        listing_url = ""

        for text in all_text:
            # Look for price + bed/bath patterns
            has_beds = bool(re.search(r"\d+\s*(?:bed|bd|br)", text, re.IGNORECASE))
            has_baths = bool(re.search(r"\d+(?:\.\d+)?\s*(?:bath|ba)", text, re.IGNORECASE))
            has_price = bool(re.search(r"\$[\d,]+", text))

            if (has_beds or has_baths) and len(text) > len(best_snippet):
                best_snippet = text
                pm = re.search(r"\$[\d,]+", text)
                if pm:
                    price = pm.group(0)

        # Find listing URLs
        for link in soup.find_all("a"):
            href = link.get("href", "")
            if "zillow.com/homedetails" in href or "redfin.com" in href:
                listing_url = href
                break

        if not best_snippet:
            return None

        # Parse structured data
        beds = "N/A"
        baths = "N/A"
        sqft = "N/A"

        bed_match = re.search(r"(\d+)\s*(?:bed|bd|bedroom|br)", best_snippet, re.IGNORECASE)
        bath_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:bath|ba|bathroom)", best_snippet, re.IGNORECASE)
        sqft_match = re.search(r"([\d,]+)\s*(?:sq\s*ft|sqft|square\s*feet|sf)", best_snippet, re.IGNORECASE)

        if bed_match:
            beds = bed_match.group(1)
        if bath_match:
            baths = bath_match.group(1)
        if sqft_match:
            sqft = sqft_match.group(1)

        return {
            "found": True,
            "address": address,
            "price": price,
            "bedrooms": beds,
            "bathrooms": baths,
            "sqft": sqft,
            "description": best_snippet,
            "listing_type": "Unknown",
            "year_built": "N/A",
            "listing_url": listing_url,
            "error": None,
        }

    except Exception as exc:
        print(f"[listing_scraper] Google strategy failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Strategy 4: Zillow autocomplete basic (address verification only)
# ---------------------------------------------------------------------------


def _try_zillow_autocomplete_basic(address: str) -> Optional[Dict]:
    """Return whatever the Zillow autocomplete gives us (address verification)."""
    try:
        api_url = "https://www.zillowstatic.com/autocomplete/v3/suggestions"
        params = {"q": address, "resultTypes": "allAddress", "resultCount": 1}
        headers = {
            "User-Agent": _BROWSER_UA,
            "Referer": "https://www.zillow.com/",
            "Origin": "https://www.zillow.com",
        }

        resp = requests.get(api_url, params=params, headers=headers, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None

        first = results[0]
        display = first.get("display", "")
        meta = first.get("metaData", {})

        if not display:
            return None

        print(f"[listing_scraper] Autocomplete verified: {display}")

        return {
            "found": True,
            "address": display,
            "price": "N/A",
            "bedrooms": "N/A",
            "bathrooms": "N/A",
            "sqft": "N/A",
            "description": f"Verified property listing at {display}",
            "listing_type": "Unknown",
            "year_built": "N/A",
            "listing_url": f"https://www.zillow.com/homedetails/{meta.get('zpid', '')}_zpid/",
            "error": None,
        }

    except Exception as exc:
        print(f"[listing_scraper] Autocomplete basic failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_address_for_url(address: str) -> str:
    """Format an address string for URL patterns."""
    cleaned = re.sub(r"[,.\#\!]", "", address.strip())
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned


def _empty_result(address: str, error: str = "") -> Dict[str, Any]:
    """Return an empty result dict with error info."""
    return {
        "found": False,
        "address": address,
        "price": "N/A",
        "bedrooms": "N/A",
        "bathrooms": "N/A",
        "sqft": "N/A",
        "description": "",
        "listing_type": "Unknown",
        "year_built": "N/A",
        "listing_url": "",
        "error": error,
    }
