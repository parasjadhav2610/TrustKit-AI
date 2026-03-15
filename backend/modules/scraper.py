"""
scraper.py — RentGuard Universal Scraper
=========================================
Two classes. That's it.

  SearchAgent   → searches 5 backends (Brave, SerpAPI, DDG, Bing, Yahoo),
                  returns listing URLs from ANY site
  UniversalParser → parses ANY listing URL on ANY site, no site-specific code

How the parser works without site-specific code:
  1. Playwright loads the page (handles JS-rendered sites like Zillow)
  2. JSON-LD / schema.org  → most modern listing sites publish structured data
  3. Open Graph meta tags  → og:title, og:description, og:image
  4. Heuristic DOM scan    → regex + common CSS patterns for price, address, beds
  5. Full-text extraction  → amenities, contact info, dates

If a new listing site launches tomorrow — no code changes needed.
The parser handles it automatically via steps 2–5.

Usage (from Python):
    from modules.scraper import SearchAgent, UniversalParser

    agent  = SearchAgent()
    parser = UniversalParser()

    urls     = agent.find(query="2BR Seattle WA under $2000")
    listings = [parser.parse(r["url"]) for r in urls]

Output schema (every listing, every site):
    {
      "id":          str,   # sha256 of URL
      "source_site": str,   # domain e.g. "zillow"
      "scraped_at":  str,   # ISO timestamp
      "listing_url": str,
      "title":       str,
      "price":       int,   # monthly USD
      "price_raw":   str,
      "address":     { full, street, city, state, zip },
      "details":     { bedrooms, bathrooms, sqft, property_type },
      "description": str,
      "amenities":   [str],
      "images":      [str],
      "contact":     { name, email, phone, agency },
      "listing_age": str,
      "posted_date": str,
      "flags":       [],    # ← your AI scam agent writes here
      "raw_extras":  {}
    }
"""

# ── Standard library ──────────────────────────────────────────────────────────
import re
import json
import time
import random
import hashlib
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urlparse, quote_plus, unquote

# ── Third-party ───────────────────────────────────────────────────────────────
import requests as httpx  # type: ignore[import]
from bs4 import BeautifulSoup  # type: ignore[import]
from playwright.sync_api import sync_playwright  # type: ignore[import]

# DDGS library — best DDG backend, handles sessions + rate limits automatically
try:
    from ddgs import DDGS  # type: ignore[import]
    _DDGS_AVAILABLE = True
except ImportError:
    _DDGS_AVAILABLE = False

# =============================================================================
# LOGGING
# =============================================================================

def _logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    if not log.handlers:
        h = logging.StreamHandler()
        fmt = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S"
        )
        h.setFormatter(fmt)
        log.addHandler(h)
        
        # Add file handler for debugging deep_scan failures
        fh = logging.FileHandler("scraper_debug.log")
        fh.setFormatter(fmt)
        log.addHandler(fh)
        
    log.setLevel(logging.INFO)
    return log


# =============================================================================
# DATA SCHEMA  (the only data model — every listing, every site)
# =============================================================================

@dataclass
class Listing:
    # Identity
    id:          str = ""
    source_site: str = ""
    scraped_at:  str = ""
    listing_url: str = ""

    # Core
    title:     str = ""
    price:     Optional[int] = None   # monthly rent as integer USD
    price_raw: str = ""

    # Structured sub-objects (stored as plain dicts for JSON-serializability)
    address: dict = field(default_factory=lambda: {
        "full": "", "street": "", "city": "", "state": "", "zip": ""
    })
    details: dict = field(default_factory=lambda: {
        "bedrooms": None, "bathrooms": None, "sqft": None, "property_type": ""
    })
    contact: dict = field(default_factory=lambda: {
        "name": "", "email": "", "phone": "", "agency": ""
    })

    # Rich content
    description: str  = ""
    amenities:   list = field(default_factory=list)
    images:      list = field(default_factory=list)

    # Temporal
    listing_age: str = ""
    posted_date: str = ""

    # Street View exterior verification
    street_view: dict = field(default_factory=lambda: {
        "fetched":    False,
        "address":    "",
        "images":     [],   # list of { heading, pitch, url, base64 }
        "coverage":   "",   # "full" | "partial" | "none"
        "note":       "",   # e.g. "No Street View coverage for this address"
    })

    # AI agent hook — RentGuard scam detection writes here
    flags:      list = field(default_factory=list)
    raw_extras: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.listing_url and not self.id:
            self.id = hashlib.sha256(self.listing_url.encode()).hexdigest()[:16]  # type: ignore[index]
        if not self.scraped_at:
            self.scraped_at = datetime.utcnow().isoformat() + "Z"
        if not self.source_site and self.listing_url:
            self.source_site = _domain(self.listing_url)

    def to_dict(self) -> dict:
        return asdict(self)  # type: ignore[arg-type]

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# =============================================================================
# PARSING UTILITIES  (shared, no site-specific logic)
# =============================================================================

def _domain(url: str) -> str:
    """zillow.com/homes/... → 'zillow'"""
    try:
        d = urlparse(url).netloc.lower()
        d = d.lstrip("www.")
        return d.split(".")[0]
    except Exception:
        return "unknown"

def _price(raw: str) -> Optional[int]:
    if not raw:
        return None
    numbers = re.findall(r"\d[\d,]*", raw.replace(",", ""))
    return int(numbers[0]) if numbers else None

def _beds(text: str) -> Optional[int]:
    if not text:
        return None
    if "studio" in text.lower():
        return 0
    m = re.search(r"(\d)\s*(?:bed|br\b)", text, re.I)
    return int(m.group(1)) if m else None

def _baths(text: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d)?)\s*(?:bath|ba\b)", text or "", re.I)
    return float(m.group(1)) if m else None

def _sqft(text: str) -> Optional[int]:
    m = re.search(r"(\d[\d,]*)\s*(?:sq\.?\s*ft|sqft)", (text or "").replace(",",""), re.I)
    return int(m.group(1)) if m else None

def _parse_address(raw: str) -> dict:
    r = {"full": raw.strip(), "street": "", "city": "", "state": "", "zip": ""}
    z = re.search(r"\b(\d{5}(?:-\d{4})?)\b", raw)
    if z:
        r["zip"] = z.group(1)
    s = re.search(r"\b([A-Z]{2})\b", raw)
    if s:
        r["state"] = s.group(1)
    parts = [p.strip() for p in raw.split(",")]
    if parts:
        r["street"] = parts[0]
    if len(parts) >= 2:
        r["city"] = parts[1]
    return r

