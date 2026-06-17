"""Generate Output 1 (new subscriptions tracker) and Output 2 (period banding summary)."""
import pandas as pd
from .config import PARQUET_PATH
from . import product_short_names as _psn

_SUB_CHANNELS = {"Recharge Subscriptions"}
_SUB_TYPES    = {"subscription"}


def _load() -> pd.DataFrame:
    if not PARQUET_PATH.exists():
        raise FileNotFoundError(
            f"Parquet not found at {PARQUET_PATH}. Run `python ingest.py` first."
        )
    return pd.read_parquet(PARQUET_PATH)


def _is_subscription(df: pd.DataFrame) -> pd.Series:
    """Row-level flag: True if this product row is from a subscription."""
    return (
        df["sales_channel"].isin(_SUB_CHANNELS)
        | (df["subscription_or_one_time"] == "subscription")
    )


def _order_is_subscription(df: pd.DataFrame) -> pd.Series:
    """Order-level flag: True for ALL rows of an order if ANY row is a subscription.

    Handles bundle orders where children are labelled 'one_time' in Shopify but
    the parent (dropped at ingest) was 'subscription'.  Using this instead of
    _is_subscription ensures mixed orders are counted as subscription orders.
    """
    return _is_subscription(df).groupby(df["order_name"]).transform("max")


