"""Integration test package.

Integration tests require a live database and are excluded from the default
unit-test run.  Run them with::

    pytest -m integration tests/integration/

or via the CI integration job which sets ``DATABASE_URL`` to a real
PostgreSQL instance.
"""