def _posted_date(age: str) -> str:
    if not age:
        return ""
    now = datetime.utcnow()
    s = age.lower()
    if any(w in s for w in ["just", "today", "hour", "minute"]):
        return now.date().isoformat()
    m = re.search(r"(\d+)\s*(day|week|month)", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"day": timedelta(days=n), "week": timedelta(weeks=n),
                 "month": timedelta(days=n*30)}[unit]
        return (now - delta).date().isoformat()
    return ""

_AMENITY_KW = [
    "parking","garage","gym","fitness","pool","hot tub","pet friendly","pets allowed",
    "washer","dryer","in-unit laundry","laundry","dishwasher","air conditioning","a/c",
    "hardwood","balcony","patio","rooftop","elevator","doorman","storage","furnished",
    "utilities included","internet","wifi","fireplace","yard","garden","wheelchair","bike",
]

def _amenities(text: str) -> list:
    t = text.lower()
    return [k for k in _AMENITY_KW if k in t]

def _polite_delay(lo: float = 1.5, hi: float = 3.5) -> None:
    time.sleep(random.uniform(lo, hi))


# =============================================================================
# SHARED HTTP HELPERS
# =============================================================================

# Rotate through multiple User-Agents — single UA gets flagged fast
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

def _random_headers() -> dict:
    return {
        "User-Agent":      random.choice(_USER_AGENTS),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT":             "1",
        "Connection":      "keep-alive",
    }


# =============================================================================
# SEARCH AGENT  — multi-backend, auto-rotates when a backend is blocked
# =============================================================================

# Domains that are never listing pages
_SKIP_DOMAINS = {
    "google","bing","yahoo","duckduckgo","reddit","twitter","x","instagram",
    "youtube","wikipedia","linkedin","nytimes","washingtonpost","forbes",
    "yelp","bbb","nextdoor","pinterest","tiktok",
}

# URL patterns that strongly indicate a listing detail page
_LISTING_PATTERNS = [
    r"craigslist\.org/.+/\d{7,}",
    r"zillow\.com/homes?/",
    r"zillow\.com/b/",
    r"realtor\.com/realestate",
    r"apartments\.com/[a-z0-9\-]+-[a-z]{2}-\d{5}",
    r"apartments\.com/[a-z0-9\-]+/[a-z0-9\-]+",
    r"facebook\.com/marketplace/item/",
    r"trulia\.com/p/",
    r"hotpads\.com/.+/\d+",
    r"zumper\.com/[a-z0-9\-]+",
    r"redfin\.com/[A-Z]{2}/.+/home/",
    r"rent\.com/[a-z0-9\-]+/[a-z0-9\-]+",
    r"/\d{7,}",
    r"/for[-_]rent/[a-z0-9\-]+",
    r"/rental[s]?/[a-z0-9\-]+",
    r"/listing[s]?/[a-z0-9\-]+",
    r"/property/[a-z0-9\-]+",
    r"/apartment[s]?/[a-z0-9\-]+",
    r"/homes?/[a-z0-9\-]+",
    r"/unit[s]?/[a-z0-9\-]+",
]

_SEARCH_TEMPLATES = [
    "{q} apartment for rent",
    "{q} rental listing",
    "{q} for rent",
]


