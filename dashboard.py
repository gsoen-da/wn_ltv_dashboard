import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Customer Segmentation Dashboard", layout="wide")

st.title("📊 LTV Dashboard")

# Load data
@st.cache_data
def load_data():
    return pd.read_excel("reports/customer_segmentation.xlsx", sheet_name="Data")

df = load_data()

# Convert cohort_month to datetime for proper sorting
df["cohort_dt"] = pd.to_datetime(df["cohort_month"])
df = df.sort_values("cohort_dt")

st.sidebar.header("Filters")

# Horizon is the primary filter — pick exactly one (default 12M)
horizon = st.sidebar.radio(
    "LTV Horizon",
    ["12 Months", "6 Months"],
    index=0,
)
horizon_col = "12M" if horizon == "12 Months" else "6M"

# Everything downstream operates on the selected-horizon slice
df = df[df[horizon_col]].copy()

# Get unique values for filters (within the chosen horizon)
fys = sorted(df["fy"].unique())
subscriber_types = sorted(df["subscriber_type"].unique())
first_products = sorted(df["first_product"].unique())
all_products = sorted(df["all_products"].unique())

# FY is the next filter
selected_fy = st.sidebar.multiselect(
    "Fiscal Year",
    fys,
    default=fys[-1:],  # Default to latest FY
)

# Month filter depends on selected FY
available_months = sorted(df[df["fy"].isin(selected_fy)]["cohort_month"].unique())
selected_months = st.sidebar.multiselect(
    "Cohort Month",
    available_months,
    default=available_months[-6:] if len(available_months) >= 6 else available_months,
)

selected_subscriber = st.sidebar.multiselect(
    "Subscriber Type",
    subscriber_types,
    default=subscriber_types,
)

selected_first_product = st.sidebar.multiselect(
    "First Product",
    first_products,
    default=["All"],
)

selected_all_products = st.sidebar.multiselect(
    "All Products",
    all_products,
    default=["All"],
)

# New filters for quiz and consult
st.sidebar.subheader("Program Status")
selected_quiz = st.sidebar.multiselect(
    "Quiz Client",
    [True, False],
    default=[True, False],
    format_func=lambda x: "Yes" if x else "No",
)

selected_consult = st.sidebar.multiselect(
    "Consult Client",
    [True, False],
    default=[True, False],
    format_func=lambda x: "Yes" if x else "No",
)

# Apply filters
filtered_df = df[
    (df["cohort_month"].isin(selected_months))
    & (df["fy"].isin(selected_fy))
    & (df["subscriber_type"].isin(selected_subscriber))
    & (df["first_product"].isin(selected_first_product))
    & (df["all_products"].isin(selected_all_products))
    & (df["quiz_client"].isin(selected_quiz))
    & (df["consult_client"].isin(selected_consult))
].copy()

st.sidebar.info(f"📈 {len(filtered_df)} rows after filtering")

# Main content
col1, col2 = st.columns([2, 1])

# Metric and breakdown selection (moved to main area)
with col1:
    metric = st.selectbox(
        "Select Metric to Display",
        ["count", "ltv", "ltr", "aov", "ipo", "orders"],
        format_func=lambda x: {
            "count": "Customer Count",
            "ltv": "LTV (Lifetime Value)",
            "ltr": "LTR (Lifetime Revenue)",
            "aov": "AOV (Average Order Value)",
            "ipo": "IPO (Items Per Order)",
            "orders": "Orders Per Customer",
        }[x],
        key="metric_select"
    )

with col2:
    time_series_breakdown = st.radio(
        "Time Series Breakdown",
        ["No Breakdown (Total)", "By Subscriber Type", "By Quiz Client", "By Consult Client"],
        key="ts_breakdown",
        horizontal=False,
    )

