# Subscription Tracker — Project Guide

## What this project does

Ingests Shopify subscription CSV exports into a central parquet file, enriches them with Google Sheets lookups, and generates three reports:

- **Output 1** — month-by-month new subscription tracker
- **Output 2** — period summary segmented by order banding
- **Output 3** — month-on-month IPO / AOV / ASP by order category

## Running the reports

```bash
python report.py --out 1
python report.py --out 2 --start 2025-05-01 --end 2025-05-31
python report.py --out 3
python report.py --out 3 --save reports/output3.xlsx   # Excel, one sheet per metric
```

## Ingesting new data

```bash
python ingest.py                          # processes all CSVs in file inputs/
python ingest.py file\ inputs/my.csv      # single file
python ingest.py --backfill-flags         # re-fetch Google Sheets and recompute flags on full history
```

---

## Critical quirks

### 1. Order-level subscription classification (most important)

**All three reports** classify orders as subscription/one-time at the **order level**, not the row level. If ANY product row in an order is a subscription, the entire order — including any one-time rows within it — is treated as a subscription order.

This is enforced via `_order_is_subscription()` in `pipeline/reports.py`, which propagates the subscription flag across all rows of the same order using a vectorised `groupby.transform("max")`.

**Why this matters:** In raw Shopify exports, bundle child rows are labelled `one_time` even when the parent order is a subscription. Without order-level classification these children leak into the Returning/New Customers categories, inflating their IPO by a factor of ~1.6×. The ingest pipeline (`transform.py`) corrects the label at ingest time, but the order-level check in reports is a second line of defence and is the canonical rule.

### 2. Bundle handling

Bundle orders have two types of rows in the Shopify CSV:

- **Purchase parent row** — SKU starts with `700`, `net_sales > 0`. Carries the bundle price, zero item detail. **Dropped at ingest** — its revenue is captured in `order_net_sales` before the row is removed.
- **Refund parent row** — SKU starts with `700`, `net_sales < 0`. **Retained at ingest** since dropping it would silently lose bundle refund data and cause revenue over-counts vs Shopify.
- **Child rows** — individual product SKUs. Have `net_sales = 0` in the CSV (price is on the parent). **Retained.** `is_bundle_item = True` on these rows.

Revenue for bundle orders is captured from the parent before it is dropped, stored as `order_net_sales` on every child row.

Child rows from subscription bundles are often labelled `subscription_or_one_time = "one_time"` in the raw Shopify CSV. `transform.py` corrects these to `"subscription"` if the parent row was `"subscription"`. External spreadsheets that read the raw export without this correction will miscategorise those rows.

### 3. IPO definition

**Items per order = `items_in_order` / order count**, where `items_in_order` is pre-computed in the parquet using different logic for bundle vs non-bundle orders:

- **Non-bundle orders:** `sum(units_sold)` for rows where `net_sales != 0`. Zero-price rows (e.g. free samples) are excluded.
- **Bundle orders:** `sum(units_sold)` for rows where `is_bundle_item = True` (child rows only). This correctly excludes both the dropped purchase parent and any retained refund parent rows.

`units_sold = net_items_sold × units_per_bundle`. The `units_per_bundle` multiplier comes from the product master sheet (column I). For most products it is 1.

Do **not** recompute IPO by summing `units_sold` directly from the filtered product-level rows — for bundle orders this works, but for non-bundle orders it includes zero-price rows. Use `items_in_order` from the order-level deduplicated frame.

### 4. AOV and ASP definitions

- **AOV** = net revenue / number of orders. Net revenue includes cross-period refund adjustments (see §9).
- **ASP** = AOV / IPO (not a direct average price per unit)

Reports use `order_net_sales`. `order_gross_sales` also exists in the parquet (see §8 below) but is not used in current reports.

### 5. Order banding (subscription orders only)

Banding is assigned per **order**, not per customer. A customer can — and regularly does — have orders in more than one banding category within the same reporting period (27,000+ customer-months affected across the full history). The most common transitions are Core 1 → Core 2 (first renewal) and Intro 2-3 → Intro 4 (fourth subscription order).

| Banding | Condition |
|---|---|
| Core 1 | NOT intro_client, `new_or_returning == "New"` |
| Core 2 | NOT intro_client, `new_or_returning == "Returning"` |
| Intro 1 | intro_client, `new_or_returning == "New"` |
| Intro 2-3 | intro_client, `new_or_returning == "Returning"`, `subscription_order_num < 4` |
| Intro 4 | intro_client, `new_or_returning == "Returning"`, `subscription_order_num ≥ 4` |

`subscription_order_num` counts **only subscription orders** per customer — one-time purchases do not increment it.

`intro_client` is a boolean flag set at ingest by matching `customer_email` against the Intros master Google Sheet. It is backfilled across full history when `--backfill-flags` is used.

### 6. Order category mapping (Outputs 2 and 3)

Both Output 2 and Output 3 segment by order category. Each order is classified independently — a customer with two orders in the same period may contribute to two different categories.

