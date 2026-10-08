from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, text
from sqlalchemy.exc import DBAPIError

from stock_radar.app import create_app
from stock_radar.db.config import database_url
from stock_radar.db.models import Source
from stock_radar.settings import Settings


def main() -> None:
    settings = Settings.from_environment()
    admin = create_engine(database_url())
    with admin.begin() as connection:
        connection.execute(Source.__table__.insert(), [
            {"code": "api_alpha", "name": "Alpha", "base_url": "https://example.invalid/private"},
            {"code": "api_beta", "name": "Beta", "base_url": None},
        ])
    try:
        headers = {"Authorization": f"Bearer {settings.reader_token.get_secret_value()}"}
        with TestClient(create_app(settings)) as client:
            assert client.get("/health/live").status_code == 200
            assert client.get("/health/ready").status_code == 401
            assert client.get("/v1/sources").status_code == 401
            assert client.get("/v1/sources", headers={"Authorization": "Bearer invalid"}).status_code == 401
            assert client.get("/health/ready", headers=headers).status_code == 200
            response = client.get("/v1/sources?limit=1", headers=headers)
            assert response.status_code == 200
            page = response.json()
            assert page["has_more"] and len(page["items"]) == 1
            assert set(page["items"][0]) == {"id", "code", "name"}
            assert "private" not in response.text
            assert client.get("/v1/sources?limit=1&offset=1", headers=headers).json()["items"][0]["code"] == "api_beta"
            assert client.get("/v1/sources?code=API_ALPHA", headers=headers).json()["items"][0]["code"] == "api_alpha"
            for query in ["limit=101", "offset=-1", "code=bad%27sql", "unexpected=secret"]:
                response = client.get("/v1/sources?" + query, headers=headers)
                assert response.status_code == 422
                assert "secret" not in response.text
            assert client.post("/v1/sources", json={}, headers=headers).status_code == 403
        reader = create_engine(settings.database_url())
        for statement in ["INSERT INTO sources (code, name) VALUES ('forbidden', 'Forbidden')", "SELECT * FROM webhook_receipts"]:
            try:
                with reader.begin() as connection:
                    connection.execute(text(statement))
            except DBAPIError as error:
                assert error.orig.sqlstate == "42501"
            else:
                raise AssertionError("Reader exceeded its database grants")
        reader.dispose()
        try:
            Settings(reader_token="short", database_password="short", database_name="test")
        except ValidationError:
            pass
        else:
            raise AssertionError("Weak configuration accepted")
        bad = settings.model_copy(update={"database_name": "missing_synthetic_database"})
        with TestClient(create_app(bad)) as client:
            response = client.get("/v1/sources", headers=headers)
            assert response.status_code == 503
            assert response.json() == {"error": {"code": "database_unavailable"}}
    finally:
        with admin.begin() as connection:
            connection.execute(delete(Source).where(Source.code.in_(["api_alpha", "api_beta"])))
        admin.dispose()
    print("API checks passed: authentication, validation, transformations, pagination and database privileges.")


if __name__ == "__main__":
    main()
