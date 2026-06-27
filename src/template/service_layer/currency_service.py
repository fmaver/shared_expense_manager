"""FX rate service: fetches the USD/ARS blue (informal) exchange rate from dolarapi.com."""

from datetime import datetime, timedelta
from typing import Optional

import requests

_CACHE_TTL_MINUTES = 10
_DOLAR_API_URL = "https://dolarapi.com/v1/dolares/blue"

_cache: dict = {"rate": None, "fetched_at": None}


def get_blue_rate() -> Optional[float]:
    """Return the current USD→ARS blue rate, using a 10-minute in-memory cache.

    Returns None if the API is unreachable or returns unexpected data.
    """
    now = datetime.now()
    if _cache["fetched_at"] is not None and (now - _cache["fetched_at"]) < timedelta(minutes=_CACHE_TTL_MINUTES):
        return _cache["rate"]

    try:
        response = requests.get(_DOLAR_API_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
        rate = float(data["venta"])
        _cache["rate"] = rate
        _cache["fetched_at"] = now
        return rate
    except requests.RequestException as exc:
        print(f"currency_service: failed to fetch blue rate: {exc}")
        return None
    except (KeyError, TypeError, ValueError) as exc:
        print(f"currency_service: unexpected response parsing blue rate: {exc}")
        return None


def get_rate_response() -> dict:
    """Return a dict suitable for the CurrencyRateResponse schema."""
    rate = get_blue_rate()
    return {"rate": rate, "currency": "USD", "source": "dolarapi.com/blue"}
