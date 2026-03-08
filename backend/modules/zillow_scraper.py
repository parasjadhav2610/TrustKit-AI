"""TrustKit AI — Zillow Listing Scraper Module.

Searches Zillow by property address and extracts listing data
including photos, price, and description for comparison against
uploaded video frames.
"""

import json
import re
import requests
from typing import Optional
from urllib.parse import quote


# Realistic browser headers to avoid anti-bot blocking
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def _address_to_zillow_slug(address: str) -> str:
    """Convert a human-readable address to a Zillow URL slug.
    
    Example: '123 Main St, New York, NY 10001' -> '123-Main-St-New-York-NY-10001'
    """
    # Remove special characters and replace spaces/commas with hyphens
    slug = re.sub(r'[,#\.\']', '', address)
    slug = re.sub(r'\s+', '-', slug.strip())
    return slug


def search_by_address(address: str) -> dict:
    """Search Zillow for a property by address and extract listing details.
    
    Args:
        address: A human-readable address string, e.g.
                 '123 Main St, New York, NY 10001'
    
    Returns:
        A dict with keys:
            - address (str)
            - price (str)
            - beds (str)
            - baths (str)
            - sqft (str)
            - description (str)
            - photo_urls (list[str])
            - photos_bytes (list[bytes]) — downloaded photo images
            - source (str) — 'zillow' or 'mock'
    """
    slug = _address_to_zillow_slug(address)
    url = f"https://www.zillow.com/homes/{slug}_rb/"
    
    print(f"[zillow_scraper] Searching: {url}")
    
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text
        
        # Try to extract __NEXT_DATA__ JSON
        listing = _extract_next_data(html)
        if listing:
            # Download photos
            photos_bytes = _download_photos(listing.get("photo_urls", []), max_photos=5)
            listing["photos_bytes"] = photos_bytes
            listing["source"] = "zillow"
            print(f"[zillow_scraper] Found listing with {len(listing.get('photo_urls', []))} photos")
            return listing
        
        # Try alternate extraction from HTML meta tags
        listing = _extract_from_meta(html, address)
        if listing:
            photos_bytes = _download_photos(listing.get("photo_urls", []), max_photos=5)
            listing["photos_bytes"] = photos_bytes
            listing["source"] = "zillow"
            print(f"[zillow_scraper] Extracted from meta tags: {len(listing.get('photo_urls', []))} photos")
            return listing
            
    except Exception as e:
        print(f"[zillow_scraper] Scrape failed: {e}")
    
    # Fallback: return mock listing data
    print("[zillow_scraper] Using mock listing data as fallback")
    return _mock_listing(address)


def _extract_next_data(html: str) -> Optional[dict]:
    """Extract listing data from Zillow's __NEXT_DATA__ JSON blob."""
    try:
        match = re.search(
            r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
            html, re.DOTALL
        )
        if not match:
            return None
        
        data = json.loads(match.group(1))
        
        # Navigate the JSON tree to find property data
        # Zillow's structure can vary, so we try multiple paths
        props = data.get("props", {}).get("pageProps", {})
        
        # Try componentProps path
        comp = props.get("componentProps", {})
        gdp = comp.get("gdpClientCache", "")
        
        if gdp:
            # gdpClientCache is often a JSON string itself
            try:
                cache = json.loads(gdp) if isinstance(gdp, str) else gdp
                # Get the first property in the cache
                for key, value in cache.items():
                    prop = value.get("property", {})
                    if prop:
                        return _parse_property(prop)
            except (json.JSONDecodeError, AttributeError):
                pass
        
        # Try initialData path
        initial = props.get("initialData", {})
        building = initial.get("building", {})
        if building:
            return _parse_property(building)

        # Try searchPageState path (search results page)
        search = props.get("searchPageState", {})
        results = search.get("cat1", {}).get("searchResults", {}).get("listResults", [])
        if results:
            first = results[0]
            return {
                "address": first.get("address", ""),
                "price": first.get("price", "N/A"),
                "beds": str(first.get("beds", "N/A")),
                "baths": str(first.get("baths", "N/A")),
                "sqft": str(first.get("area", "N/A")),
                "description": first.get("statusText", ""),
                "photo_urls": [first.get("imgSrc", "")] if first.get("imgSrc") else [],
            }
            
    except Exception as e:
        print(f"[zillow_scraper] __NEXT_DATA__ extraction failed: {e}")
    
    return None