class SearchAgent:
    """
    Multi-backend search agent with automatic fallback rotation.

    Backend priority (tries each in order until results are found):
      1. Brave Search API   — best option, free 2000/mo, no CC needed
                              Sign up: https://api.search.brave.com/
      2. SerpAPI            — reliable Google results, free 100/mo
                              Sign up: https://serpapi.com/
      3. DDGS library       — duckduckgo-search package, handles rate limits
      4. DDG HTML scrape    — raw DDG, blocks after ~2 req/session (fallback)
      5. Bing scrape        — moderate tolerance
      6. Yahoo scrape       — most lenient of the scraped options

    Recommended setup:
        agent = SearchAgent(brave_api_key="BSA...")   ← free key, 2 min signup
    """

    def __init__(self, max_results: int = 25,
                 brave_api_key: Optional[str] = None,
                 serp_api_key: Optional[str] = None):
        self.max_results   = max_results
        self.brave_api_key = brave_api_key
        self.serp_api_key  = serp_api_key
        self.log = _logger("SearchAgent")
        self._blocked: set = set()   # tracks which backends are blocked this session

    def find(self, query: str) -> list:
        self.log.info(f"Searching: '{query}'")
        seen: set = set()
        results: list = []

        for template in _SEARCH_TEMPLATES:
            if len(results) >= self.max_results:
                break
            q   = template.format(q=query)
            raw = self._search_with_rotation(q)
            for r in raw:
                url = r.get("url", "")
                if not url or url in seen:
                    continue
                if not self._is_listing(url):
                    continue
                seen.add(url)
                results.append(r)
            _polite_delay(1.5, 3.5)

        self.log.info(f"Found {len(results)} listing URLs")
        return results[:self.max_results]  # type: ignore[index]

    # ── Backend rotation ──────────────────────────────────────────────────────

    def _search_with_rotation(self, query: str) -> list:
        """Try each backend in priority order; skip blocked ones."""
        backends = [
            ("brave", self._brave),
            ("serp",  self._serp),
            ("ddgs",  self._ddgs),
            ("ddg",   self._ddg),
            ("bing",  self._bing),
            ("yahoo", self._yahoo),
        ]

        for name, fn in backends:
            if name in self._blocked:
                continue
            if name == "brave" and not self.brave_api_key:
                continue
            if name == "serp"  and not self.serp_api_key:
                continue

            self.log.info(f"Trying backend: {name}")
            results = fn(query)

            if results:
                self.log.info(f"Backend '{name}' returned {len(results)} results")
                return results

            self.log.warning(f"Backend '{name}' empty — marking blocked for this session")
            self._blocked.add(name)
            time.sleep(random.uniform(0.5, 1.5))

        self.log.error("All search backends exhausted — no results")
        return []

    # ── Backend 1: Brave Search API ───────────────────────────────────────────

    def _brave(self, query: str) -> list:
        """
        Brave Search API (recommended primary backend).
        Free: 2,000 queries/month, no credit card.
        Get key: https://api.search.brave.com/
        """
        try:
            resp = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 20, "country": "us",
                        "search_lang": "en", "freshness": "pm"},
                headers={
                    "Accept":               "application/json",
                    "Accept-Encoding":      "gzip",
                    "X-Subscription-Token": self.brave_api_key,
                },
                timeout=12,
            )
            if resp.status_code in (429, 401):
                self.log.warning(f"Brave: HTTP {resp.status_code}")
                return []
            resp.raise_for_status()
            out = []
            for item in resp.json().get("web", {}).get("results", []):
                out.append({
                    "url":     item.get("url", ""),
                    "title":   item.get("title", ""),
                    "snippet": item.get("description", ""),
                })
            return out
        except Exception as e:
            self.log.warning(f"Brave failed: {e}")
            return []

    # ── Backend 2: SerpAPI ────────────────────────────────────────────────────

    def _serp(self, query: str) -> list:
        """
        SerpAPI — Google results via API.
        Free: 100 searches/month. Get key: https://serpapi.com/
        """
        try:
            resp = httpx.get(
                "https://serpapi.com/search",
                params={"q": query, "engine": "google", "num": 20,
                        "hl": "en", "gl": "us", "api_key": self.serp_api_key},
                timeout=15,
            )
            if resp.status_code == 429:
                self.log.warning("SerpAPI: rate limited")
                return []
            resp.raise_for_status()
            out = []
            for item in resp.json().get("organic_results", []):
                out.append({
                    "url":     item.get("link", ""),
                    "title":   item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                })
            return out
        except Exception as e:
            self.log.warning(f"SerpAPI failed: {e}")
            return []

    # ── Backend 3: DDGS library ───────────────────────────────────────────────

    def _ddgs(self, query: str) -> list:
        """
        duckduckgo-search library — handles sessions, cookies, rate limits.
        Install: pip install duckduckgo-search
        """
        if not _DDGS_AVAILABLE:
            return []
        try:
            out: list = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, region="us-en", max_results=15):
                    out.append({
                        "url":     r.get("href", ""),
                        "title":   r.get("title", ""),
                        "snippet": r.get("body", ""),
                    })
            return out
        except Exception as e:
            self.log.warning(f"DDGS failed: {e}")
            return []

    # ── Backend 4: DDG HTML scrape (last-resort DDG fallback) ─────────────────

    def _ddg(self, query: str) -> list:
        """Raw DDG HTML POST — blocks quickly, used only if DDGS library fails."""
        try:
            time.sleep(random.uniform(2.0, 5.0))
            resp = httpx.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "kl": "us-en"},
                headers=_random_headers(),
                timeout=15,
            )
            if len(resp.text) < 2000:
                self.log.warning("DDG HTML: response too short — likely blocked")
                return []
            return self._parse_ddg(resp.text)
        except Exception as e:
            self.log.warning(f"DDG HTML failed: {e}")
            return []

    def _parse_ddg(self, html: str) -> list:
        soup = BeautifulSoup(html, "lxml")
        out: list = []
        for res in soup.select(".result"):
            a = res.select_one("a.result__a")
            if not a:
                continue
            href = self._unwrap_ddg(a.get("href", ""))
            if not href:
                continue
            snip = res.select_one(".result__snippet")
            out.append({
                "url":     href,
                "title":   a.get_text(strip=True),
                "snippet": snip.get_text(strip=True) if snip else "",
            })
        return out

    def _unwrap_ddg(self, href: str) -> str:
        if not href:
            return ""
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            return unquote(m.group(1))
        return href if href.startswith("http") else ""

    # ── Backend 5: Bing scrape ────────────────────────────────────────────────

    def _bing(self, query: str) -> list:
        """Bing HTML scrape — more tolerant than DDG raw."""
        try:
            time.sleep(random.uniform(1.5, 3.5))
            resp = httpx.get(
                "https://www.bing.com/search",
                params={"q": query, "count": 20, "first": 1},
                headers=_random_headers(),
                timeout=15,
            )
            if resp.status_code == 429 or "captcha" in resp.text.lower():
                self.log.warning("Bing: rate limited / CAPTCHA")
                return []
            soup = BeautifulSoup(resp.text, "lxml")
            out: list = []
            for li in soup.select("li.b_algo"):
                a = li.select_one("h2 a")
                if not a:
                    continue
                href = a.get("href", "")
                if not href.startswith("http"):
                    continue
                snip = li.select_one(".b_caption p, .b_algoSlug")
                out.append({
                    "url":     href,
                    "title":   a.get_text(strip=True),
                    "snippet": snip.get_text(strip=True) if snip else "",
                })
            return out
        except Exception as e:
            self.log.warning(f"Bing failed: {e}")
            return []

    # ── Backend 6: Yahoo scrape ───────────────────────────────────────────────

    def _yahoo(self, query: str) -> list:
        """Yahoo search — generally the most lenient of the free scraped options."""
        try:
            time.sleep(random.uniform(2.0, 4.0))
            resp = httpx.get(
                "https://search.yahoo.com/search",
                params={"p": query, "n": 20},
                headers=_random_headers(),
                timeout=15,
            )
            if resp.status_code == 429:
                self.log.warning("Yahoo: rate limited")
                return []
            soup = BeautifulSoup(resp.text, "lxml")
            out: list = []
            for div in soup.select("div.algo, div[class*='searchCenterMiddle'] li"):
                a = div.select_one("h3 a, h3.title a")
                if not a:
                    continue
                href = self._unwrap_yahoo(a.get("href", ""))
                if not href or not href.startswith("http"):
                    continue
                snip = div.select_one("p, .compText")
                out.append({
                    "url":     href,
                    "title":   a.get_text(strip=True),
                    "snippet": snip.get_text(strip=True) if snip else "",
                })
            return out
        except Exception as e:
            self.log.warning(f"Yahoo failed: {e}")
            return []

    def _unwrap_yahoo(self, href: str) -> str:
        if not href:
            return ""
        m = re.search(r"[?&](?:u|url|q)=([^&]+)", href)
        if m:
            return unquote(m.group(1))
        m = re.search(r"/RU=([^/]+)/", href)
        if m:
            return unquote(m.group(1))
        return href if href.startswith("http") else ""

    # ── URL classification ────────────────────────────────────────────────────

    def _is_listing(self, url: str) -> bool:
        """Heuristic: does this URL point to a rental listing detail page?"""
        try:
            parsed      = urlparse(url)
            domain_root = parsed.netloc.lower().lstrip("www.").split(".")[0]
        except Exception:
            return False

        if domain_root in _SKIP_DOMAINS:
            return False

        full = url.lower()
        path = (parsed.path + "?" + parsed.query).lower()

        # Reject generic aggregators: real property paths almost always contain numbers
        # (either the street number, zip code, or a property ID).
        if not any(c.isdigit() for c in path):
            return False

        for pat in _LISTING_PATTERNS:
            # Domain-anchored patterns (contain \.) match against full URL
            target = full if r"\." in pat else path
            if re.search(pat, target):
                return True

        return False


