import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Customer Segmentation Dashboard", layout="wide")

st.title("LTV Dashboard")

# ---------------------------------------------------------------------------
# Data: ROW-LEVEL grain — one row per customer per window (6M / 12M).
# Product membership is expressed as boolean flags:
#   first_<Product>  = product was in the customer's first order
#   bought_<Product> = product was bought anywhere in the window
# Because each row is one customer, count = number of rows (always distinct).
# ---------------------------------------------------------------------------
@st.cache_data
def load_data():
    return pd.read_parquet("customer_segmentation.parquet")

df = load_data()

# Derive the product list from the flag columns.
PRODUCTS = sorted(c[len("first_"):] for c in df.columns if c.startswith("first_"))

# CM3 = contribution margin after CAC (LTV already nets COGS + fulfilment, so
# CM3 = LTV − CAC). Blank where CAC is unknown.
df["cm3"] = df["ltv"] - df["cac"]

# Convert cohort_month to datetime for proper sorting
df["cohort_dt"] = pd.to_datetime(df["cohort_month"])
df = df.sort_values("cohort_dt")

st.sidebar.header("Filters")

# 1) Horizon — pick exactly one (default 12M). Each row belongs to one window,
#    so this guarantees every count below is a distinct-customer count.
horizon = st.sidebar.radio("LTV Horizon", ["12 Months", "6 Months"], index=0)
horizon_col = "12M" if horizon == "12 Months" else "6M"
df = df[df[horizon_col]].copy()

# 2) Fiscal Year — default to the three most recent (e.g. FY24, FY25, FY26)
fys = sorted(df["fy"].unique())
selected_fy = st.sidebar.multiselect("Fiscal Year", fys, default=fys[-3:])

# 3) Cohort Month (cascades from FY) — every month of the selected FY(s) is
#    auto-selected. Keying the widget on the FY selection forces it to
#    re-initialise (re-select all months) whenever you add/remove a fiscal year.
available_months = sorted(df[df["fy"].isin(selected_fy)]["cohort_month"].unique())
selected_months = st.sidebar.multiselect(
    "Cohort Month",
    available_months,
    default=available_months,
    key=f"months_{'_'.join(sorted(selected_fy))}",
)

# 4) Subscriber type
subscriber_types = sorted(df["subscriber_type"].unique())
selected_subscriber = st.sidebar.multiselect(
    "Subscriber Type", subscriber_types, default=subscriber_types
)

# 5) Product filters — flag based, so no double counting.
#    Empty selection = no filter (all customers). Multiple picks = "any of"
#    (OR within a dimension). The two dimensions combine with AND, which lets
#    you ask e.g. "started with Vitamin D AND later bought Iron".
st.sidebar.subheader("Products")
selected_first_products = st.sidebar.multiselect(
    "First Order Includes", PRODUCTS, default=[],
    help="Customers whose FIRST order included any of these. Empty = all customers.",
)
selected_bought_products = st.sidebar.multiselect(
    "Bought In Window", PRODUCTS, default=[],
    help="Customers who bought any of these within the window. Empty = all customers.",
)

# 6) Quiz / Consult
st.sidebar.subheader("Program Status")
selected_quiz = st.sidebar.multiselect(
    "Quiz Client", [True, False], default=[True, False],
    format_func=lambda x: "Yes" if x else "No",
)
selected_consult = st.sidebar.multiselect(
    "Consult Client", [True, False], default=[True, False],
    format_func=lambda x: "Yes" if x else "No",
)

# Apply filters
mask = (
    df["cohort_month"].isin(selected_months)
    & df["fy"].isin(selected_fy)
    & df["subscriber_type"].isin(selected_subscriber)
    & df["quiz_client"].isin(selected_quiz)
    & df["consult_client"].isin(selected_consult)
)
if selected_first_products:
    mask &= df[[f"first_{p}" for p in selected_first_products]].any(axis=1)
if selected_bought_products:
    mask &= df[[f"bought_{p}" for p in selected_bought_products]].any(axis=1)

filtered_df = df[mask].copy()

st.sidebar.info(f"📈 {len(filtered_df):,} customers after filtering")

