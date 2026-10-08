from starlette.responses import JSONResponse

from stock_radar.security import access_role


class RequestBoundary:
    def __init__(self, app, settings, max_bytes: int = 1048576):
        self.app = app
        self.settings = settings
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["path"].rstrip("/") == "/mcp":
            headers = dict(scope["headers"])
            if access_role(headers.get(b"authorization", b"").decode("latin1"), self.settings) is None:
                await JSONResponse({"error": {"code": "unauthorized"}}, status_code=401, headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
                return
        messages = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.max_bytes:
                await JSONResponse({"error": {"code": "request_too_large"}}, status_code=413)(scope, receive, send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break
        index = 0

        async def replay():
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return await receive()

        await self.app(scope, replay, send)