# =============================================================================
# UNIVERSAL PARSER  — parses ANY listing page on ANY site
# =============================================================================

_UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
]
_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
]

# Titles that indicate a bot-protection / error page — not real listing content.
# Applied in parse() after extraction so we can silently drop garbage results.
_BLOCK_PAGE_SIGNALS = [
    "access denied",
    "403 forbidden",
    "just a moment",         # Cloudflare interstitial
    "checking your browser", # Cloudflare challenge
    "enable javascript",     # JS-wall with no content rendered
    "robot or human",
    "are you a robot",
    "captcha",
    "blocked",
    "attention required",    # Cloudflare older variant
    "security check",
    "oops!",
    "pardon our interruption"
]

class UniversalParser:
    """
    Parses a rental listing page on ANY site without site-specific code.
    Uses Playwright to handle JS-rendered sites (Zillow, etc.).
    """

    def __init__(self, headless: bool = True, proxy: Optional[dict] = None,
                 fb_cookies: Optional[list] = None):
        self.headless   = headless
        self.proxy      = proxy
        self.fb_cookies = fb_cookies or []
        self.log = _logger("UniversalParser")

    def parse(self, url: str) -> Optional["Listing"]:
        listing = Listing(listing_url=url)
        html = self._load_page(url)
        if not html:
            return None

        soup      = BeautifulSoup(html, "lxml")
        full_text = soup.get_text(" ", strip=True)

        self._from_json_ld(soup, listing)
        self._from_next_data(soup, listing)
        self._from_og_meta(soup, listing)
        self._from_dom_heuristics(soup, full_text, listing)
        self._from_fulltext(full_text, listing)

        if not listing.title and not listing.price:
            self.log.warning(f"Could not extract data from {url}")
            return None

        # ── FIX 1: Block-page detection ───────────────────────────────────────
        # Cloudflare / 403 pages render a title like "Access Denied" or
        # "Just a moment..." — detect them and return None instead of storing
        # a garbage listing with title="Access Denied" and price=None.
        title_lower = (listing.title or "").lower()
        if any(sig in title_lower for sig in _BLOCK_PAGE_SIGNALS):
            self.log.warning(
                f"Blocked by site ({listing.source_site}): '{listing.title}' — skipping"
            )
            return None

        return listing

    # ── Page loading ──────────────────────────────────────────────────────────

    def _load_page(self, url: str) -> Optional[str]:
        # Fast-path: Try basic HTTP GET. Many block headless Chrome but allow basic GETs.
        try:
            import requests  # type: ignore
            resp = requests.get(url, headers=_random_headers(), timeout=12)
            if resp.status_code == 200 and len(resp.text) > 10000:
                page_head = resp.text[:10000].lower()
                is_blocked = any(f"{b}" in page_head for b in _BLOCK_PAGE_SIGNALS)
                if not is_blocked and "captcha" not in page_head and "<title>just a moment" not in page_head:
                    self.log.info("Page loaded via fast-path HTTP GET")
                    return resp.text
        except Exception as e:
            self.log.info(f"Fast-path HTTP GET failed: {e}")

        self.log.info("Falling back to Playwright headless browser...")
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                    ],
                    proxy=self.proxy,
                )
                ctx = browser.new_context(
                    user_agent=random.choice(_UA_LIST),
                    viewport=random.choice(_VIEWPORTS),
                    locale="en-US",
                    timezone_id="America/Los_Angeles",
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                )

                if self.fb_cookies and "facebook.com" in url:
                    ctx.add_cookies(self.fb_cookies)

                page = ctx.new_page()
                page.add_init_script("""
                    Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
                    Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
                    Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
                """)

                page.goto(url, wait_until="domcontentloaded", timeout=20000)

                for selector in ["h1", "[class*='price']", "article", "main"]:
                    try:
                        page.wait_for_selector(selector, timeout=4000)
                        break
                    except Exception:
                        pass

                height = page.evaluate("document.body.scrollHeight")
                step   = height // 4
                for i in range(1, 5):
                    page.evaluate(f"window.scrollTo(0,{step*i})")
                    time.sleep(random.uniform(0.4, 0.9))

                html = page.content()
                browser.close()
                return html

        except Exception as e:
            self.log.warning(f"Page load failed ({url[:60]}): {e}")  # type: ignore[index]
            return None

    # ── Extraction strategies (waterfall) ─────────────────────────────────────

    def _from_json_ld(self, soup: BeautifulSoup, L: "Listing") -> None:
        LISTING_TYPES = {
            "Apartment", "SingleFamilyResidence", "ApartmentComplex",
            "RealEstateListing", "Product", "Residence", "House", "Place",
        }
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, list):
                    data = data[0] if data else {}
                if not isinstance(data, dict):
                    continue
                if data.get("@type") not in LISTING_TYPES:
                    continue

                if not L.title:
                    L.title = data.get("name", "")
                if not L.description:
                    L.description = data.get("description", "")

                if not L.address["full"]:
                    addr = data.get("address", {})
                    if isinstance(addr, dict):
                        L.address = _parse_address(
                            f"{addr.get('streetAddress','')},"
                            f"{addr.get('addressLocality','')},"
                            f"{addr.get('addressRegion','')} "
                            f"{addr.get('postalCode','')}"
                        )

                if not L.price:
                    offers = data.get("offers", {})
                    if isinstance(offers, dict):
                        L.price_raw = str(offers.get("price", ""))
                        L.price = _price(L.price_raw)

                imgs = data.get("image", [])
                if isinstance(imgs, str):
                    imgs = [imgs]
                for img in imgs:
                    if isinstance(img, dict):
                        img = img.get("url", "")
                    if img and img not in L.images:
                        L.images.append(img)

                if L.details["bedrooms"] is None:
                    L.details["bedrooms"] = (
                        data.get("numberOfBedrooms") or data.get("numberOfRooms")
                    )
                if L.details["bathrooms"] is None:
                    L.details["bathrooms"] = data.get("numberOfBathroomsTotal")

            except Exception:
                continue

    def _from_next_data(self, soup: BeautifulSoup, L: "Listing") -> None:
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return
        
        try:
            data = json.loads(script.string)
            props = data.get("props", {}).get("pageProps", {})
            
            building = props.get("initialData", {}).get("building", {})
            cache = props.get("componentProps", {}).get("gdpClientCache", "")
            
            prop_data = building
            if not prop_data and cache:
                cache_dict: dict = json.loads(cache) if isinstance(cache, str) else cache  # type: ignore
                for k, v in cache_dict.items():
                    if v.get("property"):
                        prop_data = v.get("property")
                        break

            if not prop_data:
                return

            if not L.price:
                price = prop_data.get("price")
                if price:
                    L.price_raw = str(price)
                    L.price = _price(str(price))
            
            if L.details["bedrooms"] is None:
                L.details["bedrooms"] = prop_data.get("bedrooms", prop_data.get("beds"))
            if L.details["bathrooms"] is None:
                L.details["bathrooms"] = prop_data.get("bathrooms", prop_data.get("baths"))
            if L.details["sqft"] is None:
                L.details["sqft"] = prop_data.get("livingArea", prop_data.get("area"))
            
            if not L.description:
                L.description = prop_data.get("description", "")
                
            photo_urls = []
            media = prop_data.get("responsivePhotos", []) or prop_data.get("photos", []) or prop_data.get("hugePhotos", [])
            for item in media:
                if isinstance(item, dict):
                    sources = item.get("mixedSources", {}).get("jpeg", [])
                    if sources:
                        best = max(sources, key=lambda x: x.get("width", 0))
                        photo_urls.append(best.get("url", ""))
                    elif item.get("url"):
                        photo_urls.append(item["url"])
            
            for pu in photo_urls:
                if pu and pu not in L.images:
                    L.images.append(pu)
                    
            if not L.address["full"]:
                addr = prop_data.get("address", {})
                if isinstance(addr, dict):
                    L.address["street"] = addr.get("streetAddress", "")
                    L.address["city"] = addr.get("city", "")
                    L.address["state"] = addr.get("state", "")
                    L.address["zip"] = addr.get("zipcode", "")
                    L.address["full"] = f"{L.address['street']}, {L.address['city']}, {L.address['state']} {L.address['zip']}"
                elif isinstance(addr, str):
                    L.address["full"] = addr 
                    
        except Exception as e:
            self.log.warning(f"Error parsing __NEXT_DATA__: {e}")

    def _from_og_meta(self, soup: BeautifulSoup, L: "Listing") -> None:
        def meta(prop: str) -> str:
            t = (soup.find("meta", property=prop) or
                 soup.find("meta", attrs={"name": prop}))
            return t.get("content", "").strip() if t else ""  # type: ignore[union-attr]

        if not L.title:
            L.title = meta("og:title") or meta("twitter:title")
        if not L.description:
            d = meta("og:description") or meta("twitter:description") or meta("description")
            if d:
                L.description = d

        og_img = meta("og:image")
        if og_img and og_img not in L.images:
            L.images.insert(0, og_img)

        if not L.price:
            p = meta("product:price:amount") or meta("og:price:amount")
            if p:
                L.price_raw = p
                L.price = _price(p)

    def _from_dom_heuristics(self, soup: BeautifulSoup, full_text: str, L: "Listing") -> None:
        if not L.title:
            h1 = soup.find("h1")
            if h1:
                L.title = h1.get_text(strip=True)[:200]  # type: ignore[index]

        if not L.price:
            for pat in [
                r"\$([\d,]+)\s*/\s*mo(?:nth)?",
                r"\$([\d,]+)\s*per\s*month",
                r"([\d,]+)\s*/\s*mo(?:nth)?\b",
            ]:
                m = re.search(pat, full_text, re.I)
                if m:
                    L.price_raw = m.group(0)
                    L.price = _price(m.group(1))
                    break

        if not L.price:
            for el in soup.find_all(class_=re.compile(r"price|rent|cost|amount", re.I)):
                t = el.get_text(strip=True)
                if "$" in t and len(t) < 40:
                    L.price_raw = t
                    L.price = _price(t)
                    break

        if not L.address["full"]:
            m = re.search(
                r"\d+\s+[A-Z][a-z]+(?:\s+[A-Z]?[a-z]+)*"
                r"(?:\s+(?:St|Ave|Blvd|Dr|Rd|Ln|Way|Ct|Pl|Pkwy)\.?)?"
                r",\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z]{2}\s+\d{5}",
                full_text
            )
            if m:
                L.address = _parse_address(m.group(0))

        if not L.address["full"]:
            for el in soup.find_all(class_=re.compile(r"address|location|street", re.I)):
                t = el.get_text(strip=True)
                if len(t) > 10 and any(c.isdigit() for c in t):
                    L.address = _parse_address(t)
                    break

        scan = full_text[:3000]  # type: ignore[index]
        if L.details["bedrooms"] is None:
            L.details["bedrooms"] = _beds(scan)
        if L.details["bathrooms"] is None:
            L.details["bathrooms"] = _baths(scan)
        if L.details["sqft"] is None:
            L.details["sqft"] = _sqft(scan)

        if not L.details["property_type"]:
            for ptype in ["studio","apartment","condo","townhouse","house","room","duplex"]:
                if ptype in scan.lower():
                    L.details["property_type"] = ptype
                    break

        if not L.description:
            candidates = (
                soup.find_all(class_=re.compile(r"desc|detail|about|summary|body", re.I))
                + soup.find_all(["p", "article"])
            )
            best = max((el.get_text(strip=True) for el in candidates), key=len, default="")
            if len(best) > 100:
                L.description = best[:4000]  # type: ignore[index]

        # ALways scan DOM for images to back up JSON-LD/OG:Image, up to a limit
        for img in soup.find_all("img"):
            src = img.get("src","") or img.get("data-src","") or img.get("data-lazy-src","")
            if not src or src.startswith("data:"):
                continue
            if any(x in src.lower() for x in ["icon","logo","avatar","pixel","badge","ad.","blank"]):
                continue
            try:
                w = int(str(img.get("width", "0")).replace("px", ""))
                if w and w < 100:
                    continue
            except ValueError:
                pass
            if src not in L.images:
                L.images.append(src)
            if len(L.images) >= 30:
                break

        if not L.listing_age:
            date_el = soup.find("time")
            if date_el:
                L.listing_age = date_el.get("title","") or date_el.get_text(strip=True)
                dt = date_el.get("datetime","")
                L.posted_date = dt[:10] if dt else _posted_date(L.listing_age)  # type: ignore[index]

    def _from_fulltext(self, full_text: str, L: "Listing") -> None:
        if not L.amenities and L.description:
            L.amenities = _amenities(L.description + " " + full_text[:2000])  # type: ignore[index]

        if not L.contact["phone"]:
            m = re.search(r"\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4}", full_text)
            if m:
                L.contact["phone"] = m.group(0)

        if not L.contact["email"]:
            m = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", full_text)
            if m:
                L.contact["email"] = m.group(0)

        if L.price and not L.price_raw:
            L.price_raw = f"${L.price:,}/mo"