# ---------------------------------------------------------------------------
# Metric helpers — every row is one customer.
#   count  -> number of customers
#   ltv/ltr-> mean across customers
#   orders -> mean orders per customer
#   aov    -> total revenue / total orders
#   ipo    -> total items / total orders
# ---------------------------------------------------------------------------
def scalar_metric(data, metric):
    if len(data) == 0:
        return 0
    if metric == "count":
        return len(data)
    if metric == "aov":
        total_orders = data["orders"].sum()
        return data["ltr"].sum() / total_orders if total_orders else 0
    if metric == "ipo":
        total_orders = data["orders"].sum()
        return data["items"].sum() / total_orders if total_orders else 0
    if metric == "orders":
        return data["orders"].mean()
    if metric == "ltv_cac":
        total_cac = data["cac"].sum()
        return data["ltv"].sum() / total_cac if total_cac else 0
    return data[metric].mean()  # ltv, ltr, cac, cm3


def cohort_series(data, metric):
    """Return a metric aggregated per cohort month (indexed by cohort_dt)."""
    g = data.groupby("cohort_dt")
    if metric == "count":
        s = g.size()
    elif metric == "aov":
        s = g["ltr"].sum() / g["orders"].sum()
    elif metric == "ipo":
        s = g["items"].sum() / g["orders"].sum()
    elif metric == "orders":
        s = g["orders"].mean()
    elif metric == "ltv_cac":
        s = g["ltv"].sum() / g["cac"].sum()
    else:  # ltv, ltr, cac, cm3
        s = g[metric].mean()
    return s.sort_index()


# Display precision per metric: money (LTV/LTR/CM3/CAC) 0dp; averages/ratios
# (AOV/Orders/LTV:CAC) 1dp; IPO 2dp; count integer.
METRIC_DP = {"count": 0, "ltv": 0, "ltr": 0, "cm3": 0, "cac": 0,
             "ltv_cac": 1, "aov": 1, "orders": 1, "ipo": 2}
COL_DP = {"Customers": 0, "LTV": 0, "LTR": 0, "CM3": 0, "CAC": 0,
          "LTV:CAC": 1, "AOV": 1, "Orders/Customer": 1, "IPO": 2}


def table_config(frame):
    """Per-column number formatting so st.dataframe shows the intended decimals."""
    return {c: st.column_config.NumberColumn(format=f"%.{d}f")
            for c, d in COL_DP.items() if c in frame.columns}


def show_table(frame):
    st.dataframe(frame, width="stretch", hide_index=True, column_config=table_config(frame))


# Main content
col1, col2 = st.columns([2, 1])

with col1:
    metric = st.selectbox(
        "Select Metric to Display",
        ["count", "ltv", "cm3", "cac", "ltv_cac", "ltr", "aov", "ipo", "orders"],
        index=1,  # default to LTV
        format_func=lambda x: {
            "count": "Customer Count",
            "ltv": "LTV (Lifetime Value)",
            "cm3": "CM3 (LTV − CAC)",
            "cac": "CAC (Acquisition Cost)",
            "ltv_cac": "LTV : CAC ratio",
            "ltr": "LTR (Lifetime Revenue)",
            "aov": "AOV (Average Order Value)",
            "ipo": "IPO (Items Per Order)",
            "orders": "Orders Per Customer",
        }[x],
        key="metric_select",
    )

with col2:
    time_series_breakdown = st.radio(
        "Time Series Breakdown",
        ["No Breakdown (Total)", "By Subscriber Type", "By Quiz Client", "By Consult Client"],
        key="ts_breakdown",
        horizontal=False,
    )

# Only "count" is a total; everything else (incl. CAC metrics) shows as an average/ratio.
is_per_customer = metric != "count"

