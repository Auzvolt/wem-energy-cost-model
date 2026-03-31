"""Authentication helpers for the WEM Energy Cost Model Streamlit app.

Credentials are loaded from the ``AUTH_CREDENTIALS_JSON`` environment variable
(a JSON object) or from ``st.secrets["credentials"]`` when running on
Streamlit Cloud.

Credential format::

    {
      "usernames": {
        "admin": {
          "name": "Administrator",
          "password": "<bcrypt_hash>",
          "role": "admin"
        },
        "analyst": {
          "name": "Analyst User",
          "password": "<bcrypt_hash>",
          "role": "analyst"
        }
      }
    }

Generate bcrypt hashes::

    python -c "import streamlit_authenticator as sa; print(sa.Hasher(['mypass']).generate())"
"""

from __future__ import annotations

import json
import logging
import os

import streamlit as st

from app.ui.session import USER_ROLE, USERNAME

logger = logging.getLogger(__name__)

_COOKIE_NAME = "wem_auth"
_COOKIE_KEY = "wem_auth_signature_key_change_me"
_COOKIE_EXPIRY_DAYS = 1


def _load_credentials() -> dict:  # type: ignore[type-arg]
    """Load credential config from env var or Streamlit secrets."""
    raw = os.getenv("AUTH_CREDENTIALS_JSON", "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.error("AUTH_CREDENTIALS_JSON is not valid JSON")
            return {"usernames": {}}

    # Try Streamlit secrets (Streamlit Cloud)
    try:
        return dict(st.secrets["credentials"])
    except (KeyError, FileNotFoundError):
        pass

    # No credentials configured — return empty (login always fails)
    logger.warning("No credentials configured. Set AUTH_CREDENTIALS_JSON env var.")
    return {"usernames": {}}


def login() -> bool:
    """Render login form and return True if the user is authenticated.

    Sets ``st.session_state[USER_ROLE]`` and ``st.session_state[USERNAME]``
    on successful login.

    Returns
    -------
    bool
        True if currently authenticated, False otherwise.
    """
    import streamlit_authenticator as stauth  # noqa: PLC0415

    credentials = _load_credentials()

    authenticator = stauth.Authenticate(
        credentials,
        _COOKIE_NAME,
        _COOKIE_KEY,
        _COOKIE_EXPIRY_DAYS,
    )

    _name, authentication_status, _username = authenticator.login(
        "Login", "main"
    )

    if authentication_status is True:
        # Store role in session state
        username = st.session_state.get("username", "")
        user_cfg = credentials.get("usernames", {}).get(username, {})
        role = user_cfg.get("role", "analyst")
        st.session_state[USER_ROLE] = role
        st.session_state[USERNAME] = username
        return True
    elif authentication_status is False:
        st.error("Invalid username or password.")
        return False
    else:
        st.info("Please enter your username and password.")
        return False


def logout() -> None:
    """Clear authentication session state."""
    for key in (USER_ROLE, USERNAME):
        st.session_state.pop(key, None)
    # Also clear streamlit_authenticator's cookie state
    for key in ("name", "username", "authentication_status"):
        st.session_state.pop(key, None)