# =============================================================================
# STREET VIEW CHECKER
# =============================================================================

_STREET_VIEW_HEADINGS = [
    {"heading": 0,   "label": "north"},
    {"heading": 90,  "label": "east"},
    {"heading": 180, "label": "south"},
    {"heading": 270, "label": "west"},
]

_SV_API_BASE    = "https://maps.googleapis.com/maps/api/streetview"
_SV_META_BASE   = "https://maps.googleapis.com/maps/api/streetview/metadata"
_MAPBOX_BASE    = "https://api.mapbox.com/styles/v1/mapbox/streets-v12/static"
_GEOCODE_BASE   = "https://maps.googleapis.com/maps/api/geocode/json"
_NOMINATIM_BASE = "https://nominatim.openstreetmap.org/search"


class StreetViewChecker:
    """Fetches Google Street View images at 4 compass angles for exterior comparison."""

    def __init__(self, google_api_key: Optional[str] = None,
                 mapbox_token: Optional[str] = None,
                 image_size: str = "640x480", fetch_base64: bool = True):
        self.google_api_key = google_api_key
        self.mapbox_token   = mapbox_token
        self.image_size     = image_size
        self.fetch_base64   = fetch_base64
        self.log = _logger("StreetView")

        if not google_api_key and not mapbox_token:
            self.log.warning("No API key — pass google_api_key or mapbox_token to enable Street View.")

    def check(self, address: str) -> dict:
        result: dict = {
            "fetched": False, "address": address,
            "lat": None, "lng": None,
            "images": [], "coverage": "none", "note": "",
        }
        if not self.google_api_key and not self.mapbox_token:
            result["note"] = "No API key configured"
            return result

        lat, lng = self._geocode(address)
        if lat is None:
            result["note"] = f"Could not geocode: {address}"
            return result

        result["lat"] = lat
        result["lng"] = lng
        self.log.info(f"Geocoded '{address[:50]}' → ({lat:.5f}, {lng:.5f})")  # type: ignore[index]

        if self.google_api_key:
            return self._fetch_google(address, lat, lng, result)
        return self._fetch_mapbox(lat, lng, result)

    def _geocode(self, address: str) -> tuple:
        if self.google_api_key:
            try:
                resp = httpx.get(_GEOCODE_BASE, params={
                    "address": address, "key": self.google_api_key,
                }, timeout=10)
                data = resp.json()
                if data.get("status") == "OK":
                    loc = data["results"][0]["geometry"]["location"]
                    return loc["lat"], loc["lng"]
            except Exception as e:
                self.log.warning(f"Google Geocode failed: {e}")

        try:
            resp = httpx.get(_NOMINATIM_BASE, params={
                "q": address, "format": "json", "limit": 1,
            }, headers={"User-Agent": "RentGuard-TrustKit/1.0"}, timeout=10)
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception as e:
            self.log.warning(f"Nominatim geocode failed: {e}")

        return None, None

    def _fetch_google(self, address: str, lat: float, lng: float, result: dict) -> dict:
        location = f"{lat},{lng}"
        w, h = self.image_size.split("x")
        images: list = []
        success_count = 0

        try:
            meta = httpx.get(_SV_META_BASE, params={
                "location": location, "key": self.google_api_key,
            }, timeout=10).json()
            if meta.get("status") == "ZERO_RESULTS":
                result.update({"coverage": "none", "fetched": True,
                                "note": "No Street View coverage at this address"})
                return result
        except Exception as e:
            self.log.warning(f"Metadata check failed: {e}")

        for angle in _STREET_VIEW_HEADINGS:
            url = (f"{_SV_API_BASE}?size={w}x{h}&location={location}"
                   f"&heading={angle['heading']}&pitch=-5&fov=90"
                   f"&key={self.google_api_key}")
            entry: dict = {"heading": angle["heading"], "label": angle["label"],
                           "url": url, "base64": None}
            if self.fetch_base64:
                b64 = self._download_image_b64(url)
                if b64:
                    entry["base64"] = b64
                    success_count += 1
            else:
                success_count += 1
            images.append(entry)

        result.update({
            "images": images, "fetched": True,
            "coverage": "full" if success_count == 4 else "partial" if success_count > 0 else "none",
            "note": f"Fetched {success_count}/4 Street View angles.",
        })
        return result

    def _fetch_mapbox(self, lat: float, lng: float, result: dict) -> dict:
        zoom_levels = [
            {"zoom": 19, "label": "close_up"}, {"zoom": 17, "label": "block"},
            {"zoom": 15, "label": "neighborhood"}, {"zoom": 13, "label": "area"},
        ]
        images: list = []
        success_count = 0
        for z in zoom_levels:
            url = (f"{_MAPBOX_BASE}/{lng},{lat},{z['zoom']},0/640x480"
                   f"?access_token={self.mapbox_token}")
            entry: dict = {"heading": None, "label": z["label"], "url": url, "base64": None}
            if self.fetch_base64:
                b64 = self._download_image_b64(url)
                if b64:
                    entry["base64"] = b64
                    success_count += 1
            else:
                success_count += 1
            images.append(entry)

        result.update({
            "images": images, "fetched": True, "coverage": "partial",
            "note": "Mapbox satellite (not street-level). Add google_api_key for real Street View.",
        })
        return result

    def _download_image_b64(self, url: str) -> Optional[str]:
        import base64
        try:
            resp = httpx.get(url, timeout=15)
            resp.raise_for_status()
            raw = resp.content
            if len(raw) < 1000:
                self.log.warning("Image too small — likely a placeholder")
                return None
            ct = resp.headers.get("Content-Type", "image/jpeg")
            return f"data:{ct};base64,{base64.b64encode(raw).decode()}"
        except Exception as e:
            self.log.warning(f"Image download failed: {e}")
            return None