def _parse_property(prop: dict) -> dict:
    """Parse a Zillow property dict into our standard format."""
    # Extract photo URLs
    photo_urls = []
    media = prop.get("responsivePhotos", []) or prop.get("photos", [])
    for item in media:
        if isinstance(item, dict):
            # responsivePhotos format
            sources = item.get("mixedSources", {}).get("jpeg", [])
            if sources:
                # Get the highest resolution
                best = max(sources, key=lambda x: x.get("width", 0))
                photo_urls.append(best.get("url", ""))
            elif item.get("url"):
                photo_urls.append(item["url"])
    
    # Fallback: try hugePhotos
    if not photo_urls:
        huge = prop.get("hugePhotos", [])
        for item in huge:
            if isinstance(item, dict) and item.get("url"):
                photo_urls.append(item["url"])
    
    return {
        "address": prop.get("address", {}).get("streetAddress", "") if isinstance(prop.get("address"), dict) else str(prop.get("address", "")),
        "price": str(prop.get("price", "N/A")),
        "beds": str(prop.get("bedrooms", prop.get("beds", "N/A"))),
        "baths": str(prop.get("bathrooms", prop.get("baths", "N/A"))),
        "sqft": str(prop.get("livingArea", prop.get("area", "N/A"))),
        "description": prop.get("description", "No description available."),
        "photo_urls": photo_urls[:10],  # Cap at 10
    }


def _extract_from_meta(html: str, address: str) -> Optional[dict]:
    """Fallback: extract basic listing info from HTML meta tags and OG data."""
    try:
        photo_urls = []
        
        # Extract OG images
        og_images = re.findall(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        photo_urls.extend(og_images)
        
        # Extract any other listing images
        img_matches = re.findall(r'https://photos\.zillowstatic\.com/fp/[a-zA-Z0-9_-]+\.jpg', html)
        for url in img_matches:
            if url not in photo_urls:
                photo_urls.append(url)
        
        if not photo_urls:
            return None
        
        # Get description from meta
        desc_match = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
        description = desc_match.group(1) if desc_match else "No description available."
        
        # Price
        price_match = re.search(r'\$[\d,]+', html)
        price = price_match.group(0) if price_match else "N/A"
        
        return {
            "address": address,
            "price": price,
            "beds": "N/A",
            "baths": "N/A",
            "sqft": "N/A",
            "description": description,
            "photo_urls": photo_urls[:10],
        }
    except Exception:
        return None


def _download_photos(urls: list, max_photos: int = 5) -> list:
    """Download listing photos as bytes."""
    photos = []
    for url in urls[:max_photos]:
        try:
            if not url:
                continue
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            resp.raise_for_status()
            photos.append(resp.content)
        except Exception as e:
            print(f"[zillow_scraper] Failed to download photo: {e}")
    return photos


def _mock_listing(address: str) -> dict:
    """Return a mock listing when Zillow scraping fails."""
    return {
        "address": address,
        "price": "$2,500/mo",
        "beds": "2",
        "baths": "1",
        "sqft": "850",
        "description": (
            "Spacious 2-bedroom apartment in a prime location. "
            "Features hardwood floors, updated kitchen with stainless steel appliances, "
            "large windows with natural light, and in-unit washer/dryer. "
            "Building amenities include a fitness center and rooftop terrace."
        ),
        "photo_urls": [],
        "photos_bytes": [],
        "source": "mock",
    }
