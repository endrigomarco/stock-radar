from fastapi import APIRouter, Depends, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from stock_radar.security import require_reader

router = APIRouter()


@router.get("/metrics", dependencies=[Depends(require_reader)], include_in_schema=False)
def metrics(request: Request) -> Response:
    return Response(generate_latest(request.app.state.telemetry.registry), headers={"Content-Type": CONTENT_TYPE_LATEST})
