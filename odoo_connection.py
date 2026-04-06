"""Shared Odoo XML-RPC connection for helpdesk and sales MCP servers."""

import os
import xmlrpc.client
from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv()

ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USERNAME = os.getenv("ODOO_USERNAME")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_API_KEY")

_odoo_cache: Dict[str, Any] = {"uid": None, "models": None}


def get_odoo_connection():
    if not all([ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD]):
        raise ValueError("Missing Odoo credentials in environment variables")

    if _odoo_cache["uid"] and _odoo_cache["models"]:
        return _odoo_cache["uid"], _odoo_cache["models"]

    url = ODOO_URL.rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    try:
        uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
        if not uid:
            raise PermissionError("Authentication failed. Please check your credentials.")
        models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
        _odoo_cache["uid"] = uid
        _odoo_cache["models"] = models
        return uid, models
    except Exception as e:
        raise ConnectionError(f"Failed to connect to Odoo: {str(e)}") from e
