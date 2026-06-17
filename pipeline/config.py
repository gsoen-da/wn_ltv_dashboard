from pathlib import Path

PARQUET_PATH = Path("data/subscriptions.parquet")
INPUTS_DIR   = Path("file inputs")

# ── Auth ───────────────────────────────────────────────────────────────────────
# "oauth"           : sign in with your personal Google account (recommended).
#                     First run opens a browser window; token is cached after that.
# "service_account" : use a downloaded service-account JSON key.
AUTH_METHOD = "oauth"

# OAuth (AUTH_METHOD = "oauth"):
#   Download from Google Cloud Console → Credentials → OAuth 2.0 Client IDs → Desktop app
OAUTH_CLIENT_SECRETS = Path("client_secrets.json")
OAUTH_TOKEN_CACHE    = Path("token.json")       # written automatically after first login

# Service account (AUTH_METHOD = "service_account"):
CREDENTIALS_FILE = Path("credentials.json")

# ── Google Sheets ──────────────────────────────────────────────────────────────
# Extract the ID from the URL: docs.google.com/spreadsheets/d/<SHEET_ID>/edit
INTROS_SHEET_ID      = "1DROOTHg7H4D1-ty-gxmLPGSVXxd5TEzX68MW1JgL1jg"
INTROS_SHEET_TAB     = 0   # 0 = first tab

PRODUCT_MASTER_SHEET_ID  = "1LYudAHgU0FDIFUGBJACxXQCYSkoAsm0wLvSLi8w6X2M"
PRODUCT_MASTER_SHEET_TAB = 0

IVY_FIONA_SHEET_ID  = "1NEk7QHxkB0CXRBqhq1-ifG3SVu8mLaJ5LqpyPlgadlQ"
IVY_FIONA_SHEET_GID = 396227735   # worksheet gid from URL ?gid=396227735; emails in column B

QUIZ_SHEET_ID  = "15aAAP17B1PzXr088Ge1NQ6uuaPwy71PdH4IrTtWbEFY"
QUIZ_SHEET_GID = 0   # first tab; emails in column A

CONSULT_SHEET_ID  = "16nIcIBe6om6Ewtde-Sk2ATD51_xz6hLNMF6P9yrKqQU"
CONSULT_SHEET_GID = 0   # first tab; emails in column A

# ── Product master column config ───────────────────────────────────────────────
# To inspect column headers, run:
#   python -c "from pipeline.google_sheets import fetch_product_master_raw; df = fetch_product_master_raw(); print(df.columns.tolist())"
#
# PM_SKU_COL_IDX  : 0-based column index whose values match 'Product variant SKU' in the Shopify CSV.
#                   Column A in the sheet formula SUMIF(product_master!A:A, J, product_master!L:L) → index 0.
PM_SKU_COL_IDX   = 0

# PM_GROUP_COL    : Column header name for the product group label.
PM_GROUP_COL     = "product/group"

# PM_UNITS_COL_IDX: 0-based index for units-per-bundle.
#                   Column I in the sheet = product/quantity → index 8.
#                   (index 11 = product/recharge_variant_id — do not use)
PM_UNITS_COL_IDX = 8

# ── Bundle detection ───────────────────────────────────────────────────────────
# Rows whose Product variant SKU (as string) starts with this prefix are bundle
# parent rows: they carry net_sales but not the individual product detail.
# Individual products within the bundle appear as sibling rows with Net sales = 0.
BUNDLE_SKU_PREFIX = "700"
