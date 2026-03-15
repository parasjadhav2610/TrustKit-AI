"""
run.py — RentGuard Scraper CLI
================================
Usage:
  python run.py --query "2BR Seattle WA under 2000"
  python run.py --query "412 Westlake Ave N Seattle WA for rent" --max 30
  python run.py --url   "https://seattle.craigslist.org/apa/1234567890.html"
  python run.py --query "studio Austin TX" --visible        # show browser
  python run.py --query "Miami apartment"  --fb-cookies fb_cookies.json
  python run.py --query "Jersey City NJ"  --google-key AIza... --pretty
  python run.py --query "Jersey City NJ"  --brave-key BSA...  --pretty
  python run.py --query "Jersey City NJ"  --serp-key YOUR_KEY --pretty
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# Ensure the backend root is on the path so `modules.*` imports resolve
sys.path.insert(0, str(Path(__file__).parent))

from modules.scraper import SearchAgent, UniversalParser, scrape  # type: ignore[import]
from modules.scraper import _logger  # type: ignore[import]

log = _logger("run")

# Capture module docstring at module level so Pyre2 can resolve it inside cli()
_USAGE_DOC: str = __doc__ or ""  # type: ignore[name-defined]


def cli():
    p = argparse.ArgumentParser(
        description="RentGuard Unified Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_USAGE_DOC
    )
    p.add_argument("--query", "-q",  help='Search query e.g. "2BR Seattle WA under 2000"')
    p.add_argument("--url",          help="Parse a single listing URL directly")
    p.add_argument("--max",  type=int, default=20, help="Max listings (default 20)")
    p.add_argument("--output", "-o", help="Output JSON path (default: auto)")
    p.add_argument("--visible",  action="store_true", help="Show browser window")
    p.add_argument("--workers", type=int, default=3,  help="Parallel parse workers")
    p.add_argument("--proxy",   help='Proxy URL e.g. "http://user:pass@host:port"')
    p.add_argument("--fb-cookies",   help="Path to Facebook cookies JSON file")
    p.add_argument("--brave-key",    help="Brave Search API key — free 2000/mo at api.search.brave.com")
    p.add_argument("--serp-key",     help="SerpAPI key — free 100/mo at serpapi.com")
    p.add_argument("--google-key",   help="Google Maps API key (enables real Street View photos)")
    p.add_argument("--mapbox-token", help="Mapbox token (free satellite fallback)")
    p.add_argument("--no-streetview", action="store_true", help="Skip Street View lookup")
    p.add_argument("--pretty", action="store_true", help="Print first 2 listings to stdout")
    args = p.parse_args()

    if not args.query and not args.url:
        p.print_help()
        sys.exit(1)

    headless = not args.visible
    proxy    = {"server": args.proxy} if args.proxy else None

    # Load Facebook cookies if provided
    fb_cookies = []
    if args.fb_cookies:
        try:
            with open(args.fb_cookies) as f:
                raw = json.load(f)
            # Normalise to Playwright cookie format
            fb_cookies = [{
                "name":   c.get("name", ""),
                "value":  c.get("value", ""),
                "domain": c.get("domain", ".facebook.com"),
                "path":   c.get("path", "/"),
            } for c in raw]
            log.info(f"Loaded {len(fb_cookies)} Facebook cookies")
        except Exception as e:
            log.warning(f"Could not load FB cookies: {e}")

    # ── Single URL mode ───────────────────────────────────────────────────────
    if args.url:
        log.info(f"Parsing single URL: {args.url}")
        parser  = UniversalParser(headless=headless, proxy=proxy, fb_cookies=fb_cookies)
        listing = parser.parse(args.url)
        results = [listing.to_dict()] if listing else []
        if not results:
            log.error("Failed to parse listing.")
            sys.exit(1)

    # ── Search mode ───────────────────────────────────────────────────────────
    else:
        log.info(f"\n{'='*60}")
        log.info(f"  RentGuard Scraper  |  query: {args.query}")
        log.info(f"  max={args.max}  workers={args.workers}  headless={headless}")
        log.info(f"{'='*60}\n")

        results = scrape(
            query=args.query,
            max_results=args.max,
            headless=headless,
            proxy=proxy,
            fb_cookies=fb_cookies,
            workers=args.workers,
            google_api_key=None if args.no_streetview else args.google_key,
            mapbox_token=None  if args.no_streetview else args.mapbox_token,
            brave_api_key=args.brave_key,
            serp_api_key=args.serp_key,
        )

    # ── Save output ───────────────────────────────────────────────────────────
    if results:
        output_path: str = args.output or ""
        if not output_path:
            Path("output").mkdir(exist_ok=True)
            slug = (args.query or "single")[:40]
            slug = "".join(c if c.isalnum() else "_" for c in slug).strip("_")
            ts   = datetime.utcnow().strftime("%Y%m%d_%H%M")
            output_path = f"output/{slug}_{ts}.json"

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        log.info(f"\n✓  {len(results)} listings  →  {output_path}")

        if args.pretty:
            print("\n── Sample (first 2 listings) ──────────────────────────")
            print(json.dumps(results[:2], indent=2))  # type: ignore[index]
    else:
        log.warning("No listings collected.")

    return results


if __name__ == "__main__":
    cli()