# Main graph and stats area
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"Data Summary ({len(filtered_df)} records)")
    # Group by cohort for time series
    if len(filtered_df) > 0:
        fig_time = go.Figure()

        # Determine breakdown dimension and values
        if time_series_breakdown == "No Breakdown (Total)":
            breakdown_values = [None]
            breakdown_dim = None
        elif time_series_breakdown == "By Subscriber Type":
            breakdown_dim = "subscriber_type"
            breakdown_values = sorted(filtered_df[breakdown_dim].unique())
        elif time_series_breakdown == "By Quiz Client":
            breakdown_dim = "quiz_client"
            breakdown_values = [False, True]  # False first, then True
        else:  # By Consult Client
            breakdown_dim = "consult_client"
            breakdown_values = [False, True]

        # Create a line for each breakdown value + one for All
        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
        all_plot_values = []  # Store all values for stats

        for idx, breakdown_val in enumerate(breakdown_values):
            if breakdown_dim:
                subset = filtered_df[filtered_df[breakdown_dim] == breakdown_val]
                label = str(breakdown_val) if isinstance(breakdown_val, bool) else breakdown_val
                if isinstance(breakdown_val, bool):
                    label = "Yes" if breakdown_val else "No"
            else:
                subset = filtered_df
                label = "All"

            # Aggregate by cohort with proper weighting
            if metric in ["ltv", "ltr", "aov", "ipo", "orders"]:
                # Weighted average: multiply metric by count, sum, then divide by count sum
                weighted_sum = (subset[metric] * subset["count"]).groupby(subset["cohort_dt"]).sum()
                count_sum = subset["count"].groupby(subset["cohort_dt"]).sum()
                time_data = pd.DataFrame({
                    "cohort_dt": weighted_sum.index,
                    metric: (weighted_sum / count_sum).values
                })
            else:
                time_data = subset.groupby("cohort_dt")[metric].sum().reset_index()

            time_data = time_data.sort_values("cohort_dt")
            all_plot_values.extend(time_data[metric].values)

            fig_time.add_trace(
                go.Scatter(
                    x=time_data["cohort_dt"],
                    y=time_data[metric],
                    mode="lines+markers",
                    name=label,
                    line=dict(color=colors[idx % len(colors)], width=2),
                    marker=dict(size=6),
                )
            )

        # Add "All" line if breakdown is selected
        if breakdown_dim:
            if metric in ["ltv", "ltr", "aov", "ipo", "orders"]:
                weighted_sum_all = (filtered_df[metric] * filtered_df["count"]).groupby(filtered_df["cohort_dt"]).sum()
                count_sum_all = filtered_df["count"].groupby(filtered_df["cohort_dt"]).sum()
                time_data_all = pd.DataFrame({
                    "cohort_dt": weighted_sum_all.index,
                    metric: (weighted_sum_all / count_sum_all).values
                })
            else:
                time_data_all = filtered_df.groupby("cohort_dt")[metric].sum().reset_index()

            time_data_all = time_data_all.sort_values("cohort_dt")
            all_plot_values.extend(time_data_all[metric].values)

            fig_time.add_trace(
                go.Scatter(
                    x=time_data_all["cohort_dt"],
                    y=time_data_all[metric],
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
        st.plotly_chart(fig_time, use_container_width=True)

with col2:
    st.subheader("Quick Stats")
    if len(filtered_df) > 0:
        if metric in ["ltv", "ltr", "aov", "ipo", "orders"]:
            # For per-customer metrics, calculate weighted average of ALL filtered data
            weighted_avg = (filtered_df[metric] * filtered_df["count"]).sum() / filtered_df["count"].sum()
            st.metric(
                "Avg (Weighted)",
                f"{weighted_avg:,.2f}",
            )
            # Min/Max of the actual plotted lines
            if all_plot_values:
                st.metric(
                    "Min (Plotted)",
                    f"{min(all_plot_values):,.2f}",
                )
                st.metric(
                    "Max (Plotted)",
                    f"{max(all_plot_values):,.2f}",
                )
        else:
            # For count, sum total customers
            st.metric(
                "Total",
                f"{filtered_df[metric].sum():,.0f}",
            )
            # Min/Max of plotted lines
            if all_plot_values:
                st.metric(
                    "Min (Plotted)",
                    f"{min(all_plot_values):,.0f}",
                )
                st.metric(
                    "Max (Plotted)",
                    f"{max(all_plot_values):,.0f}",
                )
    else:
        st.warning("No data matches your filters")

st.divider()

# Breakdown by First Product (detailed table)
st.subheader("Breakdown by First Product")
if len(filtered_df) > 0:
    # Aggregate by first_product with weighted averages for per-customer metrics
    prod_breakdown = []
    for product in filtered_df["first_product"].unique():
        product_data = filtered_df[filtered_df["first_product"] == product]
        total_count = product_data["count"].sum()

        row = {
            "First Product": product,
            "Customers": total_count,
            "LTV": round((product_data["ltv"] * product_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
            "LTR": round((product_data["ltr"] * product_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
            "AOV": round((product_data["aov"] * product_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
            "IPO": round((product_data["ipo"] * product_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
            "Orders/Customer": round((product_data["orders"] * product_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
        }
        prod_breakdown.append(row)

    prod_breakdown_df = pd.DataFrame(prod_breakdown).sort_values("Customers", ascending=False)
    st.dataframe(prod_breakdown_df, use_container_width=True, hide_index=True)
else:
    st.warning("No data to display")

st.divider()

# Breakdown by Subscriber Type (detailed table)
st.subheader("Breakdown by Subscriber Type")
if len(filtered_df) > 0:
    # Aggregate by subscriber_type with weighted averages
    sub_breakdown = []
    for sub_type in filtered_df["subscriber_type"].unique():
        sub_data = filtered_df[filtered_df["subscriber_type"] == sub_type]
        total_count = sub_data["count"].sum()

        row = {
            "Subscriber Type": sub_type,
            "Customers": total_count,
            "LTV": round((sub_data["ltv"] * sub_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
            "LTR": round((sub_data["ltr"] * sub_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
            "AOV": round((sub_data["aov"] * sub_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
            "IPO": round((sub_data["ipo"] * sub_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
            "Orders/Customer": round((sub_data["orders"] * sub_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
        }
        sub_breakdown.append(row)

    sub_breakdown_df = pd.DataFrame(sub_breakdown).sort_values("Customers", ascending=False)
    st.dataframe(sub_breakdown_df, use_container_width=True, hide_index=True)
else:
    st.warning("No data to display")

st.divider()

# Breakdown by Quiz/Consult Status
col1, col2 = st.columns(2)

with col1:
    st.subheader("Breakdown by Quiz Client Status")
    if len(filtered_df) > 0:
        quiz_breakdown = []
        for status in [True, False]:
            quiz_data = filtered_df[filtered_df["quiz_client"] == status]
            total_count = quiz_data["count"].sum()

            row = {
                "Status": "Quiz Client" if status else "Non-Quiz",
                "Customers": total_count,
                "LTV": round((quiz_data["ltv"] * quiz_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
                "LTR": round((quiz_data["ltr"] * quiz_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
                "AOV": round((quiz_data["aov"] * quiz_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
                "IPO": round((quiz_data["ipo"] * quiz_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
                "Orders/Customer": round((quiz_data["orders"] * quiz_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
            }
            quiz_breakdown.append(row)

        quiz_breakdown_df = pd.DataFrame(quiz_breakdown).sort_values("Customers", ascending=False)
        st.dataframe(quiz_breakdown_df, use_container_width=True, hide_index=True)
    else:
        st.warning("No data to display")

with col2:
    st.subheader("Breakdown by Consult Client Status")
    if len(filtered_df) > 0:
        consult_breakdown = []
        for status in [True, False]:
            consult_data = filtered_df[filtered_df["consult_client"] == status]
            total_count = consult_data["count"].sum()

            row = {
                "Status": "Consult Client" if status else "Non-Consult",
                "Customers": total_count,
                "LTV": round((consult_data["ltv"] * consult_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
                "LTR": round((consult_data["ltr"] * consult_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
                "AOV": round((consult_data["aov"] * consult_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
                "IPO": round((consult_data["ipo"] * consult_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
                "Orders/Customer": round((consult_data["orders"] * consult_data["count"]).sum() / total_count, 2) if total_count > 0 else 0,
            }
            consult_breakdown.append(row)

        consult_breakdown_df = pd.DataFrame(consult_breakdown).sort_values("Customers", ascending=False)
        st.dataframe(consult_breakdown_df, use_container_width=True, hide_index=True)
    else:
        st.warning("No data to display")

st.divider()

# Detailed data table
st.subheader("Detailed Data")
display_cols = ["cohort_month", "fy", "subscriber_type", "first_product", "all_products", "quiz_client", "consult_client", "count", "ltv", "ltr", "aov", "ipo", "orders"]
if len(filtered_df) > 0:
    st.dataframe(
        filtered_df[display_cols]
        .sort_values(["cohort_month", "subscriber_type", "first_product"])
        .reset_index(drop=True),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.warning("No data to display with current filters")

# Heatmap option
st.divider()
st.subheader("Segment Performance Heatmap")

# Helper function to create weighted average heatmap
def create_heatmap(data, row_dim, col_dim, metric_col):
    """Create heatmap using weighted averages for per-customer metrics"""
    result = []
    for row_val in data[row_dim].unique():
        row_data = []
        for col_val in data[col_dim].unique():
            cell_data = data[(data[row_dim] == row_val) & (data[col_dim] == col_val)]
            if len(cell_data) > 0:
                if metric_col in ["ltv", "ltr", "aov", "ipo", "orders"]:
                    # Weighted average for per-customer metrics
                    total_count = cell_data["count"].sum()
                    weighted_avg = (cell_data[metric_col] * cell_data["count"]).sum() / total_count if total_count > 0 else 0
                    row_data.append(round(weighted_avg, 2))
                else:
                    # Sum for count metrics
                    row_data.append(round(cell_data[metric_col].sum(), 2))
            else:
                row_data.append(0)
        result.append(row_data)
    return result

if len(filtered_df) > 0:
    heatmap_config = st.radio(
        "Heatmap Layout",
        ["First Product × All Products", "First Product × Subscriber Type", "All Products × Subscriber Type"],
        horizontal=True,
        key="heatmap_config"
    )

    if heatmap_config == "First Product × All Products":
        row_dim, col_dim = "first_product", "all_products"
    elif heatmap_config == "First Product × Subscriber Type":
        row_dim, col_dim = "first_product", "subscriber_type"
    else:  # All Products × Subscriber Type
        row_dim, col_dim = "all_products", "subscriber_type"

    # Get unique values for heatmap
    rows = sorted(filtered_df[row_dim].unique())
    cols = sorted(filtered_df[col_dim].unique())

    # Create weighted average heatmap data
    heatmap_values = create_heatmap(filtered_df, row_dim, col_dim, metric)

    fig_heat = go.Figure(
        data=go.Heatmap(
            z=heatmap_values,
            x=cols,
            y=rows,
            colorscale="YlOrRd",
            text=[[f"{v:.1f}" for v in row] for row in heatmap_values],
            texttemplate="%{text}",
            textfont={"size": 9},
        )
    )
    fig_heat.update_layout(
        title=f"{metric.upper()} Heatmap: {row_dim.title()} × {col_dim.title()} (Weighted Avg)",
        xaxis_title=col_dim.replace("_", " ").title(),
        yaxis_title=row_dim.replace("_", " ").title(),
        height=max(400, len(rows) * 30),
    )
    st.plotly_chart(fig_heat, use_container_width=True)
else:
    st.warning("No data to display")
