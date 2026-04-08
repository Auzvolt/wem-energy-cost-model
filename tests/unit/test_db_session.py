"""Tests for app.db.session URL helpers."""

# Import the private helpers directly so we can unit-test them without spinning
# up a real database engine.
from app.db.session import _PLACEHOLDER_URL, _ensure_ssl


class TestEnsureSsl:
    """_ensure_ssl() should append sslmode=require for remote hosts only."""

    def test_remote_url_gets_ssl_appended(self) -> None:
        url = "postgresql://user:pass@db.supabase.co:5432/wem_energy"
        result = _ensure_ssl(url)
        assert result == f"{url}?sslmode=require"

    def test_remote_url_with_existing_query_param_uses_ampersand(self) -> None:
        url = "postgresql://user:pass@db.supabase.co:5432/wem_energy?connect_timeout=10"
        result = _ensure_ssl(url)
        assert "sslmode=require" in result
        assert result.count("?") == 1  # only one query-string separator

    def test_does_not_duplicate_sslmode(self) -> None:
        url = "postgresql://user:pass@db.supabase.co:5432/wem_energy?sslmode=require"
        assert _ensure_ssl(url) == url

    def test_existing_sslmode_disable_is_preserved(self) -> None:
        url = "postgresql://user:pass@db.supabase.co:5432/wem_energy?sslmode=disable"
        assert _ensure_ssl(url) == url

    def test_localhost_does_not_get_ssl(self) -> None:
        url = "postgresql://user:pass@localhost:5432/wem_energy"
        assert _ensure_ssl(url) == url

    def test_127_0_0_1_does_not_get_ssl(self) -> None:
        url = "postgresql://user:pass@127.0.0.1:5432/wem_energy"
        assert _ensure_ssl(url) == url


class TestPlaceholderUrl:
    """_PLACEHOLDER_URL must match what config.py returns as the default."""

    def test_placeholder_matches_config_default(self) -> None:
        # This ensures the sentinel comparison in _get_database_url() will
        # correctly detect when DATABASE_URL was not set in the environment.
        assert _PLACEHOLDER_URL == "postgresql://user:password@localhost:5432/wem_energy"
