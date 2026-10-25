import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_refuses_the_development_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(app_env="production")


def test_production_refuses_a_short_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(app_env="production", jwt_secret="short")  # type: ignore[arg-type]


def test_cors_origins_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://admin.example.com")
    assert Settings().cors_origins == ["http://localhost:3000", "https://admin.example.com"]