# Main graph and stats area
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"Data Summary ({len(filtered_df):,} customers)")
    if len(filtered_df) > 0:
        fig_time = go.Figure()

        if time_series_breakdown == "No Breakdown (Total)":
            breakdown_dim = None
            breakdown_values = [None]
        elif time_series_breakdown == "By Subscriber Type":
            breakdown_dim = "subscriber_type"
            breakdown_values = sorted(filtered_df[breakdown_dim].unique())
        elif time_series_breakdown == "By Quiz Client":
            breakdown_dim = "quiz_client"
            breakdown_values = [False, True]
        else:  # By Consult Client
            breakdown_dim = "consult_client"
            breakdown_values = [False, True]

        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
        all_plot_values = []

        for idx, breakdown_val in enumerate(breakdown_values):
            if breakdown_dim:
                subset = filtered_df[filtered_df[breakdown_dim] == breakdown_val]
                label = "Yes" if breakdown_val is True else "No" if breakdown_val is False else breakdown_val
            else:
                subset = filtered_df
                label = "All"

            series = cohort_series(subset, metric).dropna()
            all_plot_values.extend(series.values)

            fig_time.add_trace(
                go.Scatter(
                    x=series.index,
                    y=series.values,
                    mode="lines+markers",
                    name=label,
                    line=dict(color=colors[idx % len(colors)], width=2),
                    marker=dict(size=6),
                )
            )

        # Add an "All" reference line when a breakdown is active.
        if breakdown_dim:
            series_all = cohort_series(filtered_df, metric).dropna()
            all_plot_values.extend(series_all.values)
            fig_time.add_trace(
                go.Scatter(
                    x=series_all.index,
                    y=series_all.values,
                    mode="lines+markers",
                    name="All",
                    line=dict(color="black", width=3, dash="dash"),
                    marker=dict(size=6),
                )
            )

        fig_time.update_layout(
            title=f"{metric.upper()} by Cohort ({horizon} Window)",
            xaxis_title="Cohort Month",
            yaxis_title=metric.upper(),
            hovermode="x unified",
            height=450,
        )
        st.plotly_chart(fig_time, width="stretch")

with col2:
    st.subheader("Quick Stats")
    if len(filtered_df) > 0:
        dp = METRIC_DP.get(metric, 0)
        if is_per_customer:
            st.metric("Avg", f"{scalar_metric(filtered_df, metric):,.{dp}f}")
            if all_plot_values:
                st.metric("Min (Plotted)", f"{min(all_plot_values):,.{dp}f}")
                st.metric("Max (Plotted)", f"{max(all_plot_values):,.{dp}f}")
        else:
            st.metric("Total Customers", f"{len(filtered_df):,.0f}")
            if all_plot_values:
                st.metric("Min (Plotted)", f"{min(all_plot_values):,.0f}")
                st.metric("Max (Plotted)", f"{max(all_plot_values):,.0f}")
    else:
        st.warning("No data matches your filters")

st.divider()


def breakdown_table(rows):
    """Build a tidy breakdown dataframe from a list of (label, subset) pairs."""
    out = []
    for label, seg in rows:
        if len(seg) == 0:
            continue
        out.append({
            "Segment": label,
            "Customers": len(seg),
            "LTV": round(scalar_metric(seg, "ltv"), 0),
            "CAC": round(scalar_metric(seg, "cac"), 0),
            "CM3": round(scalar_metric(seg, "cm3"), 0),
            "LTV:CAC": round(scalar_metric(seg, "ltv_cac"), 1),
            "LTR": round(scalar_metric(seg, "ltr"), 0),
            "AOV": round(scalar_metric(seg, "aov"), 1),
            "IPO": round(scalar_metric(seg, "ipo"), 2),
            "Orders/Customer": round(scalar_metric(seg, "orders"), 1),
        })
    return pd.DataFrame(out).sort_values("Customers", ascending=False) if out else pd.DataFrame()


# Breakdown by First Product (each row = customers whose first order included that product;
# rows overlap because a first order can include several products — each is a valid segment).
st.subheader("Breakdown by First Order Product")
st.caption("Customers can appear under more than one product (multi-item first orders). Each row is an independent segment.")
if len(filtered_df) > 0:
    rows = [(p, filtered_df[filtered_df[f"first_{p}"]]) for p in PRODUCTS]
    tbl = breakdown_table(rows)
    if len(tbl):
        show_table(tbl)
    else:
        st.info("No first-order product activity in this selection.")
else:
    st.warning("No data to display")

st.divider()

# Breakdown by Products Bought in Window
st.subheader("Breakdown by Products Bought (in window)")
st.caption("Customers can appear under more than one product. Each row is an independent segment.")
if len(filtered_df) > 0:
    rows = [(p, filtered_df[filtered_df[f"bought_{p}"]]) for p in PRODUCTS]
    tbl = breakdown_table(rows)
    if len(tbl):
        show_table(tbl)
    else:
        st.info("No product activity in this selection.")
else:
    st.warning("No data to display")

st.divider()

# Breakdown by Subscriber Type (non-overlapping — clean partition)
st.subheader("Breakdown by Subscriber Type")
if len(filtered_df) > 0:
    rows = [(s, filtered_df[filtered_df["subscriber_type"] == s]) for s in sorted(filtered_df["subscriber_type"].unique())]
    show_table(breakdown_table(rows))