def _order_level(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse to one row per order_name, keeping order-level fields."""
    cols = [
        "day", "order_name", "customer_id",
        "new_or_returning", "sales_channel", "subscription_or_one_time",
        "order_net_sales", "has_bundle", "intro_client",
        "subscription_order_num", "banding", "items_in_order",
    ]
    for flag in ("ivy_fiona_client", "quiz_client", "consult_client"):
        if flag in df.columns:
            cols.append(flag)
    return df[cols].drop_duplicates(subset=["order_name"]).copy()


def _top3_products(
    prod_df: pd.DataFrame,
    order_names: pd.Index | set,
    total_units: float = 0.0,
    short_names: dict[str, str] | None = None,
) -> list[str]:
    """Top 3 product_groups by units_sold.

    If total_units > 0, each entry is formatted 'Short (X%)' where X is the
    product's share of total_units — the denominator is always the caller's
    total (all orders in the month), so single-item and overall percentages
    are directly comparable.
    short_names maps product_group → display label; falls back to full name.
    """
    # Mirror items_in_order logic: exclude zero-price non-bundle rows (free add-ons
    # such as a Wellbeing Scoop included at £0 alongside a paid Collagen order).
    # Bundle child rows (is_bundle_item=True, net_sales=0) are kept.
    counted = prod_df[(prod_df["net_sales"] != 0) | prod_df["is_bundle_item"]]
    sub = counted[counted["order_name"].isin(order_names) & counted["product_group"].notna()]
    if sub.empty:
        return []
    top3 = (
        sub.groupby("product_group")["units_sold"]
        .sum()
        .nlargest(3)
    )
    sn = short_names or {}
    if total_units > 0:
        return [f"{sn.get(name, name)} ({v / total_units * 100:.0f}%)" for name, v in top3.items()]
    return [sn.get(name, name) for name in top3.index]


# ── Output 1: New Subscriptions Tracker ───────────────────────────────────────

def output1(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Month-by-month tracker for NEW subscription orders only.

    Mirrors the layout in OUTPUT_1.png:
      AOV, ASP, IPO, # new subs, % intro, % bundle, % intro <£20 AOV,
      # single-item subs, single-item %, top-3 products, single-item top-3.
    """
    if df is None:
        df = _load()

    short_names = _psn.load()

    is_new_sub = (
        (df["new_or_returning"] == "New")
        & _order_is_subscription(df)
        & (df["order_net_sales"] > 0)
    )
    sub = df[is_new_sub].copy()
    sub["month"] = sub["day"].dt.to_period("M")

    orders = _order_level(sub)
    orders["month"] = orders["day"].dt.to_period("M")

    rows = []
    for month, o_grp in orders.groupby("month", sort=True):
        p_grp = sub[sub["month"] == month]

        n_orders    = o_grp["order_name"].nunique()
        total_rev   = o_grp["order_net_sales"].sum()
        paid_rows   = p_grp[(p_grp["net_sales"] != 0) | p_grp["is_bundle_item"]]
        total_units = paid_rows["units_sold"].sum()

        aov = total_rev / n_orders    if n_orders    else 0.0
        asp = total_rev / total_units if total_units else 0.0
        ipo = total_units / n_orders  if n_orders    else 0.0

        n_intro  = o_grp["intro_client"].sum()
        n_bundle = o_grp["has_bundle"].sum()
        n_intro_under_20 = (
            o_grp[o_grp["intro_client"] & (o_grp["order_net_sales"] < 20)]
            .shape[0]
        )
        n_ivy_fiona = o_grp["ivy_fiona_client"].sum() if "ivy_fiona_client" in o_grp.columns else 0
        n_quiz      = o_grp["quiz_client"].sum()      if "quiz_client"      in o_grp.columns else 0
        n_consult   = o_grp["consult_client"].sum()   if "consult_client"   in o_grp.columns else 0

        # Combined uptake: orders with EITHER quiz OR consult (avoiding double-count if both)
        if "quiz_client" in o_grp.columns and "consult_client" in o_grp.columns:
            n_combined = (o_grp["quiz_client"] | o_grp["consult_client"]).sum()
        else:
            n_combined = 0

        pct_intro          = n_intro     / n_orders * 100 if n_orders else 0.0
        pct_bundle         = n_bundle    / n_orders * 100 if n_orders else 0.0
        pct_intro_under_20 = n_intro_under_20 / n_intro * 100 if n_intro else 0.0
        pct_ivy_fiona      = n_ivy_fiona / n_orders * 100 if n_orders else 0.0
        pct_quiz           = n_quiz      / n_orders * 100 if n_orders else 0.0
        pct_consult        = n_consult   / n_orders * 100 if n_orders else 0.0
        pct_combined_uptake = n_combined / n_orders * 100 if n_orders else 0.0

        single_mask  = o_grp["items_in_order"] == 1
        n_single     = single_mask.sum()
        pct_single   = n_single / n_orders * 100 if n_orders else 0.0
        single_names = set(o_grp.loc[single_mask, "order_name"])

        top3        = _top3_products(p_grp, set(o_grp["order_name"]), total_units, short_names)
        single_top3 = _top3_products(p_grp, single_names, total_units, short_names)

        # Collagen order stats — orders containing at least one PAID Collagen line item (including bundle items)
        col_order_names = set(p_grp[(p_grp["product_group"] == "Collagen") & ((p_grp["net_sales"] != 0) | p_grp["is_bundle_item"])]["order_name"])
        col_orders      = o_grp[o_grp["order_name"].isin(col_order_names)]
        n_col           = col_orders["order_name"].nunique()
        col_single_pct  = (col_orders["items_in_order"] == 1).sum() / n_col * 100 if n_col else 0.0
        col_ipo         = col_orders["items_in_order"].sum() / n_col if n_col else 0.0

        rows.append({
            "month":                    str(month),
            "aov":                      round(aov, 1),
            "asp":                      round(asp, 1),
            "ipo":                      round(ipo, 2),
            "new_subscriptions":        int(n_orders),
            "pct_intro":               f"{pct_intro:.0f}%",
            "pct_bundle":              f"{pct_bundle:.0f}%",
            "pct_intro_under_20_aov":  f"{pct_intro_under_20:.0f}%",
            "pct_ivy_fiona":           f"{pct_ivy_fiona:.1f}%",
            "single_item_subs":         int(n_single),
            "pct_single_item":         f"{pct_single:.0f}%",
            "top3_products_1":          top3[0] if len(top3) > 0 else "",
            "top3_products_2":          top3[1] if len(top3) > 1 else "",
            "top3_products_3":          top3[2] if len(top3) > 2 else "",
            "single_item_top3_1":       single_top3[0] if len(single_top3) > 0 else "",
            "single_item_top3_2":       single_top3[1] if len(single_top3) > 1 else "",
            "single_item_top3_3":       single_top3[2] if len(single_top3) > 2 else "",
            "pct_quiz_uptake":         f"{pct_quiz:.1f}%",
            "pct_consult_uptake":      f"{pct_consult:.1f}%",
            "pct_combined_uptake":     f"{pct_combined_uptake:.1f}%",
            "collagen_single_item_pct": f"{col_single_pct:.0f}%",
            "collagen_ipo":             round(col_ipo, 2),
        })

    result = pd.DataFrame(rows).set_index("month")

    # MTD row = most recent month's data (current month to date)
    if not result.empty:
        latest_month  = orders["month"].max()
        mtd_orders    = orders[orders["month"] == latest_month]
        mtd_sub       = sub[sub["month"] == latest_month]
        n_o       = mtd_orders["order_name"].nunique()
        tot_rev   = mtd_orders["order_net_sales"].sum()
        mtd_paid  = mtd_sub[(mtd_sub["net_sales"] != 0) | mtd_sub["is_bundle_item"]]
        tot_u     = mtd_paid["units_sold"].sum()
        n_intr  = mtd_orders["intro_client"].sum()
        n_bun   = mtd_orders["has_bundle"].sum()
        n_i20   = mtd_orders[mtd_orders["intro_client"] & (mtd_orders["order_net_sales"] < 20)].shape[0]
        n_ivy     = mtd_orders["ivy_fiona_client"].sum() if "ivy_fiona_client" in mtd_orders.columns else 0
        n_quiz    = mtd_orders["quiz_client"].sum()      if "quiz_client"      in mtd_orders.columns else 0
        n_consult = mtd_orders["consult_client"].sum()   if "consult_client"   in mtd_orders.columns else 0
        n_sg    = (mtd_orders["items_in_order"] == 1).sum()
        sg_nms  = set(mtd_orders.loc[mtd_orders["items_in_order"] == 1, "order_name"])

        mtd_top3        = _top3_products(mtd_sub, set(mtd_orders["order_name"]), tot_u, short_names)
        mtd_single_top3 = _top3_products(mtd_sub, sg_nms, tot_u, short_names)

        mtd_col_names  = set(mtd_sub[(mtd_sub["product_group"] == "Collagen") & ((mtd_sub["net_sales"] != 0) | mtd_sub["is_bundle_item"])]["order_name"])
        mtd_col_orders = mtd_orders[mtd_orders["order_name"].isin(mtd_col_names)]
        n_mtd_col      = mtd_col_orders["order_name"].nunique()
        mtd_col_single = (mtd_col_orders["items_in_order"] == 1).sum() / n_mtd_col * 100 if n_mtd_col else 0.0
        mtd_col_ipo    = mtd_col_orders["items_in_order"].sum() / n_mtd_col if n_mtd_col else 0.0

        mtd_quiz_pct = n_quiz / n_o * 100 if n_o else 0.0
        mtd_consult_pct = n_consult / n_o * 100 if n_o else 0.0
        if "quiz_client" in mtd_orders.columns and "consult_client" in mtd_orders.columns:
            mtd_combined = (mtd_orders["quiz_client"] | mtd_orders["consult_client"]).sum()
        else:
            mtd_combined = 0
        mtd_combined_pct = mtd_combined / n_o * 100 if n_o else 0.0

        mtd_row = pd.DataFrame([{
            "month":                   "MTD",
            "aov":                     round(tot_rev / n_o if n_o else 0, 1),
            "asp":                     round(tot_rev / tot_u if tot_u else 0, 1),
            "ipo":                     round(tot_u / n_o if n_o else 0, 2),
            "new_subscriptions":       int(n_o),
            "pct_intro":              f"{n_intr / n_o * 100:.0f}%" if n_o else "0%",
            "pct_bundle":             f"{n_bun  / n_o * 100:.0f}%" if n_o else "0%",
            "pct_intro_under_20_aov": f"{n_i20  / n_intr * 100:.0f}%" if n_intr else "0%",
            "pct_ivy_fiona":          f"{n_ivy  / n_o * 100:.1f}%" if n_o else "0.0%",
            "single_item_subs":        int(n_sg),
            "pct_single_item":        f"{n_sg / n_o * 100:.0f}%" if n_o else "0%",
            "top3_products_1":         mtd_top3[0] if len(mtd_top3) > 0 else "",
            "top3_products_2":         mtd_top3[1] if len(mtd_top3) > 1 else "",
            "top3_products_3":         mtd_top3[2] if len(mtd_top3) > 2 else "",
            "single_item_top3_1":      mtd_single_top3[0] if len(mtd_single_top3) > 0 else "",
            "single_item_top3_2":      mtd_single_top3[1] if len(mtd_single_top3) > 1 else "",
            "single_item_top3_3":      mtd_single_top3[2] if len(mtd_single_top3) > 2 else "",
            "pct_quiz_uptake":        f"{mtd_quiz_pct:.1f}%" if n_o else "0.0%",
            "pct_consult_uptake":     f"{mtd_consult_pct:.1f}%" if n_o else "0.0%",
            "pct_combined_uptake":    f"{mtd_combined_pct:.1f}%" if n_o else "0.0%",
            "collagen_single_item_pct": f"{mtd_col_single:.0f}%",
            "collagen_ipo":             round(mtd_col_ipo, 2),
        }]).set_index("month")
        result = pd.concat([result, mtd_row])

    return result


# ── Output 2: Period Summary by Banding ───────────────────────────────────────

def output2(start_date: str, end_date: str, df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Subscription summary for a given period, segmented by customer banding.

    Mirrors OUTPUT_2.png:
      Rows: Core #1, Core #2+, CORE TOTAL,
            Intro #1, Intro #2-3, [Intro new subtotal], Intro #4+, INTRO TOTAL,
            TOTAL
      Cols: Customers, Orders, Revenue £, AOV £, IPO, ASP £
    """
    if df is None:
        df = _load()

    start = pd.Timestamp(start_date)
    end   = pd.Timestamp(end_date)

    period = df[_order_is_subscription(df) & df["day"].between(start, end) & (df["order_net_sales"] > 0)].copy()
    orders = _order_level(period)

    def _stats(banding_vals: list[str]) -> dict:
        o = orders[orders["banding"].isin(banding_vals)]
        p = period[period["banding"].isin(banding_vals)]
        n_cust   = o["customer_id"].nunique()
        n_ord    = o["order_name"].nunique()
        revenue  = o["order_net_sales"].sum()
        paid_rows = p[(p["net_sales"] != 0) | p["is_bundle_item"]]
        tot_u    = paid_rows["units_sold"].sum()
        aov = revenue / n_ord  if n_ord  else 0.0
        ipo = tot_u   / n_ord  if n_ord  else 0.0
        asp = revenue / tot_u  if tot_u  else 0.0
        return dict(customers=n_cust, orders=n_ord, revenue=revenue,
                    aov=aov, ipo=ipo, asp=asp)

    # Banding groups → display rows
    layout = [
        ("Core",  "#1",          ["Core 1"],                              False),
        ("Core",  "#2+",         ["Core 2"],                              False),
        ("Core",  "CORE TOTAL",  ["Core 1", "Core 2"],                    True),
        ("Intro", "#1",          ["Intro 1"],                             False),
        ("Intro", "#2-3",        ["Intro 2-3"],                           False),
        ("Intro", "Intro new",   ["Intro 1", "Intro 2-3"],               True),   # subtotal
        ("Intro", "#4+",         ["Intro 4"],                             False),
        ("Intro", "INTRO TOTAL", ["Intro 1", "Intro 2-3", "Intro 4"],    True),
        ("",      "TOTAL",       ["Core 1", "Core 2", "Intro 1", "Intro 2-3", "Intro 4"], True),
    ]

    rows = []
    for segment, tier, bandings, is_total in layout:
        s = _stats(bandings)
        rows.append({
            "segment":   segment,
            "tier":      tier,
            "customers": s["customers"],
            "orders":    s["orders"],
            "revenue":   round(s["revenue"]),
            "aov":       round(s["aov"], 1),
            "ipo":       round(s["ipo"], 2),
            "asp":       round(s["asp"], 1),
            "_is_total": is_total,
        })

    result = pd.DataFrame(rows).drop(columns=["_is_total"])
    return result


# ── Output 3: Month-on-Month IPO / ASP / AOV by Category ─────────────────────

_BANDING_TO_CATEGORY: dict[str, str] = {
    "Core 2":    "Subscription - core",
    "Intro 2-3": "Subscription - 50% (2+3)",
    "Intro 4":   "Subscription - 50% 4+",
    "Core 1":    "New Customers Subscription - core",
    "Intro 1":   "New Customers Subscription - 50%",
}

_CATEGORY_ORDER = [
    "Subscription - core",
    "Subscription - 50% (2+3)",
    "Subscription - 50% 4+",
    "New Customers Subscription - core",
    "New Customers Subscription - 50%",
    "Returning",
    "New Customers",
]


def output3(df: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Month-on-month IPO, ASP, and AOV pivoted by order category.

    Order classification is done at the ORDER level:
      - If any row in an order is a subscription, the whole order is subscription.
      - Only orders with zero subscription rows are 'Returning' / 'New Customers'.

    Revenue methodology: each order contributes to EVERY month it has rows in.
      - Positive contributions (purchases) appear in the placement month.
      - Negative contributions (refunds) appear in the refund month.
    This matches Shopify's monthly Net Sales figure (revenue minus refunds per month).

    IPO  = items_in_order (pre-computed in parquet: paid units per order) / orders
    AOV  = net revenue (positive orders + refund adjustments) / order count
    ASP  = AOV / IPO

    Categories:
      Subscription - core               → Core 2 banding (returning sub, not intro)
      Subscription - 50% (2+3)          → Intro 2-3 banding
      Subscription - 50% 4+             → Intro 4 banding
      New Customers Subscription - core → Core 1 banding (first sub, not intro)
      New Customers Subscription - 50%  → Intro 1 banding (first sub, intro)
      Returning                         → one-time order, returning customer
      New Customers                     → one-time order, new customer

    Returns a dict with keys 'orders', 'revenue', 'ipo', 'aov', 'asp'.
    """
    if df is None:
        df = _load()

    df = df.copy()
    df["month"] = df["day"].dt.to_period("M")

    # Classify at ORDER level: any subscription row in an order → whole order is subscription
    df["order_is_sub"] = _order_is_subscription(df)

    # Assign category to ALL rows (positive orders AND refund rows)
    sub_mask = df["order_is_sub"]
    df["category"] = df["banding"].map(_BANDING_TO_CATEGORY).where(sub_mask)
    df.loc[~sub_mask, "category"] = df.loc[~sub_mask, "new_or_returning"].map(
        {"Returning": "Returning", "New": "New Customers"}
    )
    df = df[df["category"].notna()].copy()

    # One row per (order, month): order_net_sales is order-level and the same on
    # every row for a given (order, month), so any row is representative.
    order_month_cols = ["order_name", "month", "category", "order_net_sales", "items_in_order"]
    om = df[order_month_cols].drop_duplicates(subset=["order_name", "month"])

    # Revenue: ALL (order, month) contributions including negative (cross-period refunds).
    rev_stats = om.groupby(["month", "category"]).agg(
        total_rev=("order_net_sales", "sum")
    ).reset_index()

    # Orders and items: positive FIRST OCCURRENCE only (each order counted once in
    # its placement month; refund rows in later months do not inflate order counts).
    pos_first = om[om["order_net_sales"] > 0].drop_duplicates(subset=["order_name"])
    order_stats = pos_first.groupby(["month", "category"]).agg(
        n_orders   =("order_name",     "count"),
        total_items=("items_in_order", "sum"),
    ).reset_index()

    stats = rev_stats.merge(order_stats, on=["month", "category"], how="outer")
    stats["n_orders"]    = stats["n_orders"].fillna(0).astype(int)
    stats["total_items"] = stats["total_items"].fillna(0)
    stats["total_rev"]   = stats["total_rev"].fillna(0)

    _n = stats["n_orders"].replace(0, float("nan"))
    _ipo_raw = stats["total_items"] / _n
    stats["aov"] = (stats["total_rev"] / _n).round(2)
    stats["ipo"] = _ipo_raw.round(2)
    stats["asp"] = (stats["aov"] / _ipo_raw.replace(0, float("nan"))).round(2)

    def _pivot(metric: str) -> pd.DataFrame:
        pv = stats.pivot(index="category", columns="month", values=metric)
        pv.columns = [str(c) for c in pv.columns]
        present = [c for c in _CATEGORY_ORDER if c in pv.index]
        return pv.reindex(present)

    return {
        "orders":  _pivot("n_orders"),
        "revenue": _pivot("total_rev"),
        "ipo":     _pivot("ipo"),
        "aov":     _pivot("aov"),
        "asp":     _pivot("asp"),
    }


# ── Console display helpers ────────────────────────────────────────────────────

def print_output1(df: pd.DataFrame | None = None) -> None:
    result = output1(df)
    print("\n=== OUTPUT 1: New Subscription Tracker ===\n")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    print(result.T.to_string())


def print_output2(start_date: str, end_date: str, df: pd.DataFrame | None = None) -> None:
    result = output2(start_date, end_date, df)
    print(f"\n=== OUTPUT 2: Period Summary  {start_date} → {end_date} ===\n")
    print(result.to_string(index=False))
