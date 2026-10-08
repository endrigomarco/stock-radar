from secrets import compare_digest

from fastapi import HTTPException, Request

from stock_radar.settings import Settings


def access_role(authorization: str, settings: Settings) -> str | None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    if compare_digest(token.encode(), settings.collector_token.get_secret_value().encode()):
        return "collector"
    if compare_digest(token.encode(), settings.reader_token.get_secret_value().encode()):
        return "reader"
    return None


def require_reader(request: Request) -> str:
    role = access_role(request.headers.get("authorization", ""), request.app.state.settings)
    if role is None:
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"})
    return role


def require_collector(request: Request) -> None:
    if require_reader(request) != "collector":
        raise HTTPException(status_code=403, detail="Forbidden")


def require_webhook(request: Request) -> None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    expected = request.app.state.settings.webhook_token.get_secret_value()
    if scheme.lower() != "bearer" or not compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"})
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="JSON content type required")