else:
    st.warning("No data to display")

st.divider()

# Breakdown by Quiz / Consult
col1, col2 = st.columns(2)
with col1:
    st.subheader("Breakdown by Quiz Client Status")
    if len(filtered_df) > 0:
        rows = [
            ("Quiz Client", filtered_df[filtered_df["quiz_client"]]),
            ("Non-Quiz", filtered_df[~filtered_df["quiz_client"]]),
        ]
        show_table(breakdown_table(rows))
    else:
        st.warning("No data to display")

with col2:
    st.subheader("Breakdown by Consult Client Status")
    if len(filtered_df) > 0:
        rows = [
            ("Consult Client", filtered_df[filtered_df["consult_client"]]),
            ("Non-Consult", filtered_df[~filtered_df["consult_client"]]),
        ]
        show_table(breakdown_table(rows))
    else:
        st.warning("No data to display")

st.divider()

# Detailed (aggregated) table — one row per cohort × subscriber type
st.subheader("Detailed Data (by cohort & subscriber type)")
if len(filtered_df) > 0:
    detail = []
    for (cohort, sub), seg in filtered_df.groupby(["cohort_month", "subscriber_type"]):
        detail.append({
            "Cohort Month": cohort,
            "Subscriber Type": sub,
            "Customers": len(seg),
            "LTV": round(scalar_metric(seg, "ltv"), 0),
            "CAC": round(scalar_metric(seg, "cac"), 0),
            "CM3": round(scalar_metric(seg, "cm3"), 0),
            "LTV:CAC": round(scalar_metric(seg, "ltv_cac"), 1),
            "LTR": round(scalar_metric(seg, "ltr"), 0),
            "AOV": round(scalar_metric(seg, "aov"), 1),
            "IPO": round(scalar_metric(seg, "ipo"), 2),
            "Orders/Customer": round(scalar_metric(seg, "orders"), 1),
        })
    detail_df = pd.DataFrame(detail).sort_values(["Cohort Month", "Subscriber Type"]).reset_index(drop=True)
    show_table(detail_df)
else:
    st.warning("No data to display with current filters")

st.divider()

# Heatmap — product × product (and product × subscriber type)
st.subheader("Segment Performance Heatmap")


def dim_accessor(dim):
    """Return (values, selector(data, value)) for a heatmap dimension."""
    if dim == "first":
        return PRODUCTS, lambda d, v: d[d[f"first_{v}"]]
    if dim == "bought":
        return PRODUCTS, lambda d, v: d[d[f"bought_{v}"]]
    # subscriber_type
    return sorted(filtered_df["subscriber_type"].unique()), lambda d, v: d[d["subscriber_type"] == v]


if len(filtered_df) > 0:
    heatmap_config = st.radio(
        "Heatmap Layout",
        ["First × Bought Products", "First Product × Subscriber Type", "Bought Product × Subscriber Type"],
        horizontal=True,
        key="heatmap_config",
    )

    if heatmap_config == "First × Bought Products":
        row_dim, col_dim = "first", "bought"
        row_title, col_title = "First Order Product", "Bought In Window"
    elif heatmap_config == "First Product × Subscriber Type":
        row_dim, col_dim = "first", "subscriber_type"
        row_title, col_title = "First Order Product", "Subscriber Type"
    else:
        row_dim, col_dim = "bought", "subscriber_type"
        row_title, col_title = "Bought In Window", "Subscriber Type"

    row_vals, row_sel = dim_accessor(row_dim)
    col_vals, col_sel = dim_accessor(col_dim)

    dp = METRIC_DP.get(metric, 1)
    z = []
    for rv in row_vals:
        row_data = row_sel(filtered_df, rv)
        z.append([round(scalar_metric(col_sel(row_data, cv), metric), dp) for cv in col_vals])

    fig_heat = go.Figure(
        data=go.Heatmap(
            z=z,
            x=col_vals,
            y=row_vals,
            colorscale="YlOrRd",
            text=[[f"{v:,.{dp}f}" for v in row] for row in z],
            texttemplate="%{text}",
            textfont={"size": 9},
        )
    )
    fig_heat.update_layout(
        title=f"{metric.upper()} Heatmap: {row_title} × {col_title}",
        xaxis_title=col_title,
        yaxis_title=row_title,
        height=max(400, len(row_vals) * 30),
    )
    st.plotly_chart(fig_heat, width="stretch")
else:
    st.warning("No data to display")
