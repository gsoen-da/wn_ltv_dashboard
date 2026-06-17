import pandas as pd
import numpy as np
from pipeline.config import PARQUET_PATH
from itertools import product as iterproduct

print("Loading data...")
df = pd.read_parquet(PARQUET_PATH)

# Load COGS - clean column names (from working script)
cogs_df = pd.read_excel("data/COGS FY22_27.xlsx")
cogs_cols = list(cogs_df.columns)
cogs_df.rename(columns={cogs_cols[0]: "SKU"}, inplace=True)
cogs_df["SKU"] = cogs_df["SKU"].astype(str).str.strip()

# Load fulfillment costs (from working script)
print("Loading fulfillment costs...")
fc_df = pd.read_csv("data/fulfilment costs.csv", encoding="latin-1")
fc_df["month"] = pd.to_datetime(fc_df["month"], format="%d/%m/%Y")
fc_df["month_key"] = fc_df["month"].dt.strftime("%Y-%m")
fc_df["fulfilment_cost"] = fc_df["fulfilment_cost"].astype(str).str.replace("£", "").str.replace(",", "").str.strip().astype(float)

print("Melting COGS data for merge...")

# Add FY code column (vectorized from working script)
def get_fy_code_vec(date_series):
    month = date_series.dt.month
    year = date_series.dt.year
    fy = year.where(month < 5, year + 1) - 2000
    return fy.astype(str).str.zfill(2)

df["fy_code"] = get_fy_code_vec(df["day"])
df["product_variant_sku"] = df["product_variant_sku"].astype(str).str.strip()

# Unpivot COGS to (SKU, FY_code, cost) format (from working script)
cogs_cols_list = [c for c in cogs_df.columns if "cogs" in c.lower()]
cogs_long = []

for sku_idx, sku_row in cogs_df.iterrows():
    sku = sku_row["SKU"]
    for cogs_col in cogs_cols_list:
        fy_code = cogs_col.split()[0].zfill(2)  # e.g., "22 cogs" -> "22"
        cost = sku_row[cogs_col]
        if pd.notna(cost) and str(cost).lower() not in ['unknown', 'na', 'nan', '']:
            try:
                cost_float = float(cost)
                cogs_long.append({"SKU": sku, "fy_code": fy_code, "row_cogs": cost_float})
            except:
                pass

cogs_lookup = pd.DataFrame(cogs_long)
print(f"COGS lookup table: {len(cogs_lookup)} entries")

# Merge COGS into main df (from working script)
print("Merging COGS...")
df = df.merge(
    cogs_lookup,
    left_on=["product_variant_sku", "fy_code"],
    right_on=["SKU", "fy_code"],
    how="left"
)
df["row_cogs"] = df["row_cogs"].fillna(0.0)

# Calculate order-level COGS (from working script)
print("Aggregating COGS by order...")

# Filter to rows relevant for COGS
cogs_rows = df[df["net_sales"] != 0].copy()

# For bundles, only use is_bundle_item = True
if "has_bundle" in cogs_rows.columns and "is_bundle_item" in cogs_rows.columns:
    is_bundle = cogs_rows["has_bundle"] == True
    cogs_rows.loc[is_bundle & (cogs_rows["is_bundle_item"] == False), "row_cogs"] = 0

order_cogs = cogs_rows.groupby("order_name")["row_cogs"].sum().reset_index()
order_cogs.columns = ["order_name", "order_cogs"]

df = df.merge(order_cogs, on="order_name", how="left")
df["order_cogs"] = df["order_cogs"].fillna(0.0)

print(f"COGS calculated for {len(order_cogs)} orders")

# Add month and allocate fulfillment costs (from working script)
print("Allocating fulfillment costs...")

df["order_month"] = df["day"].dt.strftime("%Y-%m")

# Get unique order-month-newreturning combinations
order_month_status = df[["order_name", "order_month", "new_or_returning"]].drop_duplicates()

# Merge with fulfillment costs
order_month_status = order_month_status.merge(fc_df[["month_key", "fulfilment_cost"]], left_on="order_month", right_on="month_key", how="left")
order_month_status["fulfilment_cost"] = order_month_status["fulfilment_cost"].fillna(0.0)

