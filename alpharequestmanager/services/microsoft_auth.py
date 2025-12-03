# alpharequestmanager/microsoft_auth.py

from msal import ConfidentialClientApplication
from fastapi import Request
from alpharequestmanager.utils.config import config

AUTHORITY = f"https://login.microsoftonline.com/{config.TENANT_ID}"
SCOPES = config.SCOPE

def build_msal_app():
    return ConfidentialClientApplication(
        client_id=config.CLIENT_ID,
        authority=AUTHORITY,
        client_credential=config.CLIENT_SECRET
    )

def initiate_auth_flow(request: Request):
    app = build_msal_app()
    flow = app.initiate_auth_code_flow(
        scopes=SCOPES,
        redirect_uri=config.REDIRECT_URI,

    )
    request.session["auth_flow"] = flow
    return flow["auth_uri"]

def acquire_token_by_auth_code(request: Request):
    app = build_msal_app()
    flow = request.session.get("auth_flow")
    if not flow:
        raise ValueError("OAuth Flow fehlt in Session")

    # Fix: QueryParams → dict
    return app.acquire_token_by_auth_code_flow(flow, dict(request.query_params))


def acquire_app_token() -> dict:
    """
    Holt ein App-Only Token für Graph (Client Credentials Flow).
    Benötigt Application Permission 'User.Read.All'.
    """
    app = build_msal_app()
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])

    if "access_token" not in result:
        raise Exception(f"App token acquisition failed: {result.get('error_description')}")

    return result
