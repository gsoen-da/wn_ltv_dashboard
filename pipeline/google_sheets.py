"""Fetch live reference data from Google Sheets.

Supports two auth methods (set AUTH_METHOD in config.py):

  "oauth" (default, recommended for personal use)
    - First run: opens a browser, you sign in with your Google account.
    - Token is cached in token.json — no re-login needed on subsequent runs.
    - No need to share sheets with anyone; you access them as yourself.
    - Setup: Google Cloud Console -> Credentials -> OAuth 2.0 Client ID (Desktop)
             Download JSON -> save as client_secrets.json

  "service_account"
    - Uses a service-account key file.
    - Requires sharing both sheets with the service account email.
    - Setup: Google Cloud Console -> IAM -> Service Accounts -> Create key
             Download JSON -> save as credentials.json
"""
import pandas as pd
import gspread
from google.auth.transport.requests import Request

from .config import (
    AUTH_METHOD,
    OAUTH_CLIENT_SECRETS, OAUTH_TOKEN_CACHE,
    CREDENTIALS_FILE,
    INTROS_SHEET_ID, INTROS_SHEET_TAB,
    PRODUCT_MASTER_SHEET_ID, PRODUCT_MASTER_SHEET_TAB,
    PM_SKU_COL_IDX, PM_GROUP_COL, PM_UNITS_COL_IDX,
    IVY_FIONA_SHEET_ID, IVY_FIONA_SHEET_GID,
    QUIZ_SHEET_ID, QUIZ_SHEET_GID,
    CONSULT_SHEET_ID, CONSULT_SHEET_GID,
)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _client() -> gspread.Client:
    if AUTH_METHOD == "oauth":
        return _oauth_client()
    return _service_account_client()


def _oauth_client() -> gspread.Client:
    """Authenticate via OAuth 2.0 using your personal Google account.

    Opens a browser on the first call; caches the token in token.json afterwards.
    """
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if OAUTH_TOKEN_CACHE.exists():
        creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_CACHE), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not OAUTH_CLIENT_SECRETS.exists():
                raise FileNotFoundError(
                    f"OAuth client secrets not found at '{OAUTH_CLIENT_SECRETS}'.\n"
                    "Download from Google Cloud Console -> Credentials -> "
                    "OAuth 2.0 Client IDs (Desktop app) and save as client_secrets.json."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(OAUTH_CLIENT_SECRETS), _SCOPES
            )
            creds = flow.run_local_server(port=0)

        OAUTH_TOKEN_CACHE.write_text(creds.to_json())

    return gspread.authorize(creds)


def _service_account_client() -> gspread.Client:
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(str(CREDENTIALS_FILE), scopes=_SCOPES)
    return gspread.authorize(creds)


# ── Public fetch functions ─────────────────────────────────────────────────────

def fetch_intro_emails() -> set[str]:
    """Return lowercase set of all emails in the intros master table (column A)."""
    try:
        ws = _client().open_by_key(INTROS_SHEET_ID).get_worksheet(INTROS_SHEET_TAB)
        return {v.strip().lower() for v in ws.col_values(1) if v.strip()}
    except Exception as exc:
        print(f"  [warn] Could not fetch intros sheet: {exc}")
        print("  [warn] Treating all customers as non-intro.")
        return set()


def fetch_ivy_fiona_emails() -> set[str]:
    """Return lowercase set of all emails in the Ivy/Fiona master table (column B)."""
    try:
        ws = _client().open_by_key(IVY_FIONA_SHEET_ID).get_worksheet_by_id(IVY_FIONA_SHEET_GID)
        return {v.strip().lower() for v in ws.col_values(2) if v.strip()}
    except Exception as exc:
        print(f"  [warn] Could not fetch ivy/fiona sheet: {exc}")
        print("  [warn] Treating all customers as non-ivy/fiona.")
        return set()


def fetch_quiz_emails() -> set[str]:
    """Return lowercase set of all emails in the Quiz uptake table (column A)."""
    try:
        ws = _client().open_by_key(QUIZ_SHEET_ID).get_worksheet_by_id(QUIZ_SHEET_GID)
        return {v.strip().lower() for v in ws.col_values(1) if v.strip()}
    except Exception as exc:
        print(f"  [warn] Could not fetch quiz sheet: {exc}")
        print("  [warn] Treating all customers as non-quiz.")
        return set()


def fetch_consult_emails() -> set[str]:
    """Return lowercase set of all emails in the Consult uptake table (column A)."""
    try:
        ws = _client().open_by_key(CONSULT_SHEET_ID).get_worksheet_by_id(CONSULT_SHEET_GID)
        return {v.strip().lower() for v in ws.col_values(1) if v.strip()}
    except Exception as exc:
        print(f"  [warn] Could not fetch consult sheet: {exc}")
        print("  [warn] Treating all customers as non-consult.")
        return set()


def fetch_product_master_raw() -> pd.DataFrame:
    """Return the full product master sheet as a DataFrame (headers from row 1)."""
    ws = _client().open_by_key(PRODUCT_MASTER_SHEET_ID).get_worksheet(PRODUCT_MASTER_SHEET_TAB)
    raw = ws.get_all_values()
    if len(raw) < 2:
        return pd.DataFrame()
    return pd.DataFrame(raw[1:], columns=raw[0])


def fetch_product_master() -> pd.DataFrame:
    """Return DataFrame[sku, product_group, units_per_bundle] keyed on Shopify SKU.

    sku             : matches 'Product variant SKU' in the Shopify CSV (string, no trailing .0)
    product_group   : human-readable product group name
    units_per_bundle: how many countable units this SKU represents (1 for singles, >1 for packs)
    """
    try:
        raw = fetch_product_master_raw()
        if raw.empty:
            return _empty_pm()

        sku_col = raw.iloc[:, PM_SKU_COL_IDX].astype(str).str.strip()

        if PM_GROUP_COL in raw.columns:
            group_col = raw[PM_GROUP_COL].str.strip()
        else:
            print(f"  [warn] '{PM_GROUP_COL}' not found in product master.")
            print(f"  [warn] Available columns: {raw.columns.tolist()}")
            print(f"  [warn] Update PM_GROUP_COL in pipeline/config.py to match.")
            group_col = pd.Series([""] * len(raw))

        if PM_UNITS_COL_IDX < len(raw.columns):
            units_col = pd.to_numeric(raw.iloc[:, PM_UNITS_COL_IDX], errors="coerce").fillna(1)
        else:
            units_col = pd.Series([1.0] * len(raw))

        pm = pd.DataFrame({
            "sku": sku_col,
            "product_group": group_col.replace("", pd.NA),
            "units_per_bundle": units_col.astype(int),
        })
        pm = pm[pm["sku"].str.len() > 0].drop_duplicates("sku").reset_index(drop=True)
        return pm

    except Exception as exc:
        print(f"  [warn] Could not fetch product master: {exc}")
        print("  [warn] SKU->product_group mapping will be skipped.")
        return _empty_pm()


def _empty_pm() -> pd.DataFrame:
    return pd.DataFrame(columns=["sku", "product_group", "units_per_bundle"])