# For missing months, calculate 10.5% of monthly revenue
missing_months = order_month_status[order_month_status["fulfilment_cost"] == 0.0]["order_month"].unique()
for month in missing_months:
    month_revenue = df[df["order_month"] == month]["order_net_sales"].sum()
    order_month_status.loc[order_month_status["order_month"] == month, "fulfilment_cost"] = month_revenue * 0.105

# Calculate weighted allocation per month (from working script)
order_fc_dict = {}

for month in order_month_status["order_month"].unique():
    month_data = order_month_status[order_month_status["order_month"] == month]
    monthly_fc = month_data["fulfilment_cost"].iloc[0]

    first_orders = month_data[month_data["new_or_returning"] == "New"]["order_name"].tolist()
    repeat_orders = month_data[month_data["new_or_returning"] != "New"]["order_name"].tolist()

    total_weight = len(repeat_orders) + len(first_orders) * 1.32

    if total_weight > 0:
        cost_per_repeat = monthly_fc / total_weight
        cost_per_first = cost_per_repeat * 1.32

        for order in repeat_orders:
            order_fc_dict[order] = cost_per_repeat
        for order in first_orders:
            order_fc_dict[order] = cost_per_first

order_fc_df = pd.DataFrame(list(order_fc_dict.items()), columns=["order_name", "order_fc"])
df = df.merge(order_fc_df, on="order_name", how="left")
df["order_fc"] = df["order_fc"].fillna(0.0)

# Calculate LTV (from working script)
df["ltr"] = df["order_net_sales"]
df["ltv"] = df["ltr"] - df["order_cogs"] - df["order_fc"]

print(f"Fulfillment costs allocated to {len(order_fc_dict)} orders")

# Define the 11 product groups we care about
TARGET_PRODUCTS = {
    "Collagen",
    "Magnesium",
    "Ashwagandha",
    "Energy Support",
    "Daily Multi Nutrient for Women",
    "Omega 3",
    "Vitamin D",
    "Pregnancy + New Mother Multi",
    "Fertility Support for Men",
    "Pregnancy + New Mother Omega 3",
    "Iron"
}

# Filter to customers with 12+ months of data
print("Filtering to customers with 12+ months of data...")
max_date = df["day"].max()
cutoff_date = max_date - pd.DateOffset(months=12)

first_order = df.groupby("customer_id").agg({"day": "min", "new_or_returning": "first"}).reset_index()
first_order.columns = ["customer_id", "first_order_date", "first_new_returning"]
first_order = first_order[(first_order["first_new_returning"] == "New") & (first_order["first_order_date"] <= cutoff_date)]
valid_customers = set(first_order["customer_id"].unique())

print(f"  Valid customers: {len(valid_customers):,}")

# Build customer attributes
print("Building customer attributes...")
df_valid = df[df["customer_id"].isin(valid_customers)].copy()

# Get first order date and add cohort month
customer_first_order = first_order[["customer_id", "first_order_date"]].copy()
customer_first_order["cohort_month"] = customer_first_order["first_order_date"].dt.to_period("M")
df_valid = df_valid.merge(customer_first_order, on="customer_id")

# Filter to 12-month window
df_valid["days_since_first"] = (df_valid["day"] - df_valid["first_order_date"]).dt.days
df_12m = df_valid[df_valid["days_since_first"] <= 365].copy()

print(f"  Orders in 12m window: {df_12m['order_name'].nunique():,}")

print("Classifying customers...")
customer_attrs = pd.DataFrame({"customer_id": list(valid_customers)})

# Identify first subscription order for each customer
subscription_orders = df_12m[df_12m["subscription_or_one_time"] == "subscription"].copy()
first_sub_order = subscription_orders.groupby("customer_id").agg({"day": "min", "order_name": "first"}).reset_index()
first_sub_order.columns = ["customer_id", "first_sub_date", "first_sub_order_name"]

# Get items_in_order for first subscription order
first_sub_items = subscription_orders[subscription_orders.groupby("customer_id")["day"].transform("min") == subscription_orders["day"]].copy()
first_sub_items = first_sub_items.drop_duplicates(subset=["customer_id"], keep="first")[["customer_id", "items_in_order"]]
first_sub_items.columns = ["customer_id", "first_sub_items"]

