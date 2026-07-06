"""FX rate service: fetches the USD/ARS blue (informal) exchange rate from dolarapi.com."""

from datetime import datetime, timedelta
from typing import Optional

import requests

_CACHE_TTL_MINUTES = 10
_FAILURE_RETRY_SECONDS = 60
_REQUEST_TIMEOUT_SECONDS = 3
_DOLAR_API_URL = "https://dolarapi.com/v1/dolares/blue"

_cache: dict = {"rate": None, "fetched_at": None, "next_retry_at": None}


def get_blue_rate() -> Optional[float]:
    """Return the current USD→ARS blue rate, using a 10-minute in-memory cache.

    On fetch failure the last known rate (or None) is served and no new
    attempt is made for _FAILURE_RETRY_SECONDS — otherwise every request
    would block on the external call for the full timeout while the API
    is down, holding its DB connection and starving the pool.
    """
    now = datetime.now()
    if _cache["fetched_at"] is not None and (now - _cache["fetched_at"]) < timedelta(minutes=_CACHE_TTL_MINUTES):
        return _cache["rate"]
    if _cache["next_retry_at"] is not None and now < _cache["next_retry_at"]:
        return _cache["rate"]

    try:
        response = requests.get(_DOLAR_API_URL, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        rate = float(data["venta"])
        _cache["rate"] = rate
        _cache["fetched_at"] = now
        _cache["next_retry_at"] = None
        return rate
    except requests.RequestException as exc:
        print(f"currency_service: failed to fetch blue rate: {exc}")
    except (KeyError, TypeError, ValueError) as exc:
        print(f"currency_service: unexpected response parsing blue rate: {exc}")

    _cache["next_retry_at"] = now + timedelta(seconds=_FAILURE_RETRY_SECONDS)
    return _cache["rate"]


def get_rate_response() -> dict:
    """Return a dict suitable for the CurrencyRateResponse schema."""
    rate = get_blue_rate()
    return {"rate": rate, "currency": "USD", "source": "dolarapi.com/blue"}
