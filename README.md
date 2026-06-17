# Customer Segmentation & LTV Dashboard

A Streamlit-based interactive dashboard for analyzing customer lifetime value (LTV), order value (AOV), and subscription metrics by cohort, product, and program status.

## 📁 Project Structure

```
dashboard/
├── dashboard.py                    # Main Streamlit app
├── customer_segmentation.py        # Data processing & aggregation
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Container configuration
├── deploy-gcp.sh                   # GCP Cloud Run deployment script
│
├── data/                           # Input data
│   ├── COGS FY22_27.xlsx          # Cost of goods sold by SKU/FY
│   └── fulfilment costs.csv       # Monthly fulfillment costs
│
├── reports/                        # Output data
│   └── customer_segmentation.xlsx # Processed segmentation data
│
├── pipeline/                       # Data processing utilities
│   ├── config.py                  # Configuration (paths, constants)
│   ├── google_sheets.py           # Google Sheets integration
│   ├── transform.py               # Data transformations
│   ├── reports.py                 # Report generation
│   └── product_short_names.json   # Product mapping
│
├── CLAUDE.md                       # Project documentation
├── CUSTOMER_SEGMENTATION_COMPACT.md # Data structure & methodology
├── DEPLOYMENT.md                   # Local/Docker/Server deployment
├── GCP_DEPLOYMENT.md              # Google Cloud Run setup
└── README.md                       # This file
```

## 🚀 Quick Start

### Local Development

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Make sure Excel data is in place
# - data/COGS FY22_27.xlsx
# - data/fulfilment costs.csv
# - data/subscriptions.parquet (from pipeline)

# 3. Generate segmentation data (if needed)
python customer_segmentation.py

# 4. Run dashboard
streamlit run dashboard.py
```

Access at: `http://localhost:8501`

### Docker (Local)

```bash
# Build image
docker build -t subscription-dashboard .

# Run container
docker run -p 8501:8501 subscription-dashboard
```

Access at: `http://localhost:8501`

### Google Cloud Run

See **GCP_DEPLOYMENT.md** for step-by-step instructions.

Quick command:
```bash
./deploy-gcp.sh
```

## 📊 Dashboard Features

### Filters (Sidebar)
- **Cohort Month**: Choose customer acquisition date(s)
- **Fiscal Year**: FY21-FY27
- **Subscriber Type**: OTP, Single Item Sub, Multi Item Sub
- **First Product**: 11 target products + All
- **All Products**: Products in customer lifetime
- **Quiz Client**: Yes/No
- **Consult Client**: Yes/No

### Metrics
- **LTV**: Lifetime value (revenue - COGS - fulfillment)
- **LTR**: Lifetime revenue per customer
- **AOV**: Average order value
- **IPO**: Items per order
- **Orders/Customer**: Order count per customer
- **Count**: Unique customers

### Visualizations
1. **Time Series Chart** (12-month windows by cohort)
   - Breakdown by Subscriber Type, Quiz Client, or Consult Client
   - Multi-line comparison with weighted averages

2. **Quick Stats**
   - Weighted average of selected metric
   - Min/Max of plotted lines

3. **Breakdown Tables**
   - By First Product
   - By Subscriber Type
   - By Quiz Client Status
   - By Consult Client Status

4. **Heatmap** (Configurable dimensions)
   - First Product × All Products
   - First Product × Subscriber Type
   - All Products × Subscriber Type

5. **Detailed Data Table**
   - All segmentation data
   - Sortable by any dimension

## 🔄 Data Pipeline

### Input Files
- `data/subscriptions.parquet` — Raw order data (from ingest pipeline)
- `data/COGS FY22_27.xlsx` — Product cost of goods sold
- `data/fulfilment costs.csv` — Monthly fulfillment cost totals

### Processing
`customer_segmentation.py` runs:
1. Load subscriptions.parquet
2. Calculate COGS per order (by SKU + fiscal year)
3. Allocate fulfillment costs (weighted by new vs returning)
4. Compute LTV = revenue - COGS - fulfillment
5. Segment by: cohort month, subscriber type, products, quiz/consult flags
6. Aggregate metrics (count, LTV, LTR, AOV, IPO, orders)
7. Export to `reports/customer_segmentation.xlsx`

### Output File
`reports/customer_segmentation.xlsx` — 38,842 rows × 13 columns
- Dimensions: cohort_month, fy, subscriber_type, first_product, all_products, quiz_client, consult_client
- Metrics: count, ltr, ltv, aov, ipo, orders

## 📈 Key Metrics & Definitions

**LTV (Lifetime Value)**
```
LTV = order_net_sales - order_cogs - order_fulfillment_cost
```

**LTR (Lifetime Revenue)**
```
LTR = order_net_sales (sum across all orders in 12-month window)
```

**AOV (Average Order Value)**
```
AOV = LTR / order_count
```

**IPO (Items Per Order)**
```
IPO = items_in_order / order_count
```

**Weighted Averages**
When aggregating across segments:
```
weighted_avg = sum(metric × customer_count) / sum(customer_count)
```

## 🔐 Deployment & Access Control

### Local
- No auth required (local only)

### Docker
- VPN/IP whitelist via firewall

### Google Cloud Run
- **No public access** — only users with IAM role can access
- Grant access: `gcloud run services add-iam-policy-binding dashboard --member=group:data-team@company.com --role=roles/run.invoker`
- Cost: ~$10-15/month for light usage

## 📝 Maintenance

### Updating Data
```bash
# Regenerate segmentation
python customer_segmentation.py

# If deployed to Cloud Run:
# 1. Update Excel file in reports/
# 2. Redeploy or upload to Cloud Storage
```

### Scheduled Updates (Cloud Run)
See **GCP_DEPLOYMENT.md** → "Updating Data" → "Option B: Scheduled Updates"

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 8501 in use | Change port: `streamlit run dashboard.py --server.port=8502` |
| Missing data files | Check `data/` and `reports/` directories exist |
| Dashboard won't load | Check logs: `streamlit run dashboard.py --logger.level=debug` |
| Cloud Run access denied | Verify IAM role: `gcloud run services get-iam-policy subscription-dashboard --region=us-central1` |
| Data is stale | Run `python customer_segmentation.py` to regenerate |

## 📚 Documentation

- **CLAUDE.md** — Project overview & quirks (order-level classification, bundle handling, etc.)
- **CUSTOMER_SEGMENTATION_COMPACT.md** — Data structure & how LTV is calculated
- **DEPLOYMENT.md** — Local, Docker, server, cloud deployment options
- **GCP_DEPLOYMENT.md** — Step-by-step Google Cloud Run setup

## 🛠️ Tech Stack

- **Frontend:** Streamlit
- **Data:** Pandas, Plotly
- **Storage:** Excel, Parquet
- **Deployment:** Docker, Google Cloud Run
- **Language:** Python 3.11+

## 📧 Questions?

Check the documentation files above, or contact your data team.