# =============================================================================
# FIX 2: ADDRESS FILTER
# Prevents search engine fuzzy-matching from leaking wrong-street results.
#
# Problem: Searching "235 South St Jersey City NJ" causes search engines to
# return results for "235 Grand St", "235 2nd St", etc. in the same city
# because they treat street names as loose keywords.
#
# Solution: After parsing, validate every listing's extracted address against
# the queried address using strict street-number + street-name matching.
#
# Matching rules:
#   - Street number must be identical        (235 ≠ 234)
#   - Street name must match after normalization ("South St" == "South Street"
#     == "S St", but ≠ "Grand St" ≠ "2nd St")
#   - Listings with no address extracted are KEPT (benefit of the doubt —
#     we can't disqualify what we can't read)
# =============================================================================

# Canonical suffix map — normalise before comparing so "St" == "Street"
_STREET_SUFFIX_MAP = {
    "st": "street",  "str": "street",   "street": "street",
    "ave": "avenue", "av": "avenue",    "avenue": "avenue",
    "blvd": "boulevard",                "boulevard": "boulevard",
    "rd": "road",    "road": "road",
    "dr": "drive",   "drive": "drive",
    "ln": "lane",    "lane": "lane",
    "ct": "court",   "court": "court",
    "pl": "place",   "place": "place",
    "ter": "terrace","terr": "terrace", "terrace": "terrace",
    "way": "way",
    "pkwy": "parkway",                  "parkway": "parkway",
    "hwy": "highway",                   "highway": "highway",
}