# Add subscription classification
customer_attrs = customer_attrs.merge(first_sub_order[["customer_id", "first_sub_date"]], on="customer_id", how="left")
customer_attrs = customer_attrs.merge(first_sub_items, on="customer_id", how="left")

def classify_subscriber(row):
    if pd.isna(row["first_sub_date"]):
        return "OTP"
    elif row["first_sub_items"] == 1:
        return "Single Item Subscriber"
    else:
        return "Multi Item Subscriber"

customer_attrs["subscriber_type"] = customer_attrs.apply(classify_subscriber, axis=1)

# Get quiz and consult flags
print("Extracting quiz and consult flags...")
quiz_consult = df_12m[["customer_id", "quiz_client", "consult_client"]].drop_duplicates()
customer_attrs = customer_attrs.merge(quiz_consult, on="customer_id", how="left")
customer_attrs["quiz_client"] = customer_attrs["quiz_client"].fillna(False).astype(bool)
customer_attrs["consult_client"] = customer_attrs["consult_client"].fillna(False).astype(bool)

# Get products for each customer
print("Extracting product information...")

# First order products (df_12m already has first_order_date from merge)
first_order_details = df_12m[df_12m["day"] == df_12m["first_order_date"]].copy()
first_order_products = first_order_details.groupby("customer_id")["product_group"].apply(
    lambda x: set([p for p in x.dropna() if p in TARGET_PRODUCTS])
).reset_index()
first_order_products.columns = ["customer_id", "first_products"]

# All products
all_products = df_12m.groupby("customer_id")["product_group"].apply(
    lambda x: set([p for p in x.dropna() if p in TARGET_PRODUCTS])
).reset_index()
all_products.columns = ["customer_id", "all_products"]

# Merge product data
customer_attrs = customer_attrs.merge(first_order_products, on="customer_id", how="left")
customer_attrs = customer_attrs.merge(all_products, on="customer_id", how="left")

# Fill NaN with empty sets
customer_attrs["first_products"] = customer_attrs["first_products"].fillna(
    customer_attrs["first_products"].apply(lambda x: set() if pd.isna(x) else x)
)
customer_attrs["all_products"] = customer_attrs["all_products"].fillna(
    customer_attrs["all_products"].apply(lambda x: set() if pd.isna(x) else x)
)

print(f"  Customers with target products in first order: {(customer_attrs['first_products'].str.len() > 0).sum():,}")
print(f"  Customers with any target products: {(customer_attrs['all_products'].str.len() > 0).sum():,}")

# Build aggregated output
print("Building aggregated output...")

# Prepare data for aggregation (use ltr and ltv which are now calculated)
df_agg = df_12m[[
    "customer_id", "day", "order_name", "ltr", "ltv",
    "items_in_order", "cohort_month"
]].drop_duplicates(subset=["order_name"]).copy()

df_agg["month"] = df_agg["day"].dt.to_period("M")

# Add fiscal year
def get_fiscal_year(cohort_month_str):
    parts = str(cohort_month_str).split("-")
    year = int(parts[0])
    month = int(parts[1])
    if month >= 5:
        return f"FY{year + 1 - 2000}"
    else:
        return f"FY{year - 2000}"

# Add customer attributes to order data
df_agg = df_agg.merge(customer_attrs[["customer_id", "subscriber_type", "first_products", "all_products", "quiz_client", "consult_client"]],
                       on="customer_id", how="left")
df_agg["fy"] = df_agg["cohort_month"].apply(get_fiscal_year)

# Create expanded rows for each product combination
result_rows = []

for _, row in df_agg.iterrows():
    customer_id = row["customer_id"]
    month = row["month"]
    fy = row["fy"]
    subscriber_type = row["subscriber_type"]
    ltr_value = row["ltr"] if pd.notna(row["ltr"]) else 0
    ltv_value = row["ltv"] if pd.notna(row["ltv"]) else 0
    items = row["items_in_order"]
    quiz_client = row["quiz_client"] if pd.notna(row["quiz_client"]) else False
    consult_client = row["consult_client"] if pd.notna(row["consult_client"]) else False

    first_prods = list(row["first_products"]) + ["All"]
    all_prods = list(row["all_products"]) + ["All"]

    for first_prod, all_prod in iterproduct(first_prods, all_prods):
        result_rows.append({
            "cohort_month": str(row["cohort_month"]),
            "fy": fy,
            "subscriber_type": subscriber_type,
            "first_product": first_prod,
            "all_products": all_prod,
            "quiz_client": quiz_client,
            "consult_client": consult_client,
            "customer_id": customer_id,
            "ltr": ltr_value,
            "ltv": ltv_value,
            "items": items
        })

