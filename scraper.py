import time
import random
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DOMAINS = {
    "Spain":         "https://www.vinted.es",
    "France":        "https://www.vinted.fr",
    "Belgium":       "https://www.vinted.be",
    "Portugal":      "https://www.vinted.pt",
    "Italy":         "https://www.vinted.it",
    "Netherlands":   "https://www.vinted.nl",
    "Germany":       "https://www.vinted.de",
    "UK":            "https://www.vinted.co.uk",
    "Luxembourg":    "https://www.vinted.lu",
    "International": "https://www.vinted.com",
}

# Vinted item condition IDs
CONDITIONS = {
    "new_tags":    "6",
    "new_no_tags": "1",
    "very_good":   "2",
    "good":        "3",
    "fair":        "4",
}

# Catalog IDs verified against the vinted.es API.
# Structure on the official site: /catalog/{id}-{slug}
CATEGORIES = {
    "all":               None,
    "women_all":         "1904",
    "women_clothing":    "4",
    "women_shoes":       "16",
    "women_bags":        "19",
    "women_accessories": "1187",
    "women_beauty":      "146",
    "men_all":           "5",
    "men_clothing":      "2050",
    "men_shoes":         "1231",
    "men_accessories":   "82",
    "kids":              "1193",
    "home":              "1918",
    "entertainment":     "2309",
    "electronics":       "2994",
    "sports":            "4332",
    "collectibles":      "4824",
    "custom":            "_custom",
}

ORDER_OPTIONS = {
    "newest":     "newest_first",
    "price_asc":  "price_low_to_high",
    "price_desc": "price_high_to_low",
    "relevance":  "relevance",
}

# Delay range (seconds) between paginated requests
DELAY_MODES = {
    "fast":     (1.0, 2.0),
    "normal":   (2.0, 4.0),
    "cautious": (4.0, 8.0),
}


def _get_attr(obj, *keys, default=None):
    for key in keys:
        try:
            val = obj[key] if isinstance(obj, dict) else getattr(obj, key, None)
            if val is not None:
                return val
        except Exception:
            pass
    return default


def _parse_price(raw) -> tuple[Optional[float], str]:
    """Return (price_float, currency). raw can be a dict, float, or str."""
    if raw is None:
        return None, "EUR"
    # API v2 format: {"amount": "92.0", "currency_code": "EUR"}
    if isinstance(raw, dict):
        currency = raw.get("currency_code", "EUR")
        amount = raw.get("amount")
        try:
            return float(str(amount).replace(",", ".")), currency
        except (ValueError, TypeError):
            return None, currency
    try:
        return float(str(raw).replace(",", ".")), "EUR"
    except (ValueError, TypeError):
        return None, "EUR"


def _photo_timestamp(photos) -> Optional[int]:
    """Extract the publication timestamp from the first photo's high_resolution field."""
    if not photos or not isinstance(photos, list):
        return None
    first = photos[0]
    hr = _get_attr(first, "high_resolution")
    if hr is None:
        return None
    return _get_attr(hr, "timestamp")


def item_to_dict(item) -> Optional[dict]:
    try:
        raw_price = _get_attr(item, "price")
        price, currency = _parse_price(raw_price)

        if currency == "EUR":
            currency = _get_attr(item, "currency") or "EUR"

        photos = _get_attr(item, "photos")

        # Prefer photo high_resolution timestamp; fall back to legacy fields
        published_at = _photo_timestamp(photos)
        if published_at is None:
            published_at = _get_attr(item, "created_at_ts", "updated_at_ts")

        photo_url = None
        if photos and isinstance(photos, list):
            photo_url = _get_attr(photos[0], "full_size_url", "url")
        if not photo_url:
            photo = _get_attr(item, "photo")
            if photo:
                photo_url = _get_attr(photo, "full_size_url", "url")

        return {
            "vinted_id":    _get_attr(item, "id"),
            "title":        _get_attr(item, "title"),
            "price":        price,
            "currency":     currency,
            "brand":        _get_attr(item, "brand_title"),
            "size":         _get_attr(item, "size_title"),
            "condition":    _get_attr(item, "status"),
            "url":          _get_attr(item, "url"),
            "photo_url":    photo_url,
            "published_at": published_at,
        }
    except Exception as e:
        logger.warning(f"Error converting item: {e}")
        return None


def fetch_items(
    domain_url: str,
    params: dict,
    max_items: int = 500,
    delay_min: float = 1.0,
    delay_max: float = 2.5,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> list[dict]:
    from vinted_scraper import VintedScraper

    def _make_scraper():
        """Create a scraper with retries and exponential backoff on 406/network errors."""
        for attempt in range(4):
            try:
                return VintedScraper(domain_url)
            except Exception as exc:
                if attempt == 3:
                    raise ConnectionError(f"Could not connect to Vinted: {exc}") from exc
                wait = (2 ** attempt) * random.uniform(2.0, 5.0)
                logger.warning(f"Session retry {attempt + 1}/3 in {wait:.1f}s: {exc}")
                time.sleep(wait)

    scraper = _make_scraper()

    all_items: list[dict] = []
    page = 1
    per_page = 96
    consecutive_errors = 0
    pages_since_refresh = 0
    _REFRESH_EVERY = 7  # Refresh session cookie every 7 pages (~672 items)

    while len(all_items) < max_items:
        # Refresh session periodically to avoid 406 errors on large fetches
        if pages_since_refresh > 0 and pages_since_refresh % _REFRESH_EVERY == 0:
            logger.info("Refreshing session cookie…")
            time.sleep(random.uniform(delay_min * 2, delay_max * 2))
            scraper = _make_scraper()
            pages_since_refresh = 0

        search_params = {**params, "page": page, "per_page": per_page}
        try:
            page_items = scraper.search(search_params)
            if not page_items:
                break

            for raw in page_items:
                d = item_to_dict(raw)
                if d:
                    all_items.append(d)

            if progress_callback:
                progress_callback(len(all_items))

            if len(page_items) < per_page:
                break

            page += 1
            pages_since_refresh += 1
            consecutive_errors = 0
            time.sleep(random.uniform(delay_min, delay_max))

        except ConnectionError:
            raise
        except Exception as e:
            # 400 means the API has no more pages for this query
            if "error code: 400" in str(e) or ": 400" in str(e):
                logger.info(f"End of results at page {page} (400).")
                break
            consecutive_errors += 1
            logger.warning(f"Error on page {page}: {e}")
            if consecutive_errors >= 3:
                logger.error("3 consecutive errors, stopping pagination.")
                raise ConnectionError(
                    f"Temporary block or network failure after fetching {len(all_items)} items."
                )
            wait = random.uniform(delay_min, delay_max) * (2 ** consecutive_errors)
            time.sleep(wait)
            try:
                scraper = _make_scraper()
                pages_since_refresh = 0
            except ConnectionError:
                pass

    return all_items[:max_items]
