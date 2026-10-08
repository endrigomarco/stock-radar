from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://brapi.dev/api"
TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 1024 * 1024
PRICE_QUANTUM = Decimal("0.00000001")
MAX_PRICE = Decimal("1e16")
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{1,12}$")


class QuoteError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Quote:
    symbol: str
    currency: str
    price: Decimal
    quoted_at: datetime


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_quote(symbol: str, currency: str, api_key: str, base_url: str = BASE_URL, timeout: float = TIMEOUT_SECONDS) -> Quote:
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise QuoteError("unsupported_symbol")
    request = Request(
        f"{base_url}/quote/{quote(symbol, safe='')}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "User-Agent": "stock-radar/0.1"},
    )
    try:
        with build_opener(_NoRedirect).open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        raise QuoteError(f"provider_http_{error.code}") from None
    except (URLError, TimeoutError, OSError):
        raise QuoteError("provider_unavailable") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise QuoteError("provider_response_too_large")
    return parse_quote(body, symbol, currency)


def parse_quote(body: bytes, symbol: str, currency: str) -> Quote:
    try:
        payload = json.loads(body, parse_float=Decimal, parse_int=Decimal)
    except (ValueError, InvalidOperation):
        raise QuoteError("provider_invalid_json") from None
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise QuoteError("provider_unexpected_shape")
    result = results[0]
    if result.get("symbol") != symbol:
        raise QuoteError("provider_symbol_mismatch")
    if result.get("currency") != currency:
        raise QuoteError("provider_currency_mismatch")
    price = result.get("regularMarketPrice")
    if not isinstance(price, Decimal) or not price.is_finite() or not 0 < price < MAX_PRICE:
        raise QuoteError("provider_invalid_price")
    price = price.quantize(PRICE_QUANTUM)
    if price <= 0:
        raise QuoteError("provider_invalid_price")
    return Quote(symbol=symbol, currency=currency, price=price, quoted_at=_parse_time(result.get("regularMarketTime")))


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise QuoteError("provider_invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise QuoteError("provider_invalid_timestamp") from None
    if parsed.tzinfo is None:
        raise QuoteError("provider_invalid_timestamp")
    return parsed.astimezone(timezone.utc)