result_df = pd.DataFrame(result_rows)

# Aggregate by dimensions
print("Aggregating metrics...")
agg_df = result_df.groupby(["cohort_month", "fy", "subscriber_type", "first_product", "all_products", "quiz_client", "consult_client"]).agg({
    "customer_id": "nunique",
    "ltr": "sum",
    "ltv": "sum",
    "items": "sum"
}).reset_index()

agg_df.columns = ["cohort_month", "fy", "subscriber_type", "first_product", "all_products", "quiz_client", "consult_client", "count", "ltr_total", "ltv_total", "items_total"]

# Calculate per-customer metrics
agg_df["ltr"] = round(agg_df["ltr_total"] / agg_df["count"], 2)
agg_df["ltv"] = round(agg_df["ltv_total"] / agg_df["count"], 2)

print(f"DEBUG: agg_df columns after calculation: {agg_df.columns.tolist()}")
print(f"DEBUG: ltv in agg_df: {'ltv' in agg_df.columns}")

# Get order counts per customer
order_counts = result_df.groupby(["cohort_month", "fy", "subscriber_type", "first_product", "all_products", "quiz_client", "consult_client", "customer_id"]).agg({
    "ltr": "count"
}).reset_index()
order_counts.columns = ["cohort_month", "fy", "subscriber_type", "first_product", "all_products", "quiz_client", "consult_client", "customer_id", "orders"]

order_counts = order_counts.groupby(["cohort_month", "fy", "subscriber_type", "first_product", "all_products", "quiz_client", "consult_client"]).agg({
    "orders": "sum"
}).reset_index()
order_counts.columns = ["cohort_month", "fy", "subscriber_type", "first_product", "all_products", "quiz_client", "consult_client", "orders_total"]

agg_df = agg_df.merge(order_counts, on=["cohort_month", "fy", "subscriber_type", "first_product", "all_products", "quiz_client", "consult_client"], how="left")
agg_df["aov"] = round(agg_df["ltr_total"] / agg_df["orders_total"], 2)
agg_df["ipo"] = round(agg_df["items_total"] / agg_df["orders_total"], 2)
agg_df["orders"] = round(agg_df["orders_total"] / agg_df["count"], 2)

# Ensure LTV column exists
if "ltv" not in agg_df.columns:
    print("WARNING: ltv column missing from agg_df, checking ltv_total...")
    if "ltv_total" in agg_df.columns:
        agg_df["ltv"] = round(agg_df["ltv_total"] / agg_df["count"], 2)
    else:
        print("ERROR: ltv_total also missing!")

# Final output - use cohort_month (not order month) and include both LTR and LTV
cols_to_export = ["cohort_month", "fy", "subscriber_type", "first_product", "all_products", "quiz_client", "consult_client", "count", "ltr", "aov", "ipo", "orders"]
if "ltv" in agg_df.columns:
    cols_to_export.insert(9, "ltv")

final_df = agg_df[cols_to_export].copy()

# Sort
final_df["sort_month"] = pd.to_datetime(final_df["cohort_month"])
final_df = final_df.sort_values(["sort_month", "subscriber_type", "first_product", "all_products"])
final_df = final_df.drop(columns=["sort_month"])

# Export to Excel
print("Exporting to Excel...")
excel_path = "reports/customer_segmentation.xlsx"
with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
    final_df.to_excel(writer, sheet_name="Data", index=False)

print(f"\nSaved to {excel_path}")
print(f"\nShape: {final_df.shape[0]:,} rows")
print(f"\nSample data:")
print(final_df.head(20))

# Summary stats
print(f"\n=== SUMMARY STATS ===")
print(f"Cohort months: {final_df['cohort_month'].nunique()}")
print(f"Subscriber types: {final_df['subscriber_type'].unique().tolist()}")
print(f"First products: {final_df['first_product'].unique().tolist()}")
print(f"All products: {final_df['all_products'].unique().tolist()}")
