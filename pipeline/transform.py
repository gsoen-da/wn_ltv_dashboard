"""Core transformation logic: Shopify CSV → enriched order-product rows → parquet."""
import pandas as pd
from pathlib import Path

from .config import BUNDLE_SKU_PREFIX, PARQUET_PATH

# Dedup key: one row per (day, order, product).
# product_variant_sku and product_title are both included so rows with a null
# SKU but different product titles are not collapsed into one.
_DEDUP_KEYS = ["day", "order_name", "product_variant_sku", "product_title"]

_SUB_CHANNELS = {"Recharge Subscriptions"}
_SUB_TYPES    = {"subscription"}

_FINAL_COLS = [
    "day", "customer_cohort_month", "order_name", "customer_id", "customer_email",
    "new_or_returning", "subscription_or_one_time", "sales_channel",
    "order_net_sales", "net_sales",
    "product_title", "product_variant_sku", "product_group",
    "net_items_sold", "units_per_bundle", "units_sold",
    "is_bundle_item", "has_bundle",
    "intro_client", "ivy_fiona_client", "quiz_client", "consult_client",
    "subscription_order_num", "banding", "items_in_order", "order_gross_sales",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _normalize_sku(v) -> str | None:
    if pd.isna(v):
        return None
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


def _is_sub_row(row: pd.Series) -> bool:
    return row["sales_channel"] in _SUB_CHANNELS or row["subscription_or_one_time"] in _SUB_TYPES


# ── Transform ──────────────────────────────────────────────────────────────────

def transform_csv(
    csv_path: str,
    product_master: pd.DataFrame,
    intro_emails: set[str],
    ivy_fiona_emails: set[str] | None = None,
    quiz_emails: set[str] | None = None,
    consult_emails: set[str] | None = None,
) -> pd.DataFrame:
    """Load a Shopify subscription CSV and return enriched order-product rows.

    One row per (order × product line).  Bundle parent rows (SKU prefix '700')
    are dropped — their revenue is captured at the order level via order_net_sales.
    Individual products inside bundles are retained (Net sales = 0 on those rows
    but order_net_sales reflects the true bundle price).
    """
    raw = pd.read_csv(csv_path, low_memory=False)
    raw["Day"] = pd.to_datetime(raw["Day"])

    df = raw.rename(columns={
        "Day":                          "day",
        "Customer cohort month":        "customer_cohort_month",
        "Order name":                   "order_name",
        "New or returning customer":    "new_or_returning",
        "Subscription or one-time":     "subscription_or_one_time",
        "Sales channel":                "sales_channel",
        "Customer ID":                  "customer_id",
        "Product title at time of sale":"product_title",
        "Customer email":               "customer_email",
        "Product variant SKU":          "_sku_raw",
        "Net sales":                    "net_sales",
        "Net items sold":               "net_items_sold",
    })

    df["customer_cohort_month"]  = pd.to_datetime(df["customer_cohort_month"], errors="coerce")
    df["new_or_returning"]       = df["new_or_returning"].fillna("Returning")
    df["subscription_or_one_time"] = df["subscription_or_one_time"].fillna("")
    df["sales_channel"]          = df["sales_channel"].fillna("")
    df["customer_id"]            = pd.to_numeric(df["customer_id"], errors="coerce").astype("Int64")
    df["net_items_sold"]         = pd.to_numeric(df["net_items_sold"], errors="coerce").fillna(0).astype(int)
    df["net_sales"]              = pd.to_numeric(df["net_sales"], errors="coerce").fillna(0.0)
    df["product_variant_sku"]    = df["_sku_raw"].apply(_normalize_sku)
    df = df.drop(columns=["_sku_raw"])

    # ── Order-level revenue (before any row filtering) ─────────────────────────
    # Bundle parent row (700* SKU) carries net_sales; sibling product rows show 0.
    # Summing per order correctly captures the full order value.
    order_net_sales = (
        df.groupby("order_name")["net_sales"]
        .sum()
        .rename("order_net_sales")
    )

    # ── Bundle detection ───────────────────────────────────────────────────────
    is_bundle_parent = df["product_variant_sku"].str.startswith(BUNDLE_SKU_PREFIX, na=False)
    bundle_order_names = set(df.loc[is_bundle_parent, "order_name"])
    df["has_bundle"]     = df["order_name"].isin(bundle_order_names)
    df["is_bundle_item"] = df["has_bundle"] & ~is_bundle_parent & df["product_variant_sku"].notna()

    # ── Subscription type propagation ─────────────────────────────────────────
    # Bundle children are often marked "one_time" in the CSV even when the parent
    # row (which carries the revenue and the correct sub type) is "subscription".
    # Override all rows in a bundle-subscription order to "subscription".
    bundle_parent_sub = (
        df[is_bundle_parent]
        .groupby("order_name")["subscription_or_one_time"]
        .first()
    )
    sub_bundle_orders = bundle_parent_sub[bundle_parent_sub == "subscription"].index
    df.loc[df["order_name"].isin(sub_bundle_orders), "subscription_or_one_time"] = "subscription"

    # For non-bundle orders with empty sub_type, fill from any non-empty row
    order_sub_first = (
        df[df["subscription_or_one_time"] != ""]
        .groupby("order_name")["subscription_or_one_time"]
        .first()
    )
    empty_sub = df["subscription_or_one_time"] == ""
    df.loc[empty_sub, "subscription_or_one_time"] = (
        df.loc[empty_sub, "order_name"].map(order_sub_first).fillna("")
    )

    # Drop bundle PURCHASE parent rows (700*+ with net_sales >= 0) — their
    # revenue is already captured in order_net_sales above.
    # Keep bundle REFUND parent rows (700* with net_sales < 0): these carry
    # negative revenue that would otherwise be silently lost, causing us to
    # over-count revenue vs Shopify for months that had bundle refunds.
    drop_bundle_parent = is_bundle_parent & (df["net_sales"] >= 0)
    df = df[~drop_bundle_parent].copy()
    # Recompute is_bundle_parent mask after filtering (used below for is_bundle_item)
    is_bundle_parent = df["product_variant_sku"].str.startswith(BUNDLE_SKU_PREFIX, na=False)

    # Drop rows with no product identity (ghost/aggregate rows in the Shopify export)
    has_identity = df["product_variant_sku"].notna() | df["product_title"].notna()
    df = df[has_identity].copy()

    # Attach order-level revenue
    df = df.join(order_net_sales, on="order_name")

    # ── Product master join ────────────────────────────────────────────────────
    if not product_master.empty:
        df = df.merge(product_master, left_on="product_variant_sku", right_on="sku", how="left")
        df = df.drop(columns=["sku"], errors="ignore")
    else:
        df["product_group"]    = pd.NA
        df["units_per_bundle"] = 1

    df["units_per_bundle"] = pd.to_numeric(df.get("units_per_bundle", 1), errors="coerce").fillna(1).astype(int)
    df["units_sold"]       = df["net_items_sold"] * df["units_per_bundle"]

    # ── Intro client flag ──────────────────────────────────────────────────────
    # Matched case-insensitively against the intros master table email column.
    df["intro_client"] = (
        df["customer_email"]
        .str.lower()
        .str.strip()
        .isin(intro_emails)
    )

    # ── Ivy/Fiona client flag ──────────────────────────────────────────────────
    _ivy = ivy_fiona_emails if ivy_fiona_emails is not None else set()
    df["ivy_fiona_client"] = (
        df["customer_email"]
        .str.lower()
        .str.strip()
        .isin(_ivy)
    )

    # ── Quiz / Consult uptake flags ────────────────────────────────────────────
    _email = df["customer_email"].str.lower().str.strip()
    df["quiz_client"]    = _email.isin(quiz_emails    if quiz_emails    is not None else set())
    df["consult_client"] = _email.isin(consult_emails if consult_emails is not None else set())

    # Derived fields are placeholders — computed across full history in append_to_parquet
    df["subscription_order_num"] = 0
    df["banding"]                = ""
    df["items_in_order"]         = 0
    df["order_gross_sales"]      = 0.0

    return df[_FINAL_COLS].copy()


# ── Derived field calculation (across full history) ────────────────────────────

def assign_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Compute subscription_order_num, banding, items_in_order on the full dataset."""
    df = df.copy()

    # ── Recompute order_net_sales for non-bundle orders (per order per month) ─────
    # order_net_sales is captured at CSV ingest time. When a same-month refund
    # arrives in a later CSV (same calendar month, different day), both rows
    # survive dedup and the original row's order_net_sales remains the pre-refund
    # amount. Re-summing per (order, month) corrects this while preserving
    # Shopify's monthly-attribution model: purchases appear in their placement
    # month, cross-period refunds (different month) remain as separate rows with
    # negative order_net_sales and are filtered out by the >0 check in reports.
    # Bundle orders excluded: child rows all have net_sales=0 (revenue is on the
    # dropped parent), so summing would zero out bundle revenue.
    df["_month"] = df["day"].dt.to_period("M")
    nb_mask = ~df["has_bundle"]
    nb_rev = (
        df[nb_mask]
        .groupby(["order_name", "_month"])["net_sales"]
        .sum()
        .rename("_nb_rev")
    )
    df = df.join(nb_rev, on=["order_name", "_month"])
    df.loc[nb_mask, "order_net_sales"] = df.loc[nb_mask, "_nb_rev"]
    df = df.drop(columns=["_nb_rev", "_month"])

    # ── Subscription order numbering ───────────────────────────────────────────
    # Count only rows that are subscription type — one sequence per customer.
    is_sub = (
        df["sales_channel"].isin(_SUB_CHANNELS)
        | (df["subscription_or_one_time"] == "subscription")
    )

    order_seq = (
        df.loc[is_sub, ["customer_id", "order_name", "day"]]
        .drop_duplicates(subset=["customer_id", "order_name"])
        .sort_values(["customer_id", "day", "order_name"])
    )
    order_seq["subscription_order_num"] = (
        order_seq.groupby("customer_id").cumcount() + 1
    )

    df = df.drop(columns=["subscription_order_num", "banding", "items_in_order", "order_gross_sales"], errors="ignore")

    # ── Order gross sales (per order per month) ────────────────────────────────
    # max(order_net_sales, sum_of_positive_net_sales_rows_in_month), clipped to 0.
    #
    # Why not just order_net_sales > 0?
    # - Bundle orders: order_net_sales is correct (captured from parent before drop),
    #   but net_sales on child rows is 0. order_net_sales handles these fine.
    # - Purchase+refund pairs in the same CSV: both rows exist, net sums to 0, so
    #   order_net_sales = 0. But the subscription WAS placed — we want to count it,
    #   matching the weekly dashboard's row-level "Net sales > 0" filter. The
    #   per-month sum of positive rows captures this correctly.
    # - Pure refunds / zero-revenue orders: both terms are 0 or negative → excluded.
    _month = df["day"].dt.to_period("M")
    _df_m  = df.assign(_month=_month)
    _monthly_pos = (
        _df_m[_df_m["net_sales"] > 0]
        .groupby(["order_name", "_month"])["net_sales"]
        .sum()
        .rename("_pos_sales")
    )
    df = _df_m.join(_monthly_pos, on=["order_name", "_month"])
    df["_pos_sales"] = df["_pos_sales"].fillna(0.0)
    df["order_gross_sales"] = df[["order_net_sales", "_pos_sales"]].max(axis=1).clip(lower=0)
    df = df.drop(columns=["_month", "_pos_sales"])
    df = df.merge(
        order_seq[["customer_id", "order_name", "subscription_order_num"]],
        on=["customer_id", "order_name"],
        how="left",
    )
    df["subscription_order_num"] = df["subscription_order_num"].fillna(0).astype(int)

    # ── Banding ────────────────────────────────────────────────────────────────
    # Formula (from customer banding mapping.png):
    #   =IF(intro="No", IF(new="New","Core 1","Core 2"),
    #                   IF(new="New","Intro 1",
    #                      IF(order_num<4,"Intro 2-3","Intro 4")))
    def _banding(row) -> str:
        if not row["intro_client"]:
            return "Core 1" if row["new_or_returning"] == "New" else "Core 2"
        if row["new_or_returning"] == "New":
            return "Intro 1"
        return "Intro 2-3" if row["subscription_order_num"] < 4 else "Intro 4"

    df["banding"] = df.apply(_banding, axis=1)

    # ── Items in order ─────────────────────────────────────────────────────────
    # For non-bundle orders: count only paid rows (net_sales != 0), matching the
    # spreadsheet's K≠0 anchor logic. For bundle orders: sum all child rows
    # (children already have net_sales=0 in the CSV, so K≠0 filter would yield 0;
    # summing all children is the closest practical equivalent).
    if "net_sales" in df.columns:
        non_bundle_items = (
            df[~df["has_bundle"] & (df["net_sales"] != 0)]
            .groupby("order_name")["units_sold"].sum()
        )
        bundle_items = (
            df[df["is_bundle_item"]]   # child items only; excludes 700* refund rows
            .groupby("order_name")["units_sold"].sum()
        )
        items_per_order = pd.concat([non_bundle_items, bundle_items]).rename("items_in_order")
    else:
        items_per_order = df.groupby("order_name")["units_sold"].sum().rename("items_in_order")
    df = df.join(items_per_order, on="order_name")

    return df


# ── Parquet I/O ────────────────────────────────────────────────────────────────

def load_parquet() -> pd.DataFrame | None:
    if PARQUET_PATH.exists():
        return pd.read_parquet(PARQUET_PATH)
    return None


def append_to_parquet(new_df: pd.DataFrame) -> pd.DataFrame:
    """Merge new rows into the parquet, recompute all derived fields, save.

    Idempotent: re-ingesting the same CSV produces the same result.
    New rows win on conflict (latest ingest wins).
    """
    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)

    _DERIVED = ["subscription_order_num", "banding", "items_in_order", "order_gross_sales"]

    existing = load_parquet()
    if existing is not None:
        existing_raw = existing.drop(columns=_DERIVED, errors="ignore")
        new_raw      = new_df.drop(columns=_DERIVED, errors="ignore")
        combined     = pd.concat([existing_raw, new_raw], ignore_index=True)
    else:
        combined = new_df.drop(columns=_DERIVED, errors="ignore").copy()

    # Back-fill boolean flags that may be absent in older parquet versions
    for _flag in ("intro_client", "ivy_fiona_client", "quiz_client", "consult_client"):
        if _flag not in combined.columns:
            combined[_flag] = False
        else:
            combined[_flag] = combined[_flag].fillna(False)

    # Dedup: fill sentinel values so NaN cells don't falsely collapse
    dedup_filled = combined.fillna({
        "product_variant_sku": "__NULL__",
        "product_title":       "__NULL__",
    })
    keep_mask = ~dedup_filled.duplicated(subset=_DEDUP_KEYS, keep="last")
    combined  = combined[keep_mask].copy()

    combined = assign_derived_fields(combined)
    combined = combined.sort_values(["day", "order_name", "product_variant_sku"]).reset_index(drop=True)

    combined.to_parquet(PARQUET_PATH, index=False)
    print(f"  Saved: {len(combined):,} rows -> {PARQUET_PATH}")
    return combined