| Display label (Output 3) | Output 2 tier | Banding / rule |
|---|---|---|
| Subscription - core | Core #2+ | Core 2 |
| Subscription - 50% (2+3) | Intro #2-3 | Intro 2-3 |
| Subscription - 50% 4+ | Intro #4+ | Intro 4 |
| New Customers Subscription - core | Core #1 | Core 1 |
| New Customers Subscription - 50% | Intro #1 | Intro 1 |
| Returning | *(not in Output 2)* | One-time order, `new_or_returning == "Returning"` |
| New Customers | *(not in Output 2)* | One-time order, `new_or_returning == "New"` |

Output 2 includes subtotal and total rows (Core Total, Intro new subtotal, Intro Total, Grand Total) that are not in Output 3.

### 7. `new_or_returning` field

Populated from Shopify's "New or returning customer" column. Null values are filled with `"Returning"` at ingest. This field is **not** recalculated from order history — it is whatever Shopify reports.

### 8. `order_gross_sales` vs `order_net_sales`

Both are stored in the parquet.

**`order_net_sales`** is recomputed on every ingest via `assign_derived_fields` as the sum of `net_sales` for a given order **within the same calendar month**. This means:
- Same-month purchase + refund pairs net correctly (e.g. refund CSV for the same month reduces the order's revenue).
- Cross-period refunds (refund arrives in a later month) leave the placement month's `order_net_sales` unchanged and appear as a separate negative `order_net_sales` row in the refund month.

**`order_gross_sales`** = `max(order_net_sales, sum_of_positive_net_sales_rows_in_month)`, clipped to ≥ 0. This recovers the gross value for purchase+refund same-month pairs where the net rounds to 0. Not currently used in reports.

### 9. Output 3 revenue methodology (Shopify-matching)

Output 3 revenue is designed to match Shopify's monthly Net Sales figure exactly. The key design decision is **per-(order, month) aggregation** rather than a single per-order figure:

- Each order can contribute to **multiple months**: a positive amount in its placement month and a negative amount (refund) in the month the refund was processed.
- **Revenue** is the sum of all `order_net_sales` contributions for that `(category, month)` — both positive and negative.
- **Order count and IPO** are based only on the **positive first-occurrence** of each order (its placement month). Refund rows in later months do not inflate order counts or distort IPO.
- **AOV = net revenue / order count**. In months with heavy refunds, AOV will be lower than the list price AOV because revenue is net.

This matches Shopify's dashboard: purchases appear in their placement month, refunds reduce the month they are processed.

**Known limitation — invisible historical bundle refunds:** Bundle refund rows (700\* SKU, negative `net_sales`) were silently dropped during historical ingestions before the fix was applied. Without the original CSVs those rows cannot be recovered, so historical months may be slightly over-stated vs Shopify by the amount of bundle refunds processed in those months. Typically this is ~£3–5k/month. New ingestions from the fix date onwards correctly capture bundle refund rows.

### 10. Deduplication

Rows are deduplicated on `(day, order_name, product_variant_sku, product_title)` — both SKU and title are included so rows with a null SKU but different product titles are not collapsed. Re-ingesting the same CSV is safe.

Derived fields (`subscription_order_num`, `banding`, `items_in_order`, `order_gross_sales`) are dropped before dedup and recomputed from scratch across the full history on every ingest.

### 11. Google Sheets live lookups at ingest

Four sheets are fetched on every `ingest.py` run:

| Flag | Sheet | Notes |
|---|---|---|
| `intro_client` | Intros master table | Column A, emails |
| `ivy_fiona_client` | Ivy/Fiona uptake | Column B, emails |
| `quiz_client` | Quiz uptake | Column A, emails |
| `consult_client` | Consult uptake | Column A, emails |

Plus the **product master** which maps SKU → `product_group` and `units_per_bundle`.

All email matching is case-insensitive. Flags are boolean columns in the parquet. Use `--backfill-flags` to re-apply updated sheets to historical data without re-ingesting CSVs.

---

## Parquet schema

```
day, customer_cohort_month, order_name, customer_id, customer_email,
new_or_returning, subscription_or_one_time, sales_channel,
order_net_sales, net_sales,
product_title, product_variant_sku, product_group,
net_items_sold, units_per_bundle, units_sold,
is_bundle_item, has_bundle,
intro_client, ivy_fiona_client, quiz_client, consult_client,
subscription_order_num, banding, items_in_order, order_gross_sales
```

One row per (order × product line × day). Multiple rows share the same `order_name`; order-level fields (`order_net_sales`, `items_in_order`, `new_or_returning`, `banding`, etc.) are identical across all rows of the same `(order, day)`.

**Note on bundle refund rows:** From the ingest fix date onwards, 700\* rows with negative `net_sales` are retained as refund markers. These rows have `has_bundle = True`, `is_bundle_item = False`, `net_sales < 0`, and `order_net_sales < 0`. They contribute negative revenue to their month in Output 3 but are excluded from order counts and IPO calculations.
