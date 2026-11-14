"""Earthdata Login through ``earthaccess``, configured only from the local environment.

Credentials are read by earthaccess from ``EARTHDATA_USERNAME`` / ``EARTHDATA_PASSWORD`` or ``EARTHDATA_TOKEN`` (or a
local ``.netrc``). This module never reads, stores, logs or returns them.
"""

from __future__ import annotations

import os
from typing import Any

from app.errors import AppError


def credentials_configured() -> bool:
    """True when some local credential source exists. Says nothing about whether NASA will accept it."""
    env = os.environ
    if env.get("EARTHDATA_TOKEN") or (env.get("EARTHDATA_USERNAME") and env.get("EARTHDATA_PASSWORD")):
        return True
    home = os.path.expanduser("~")
    return any(os.path.exists(os.path.join(home, n)) for n in (".netrc", "_netrc"))


def earthdata_session() -> Any:
    """Return an authenticated ``requests`` session that follows the Earthdata Login redirect."""
    if not credentials_configured():
        raise AppError(
            401,
            "earthdata_credentials_missing",
            "No Earthdata Login credentials are configured. Set EARTHDATA_USERNAME and EARTHDATA_PASSWORD (or EARTHDATA_TOKEN) in the environment that runs the backend.",
        )
    import earthaccess  # imported lazily: it is only needed for authenticated access

    try:
        auth = earthaccess.login(strategy="environment", persist=False)
    except Exception as exc:  # noqa: BLE001 - never echo the underlying message, it can mention the account
        raise AppError(401, "earthdata_login_failed", f"Earthdata Login failed ({type(exc).__name__}). Check the configured credentials.") from None
    if not getattr(auth, "authenticated", False):
        raise AppError(401, "earthdata_login_failed", "Earthdata Login did not accept the configured credentials.")
    return earthaccess.get_requests_https_session()