# Directional abbreviations — expand before comparing so "S St" == "South St"
_DIRECTIONAL_MAP = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
}


def _normalize_street_name(name: str) -> str:
    """
    Normalize a street name string for comparison.
    Examples:
        "235 South St Apt 2"  → "south street"
        "235 S St"            → "south street"
        "235 Grand Street"    → "grand street"
        "235 2nd St"          → "2nd street"
        "195 N Webster Ave"   → "north webster avenue"
    """
    # Strip unit/apt noise
    name = re.sub(r"\b(apt|unit|suite|ste|#|fl|floor)\b.*", "", name, flags=re.I)
    # Strip leading house number
    name = re.sub(r"^\s*\d+\s*", "", name).strip()
    tokens = name.lower().split()
    normalized = []
    for t in tokens:
        # Keep digits for ordinals (2nd, 3rd, 4th…); strip other punctuation
        t_clean = re.sub(r"[^a-z0-9]", "", t)
        if not t_clean:
            continue
        # Expand directionals (single letters only — don't expand "e" in "estate")
        if t_clean in _DIRECTIONAL_MAP and not re.search(r"\d", t_clean):
            normalized.append(_DIRECTIONAL_MAP[t_clean])
        # Expand street suffixes
        elif t_clean in _STREET_SUFFIX_MAP:
            normalized.append(_STREET_SUFFIX_MAP[t_clean])
        else:
            normalized.append(t_clean)
    return " ".join(normalized)


def _parse_query_address(query: str) -> dict:
    """
    Extract { number, street, city, state } from a free-text query string.
    Returns {} if no recognisable house number is found (e.g. generic queries
    like "2BR Seattle WA" — those should never be address-filtered).

    Examples:
        "235 South St apt2 Jersey City NJ"
          → { number:"235", street:"south street", city:"jersey city", state:"nj" }
        "2BR apartment Seattle WA under $2000"
          → {}  (no house number → no filtering)
    """
    m = re.match(r"^\s*(\d+)\s+(.+)", query.strip())
    if not m:
        return {}

    number = m.group(1)
    rest   = m.group(2)

    # Locate state abbreviation to anchor the end of the street portion
    state_m = re.search(
        r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|"
        r"MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|"
        r"UT|VT|VA|WA|WV|WI|WY|DC)\b", rest, re.I
    )
    if state_m:
        state = state_m.group(1).lower()
        street_part = rest[:state_m.start()].strip()  # type: ignore[index]
    else:
        state = ""
        street_part = rest.strip()

    # Remove zip codes and apt/unit tokens from the street portion
    street_part = re.sub(r"\b\d{5}(-\d{4})?\b", "", street_part)
    street_part = re.sub(
        r"\b(apt\d*|unit|suite|ste|#\S*|fl|floor)\s*\S*", "", street_part, flags=re.I
    )

    # Find where the street suffix ends — everything after is the city
    suffix_pattern = "|".join(_STREET_SUFFIX_MAP.keys())
    suffix_m = re.search(rf"\b({suffix_pattern})\b", street_part, re.I)
    if suffix_m:
        street_raw = street_part[:suffix_m.end()].strip()  # type: ignore[index]
        city_raw   = street_part[suffix_m.end():].strip().lower()  # type: ignore[index]
    else:
        parts      = street_part.split()
        street_raw = " ".join(parts[:2]) if len(parts) >= 2 else street_part  # type: ignore[index]
        city_raw   = " ".join(parts[2:]).lower()  # type: ignore[index]

    return {
        "number": number,
        "street": _normalize_street_name(number + " " + street_raw),
        "city":   city_raw.strip(),
        "state":  state,
    }


def _listing_matches_query_address(listing: dict, query_addr: dict,
                                   log: Optional[logging.Logger] = None) -> bool:
    """
    Returns True if the listing's parsed address is consistent with query_addr.
    Conservative: listings with no extractable address are always kept.

    Args:
        listing:    A listing dict (output of Listing.to_dict())
        query_addr: Output of _parse_query_address()
        log:        Optional logger for debug messages

    Returns:
        True  → keep this listing
        False → drop it (wrong street or wrong number)
    """
    if not query_addr:
        return True  # no address in query → generic search → filter nothing

    addr           = listing.get("address", {})
    listing_full   = (addr.get("full",   "") or "").strip()
    listing_street = (addr.get("street", "") or "").strip()

    if not listing_full and not listing_street:
        return True  # can't read address → give benefit of the doubt

    raw = listing_street or listing_full

    # ── Street number check ────────────────────────────────────────────────────
    num_m = re.match(r"\s*(\d+)", raw)
    if num_m:
        listing_number = num_m.group(1)
        if listing_number != query_addr["number"]:
            if log:
                log.info(
                    f"  ✗ Number mismatch — "
                    f"query={query_addr['number']}  listing={listing_number}  "
                    f"({listing.get('source_site', '')})"
                )
            return False

    # ── Street name check ──────────────────────────────────────────────────────
    listing_norm = _normalize_street_name(raw)
    query_norm   = query_addr["street"]

    # Isolate the "core" street name by dropping the suffix (last word if it's
    # a known suffix like "street", "avenue", etc.)
    def _core(words: list[str]) -> list[str]:
        if words and words[-1] in _STREET_SUFFIX_MAP.values():
            return words[:-1]  # type: ignore[index,return-value]
        return words

    query_core   = _core(query_norm.split())
    listing_core = _core(listing_norm.split())

    if query_core and listing_core:
        if not all(w in listing_core for w in query_core):
            if log:
                log.info(
                    f"  ✗ Street mismatch — "
                    f"query='{query_norm}'  listing='{listing_norm}'  "
                    f"({listing.get('source_site', '')})"
                )
            return False

    return True


# =============================================================================
# CONVENIENCE FUNCTION  — search + parse + Street View in one call
# =============================================================================

def scrape(query: str,
           max_results: int = 20,
           headless: bool = True,
           proxy: Optional[dict] = None,
           fb_cookies: Optional[list] = None,
           workers: int = 3,
           google_api_key: Optional[str] = None,
           mapbox_token: Optional[str] = None,
           brave_api_key: Optional[str] = None,
           serp_api_key: Optional[str] = None) -> list:
    """
    One-call interface: search + parse + Street View → list of listing dicts.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    log    = _logger("scrape")
    agent  = SearchAgent(
                 max_results=max_results * 2,
                 brave_api_key=brave_api_key,
                 serp_api_key=serp_api_key,
             )
    parser = UniversalParser(headless=headless, proxy=proxy, fb_cookies=fb_cookies)
    sv     = StreetViewChecker(
                 google_api_key=google_api_key,
                 mapbox_token=mapbox_token,
                 fetch_base64=True,
             ) if (google_api_key or mapbox_token) else None

    # Parse the address from the query upfront — used to filter results later.
    # Only activates when the query starts with a house number (e.g. "235 South St…").
    # Generic queries like "2BR Seattle WA" return {} and are never filtered.
    query_addr = _parse_query_address(query)
    if query_addr:
        log.info(
            f"Address filter active — "
            f"number={query_addr['number']}  "
            f"street='{query_addr['street']}'  "
            f"state={query_addr['state'] or 'any'}"
        )

    search_results = agent.find(query)
    if not search_results:
        log.warning("No listing URLs found.")
        return []

    log.info(f"Parsing {min(len(search_results), max_results)} listings...")
    results: list = []
    seen_ids: set = set()

    def _parse_one(r: dict) -> Optional[Listing]:
        listing = parser.parse(r["url"])
        if listing:
            listing.raw_extras["search_title"]   = r.get("title", "")
            listing.raw_extras["search_snippet"] = r.get("snippet", "")
        return listing

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_parse_one, r): r  # type: ignore[arg-type]
                   for r in search_results[:max_results]}  # type: ignore[index]
        for i, f in enumerate(as_completed(futures), 1):
            try:
                listing = f.result()
                if listing and listing.id not in seen_ids:
                    seen_ids.add(listing.id)
                    results.append(listing.to_dict())
                    log.info(f"[{i}] ✓ {listing.source_site:12} "
                             f"${listing.price or '?':>6}  {listing.title[:45]}")
            except Exception as e:
                log.warning(f"Parse error: {e}")

    # ── FIX 2: Address filter — drop wrong-street results ─────────────────────
    # Runs only when the query contained a house address (query_addr is non-empty).
    # Silently drops listings whose extracted street ≠ queried street.
    if query_addr and results:
        before  = len(results)
        results = [
            L for L in results
            if _listing_matches_query_address(L, query_addr, log)
        ]
        dropped = before - len(results)
        if dropped:
            log.info(
                f"Address filter: removed {dropped} wrong-street listing(s) "
                f"(kept {len(results)})"
            )

    if sv and results:
        first_addr = next(
            (L.get("address", {}).get("full", "") for L in results
             if L.get("address", {}).get("full", "")), ""
        )
        if first_addr:
            sv_data = sv.check(first_addr)
            for L in results:
                L["street_view"] = sv_data
            img_count = len([i for i in sv_data.get("images", []) if i.get("base64")])
            log.info(f"Street View: {sv_data['coverage']} coverage "
                     f"— {img_count} images attached")  # type: ignore[index]
        else:
            log.warning("No address found — skipping Street View")

    _flag_cross_site_duplicates(results, log)
    results.sort(key=lambda x: x.get("price") or 999999)
    log.info(f"Done — {len(results)} listings collected.")
    return results


def _flag_cross_site_duplicates(listings: list, log: logging.Logger) -> None:
    from collections import defaultdict
    by_addr: dict = defaultdict(list)
    for L in listings:
        addr = L.get("address", {}).get("full", "").lower().strip()
        if len(addr) > 10:
            by_addr[addr].append(L)

    for addr, group in by_addr.items():
        if len(group) > 1:
            sites = [g.get("source_site") for g in group]
            log.info(f"⚠  Cross-site: '{addr[:55]}' on {sites}")  # type: ignore[index]
            for L in group:
                L.setdefault("flags", []).append({
                    "type":  "cross_site_duplicate",
                    "sites": sites,
                    "note":  "Same address listed on multiple sites — verify details match",
                })
