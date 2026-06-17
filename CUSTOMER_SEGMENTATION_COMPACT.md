# Customer Segmentation with LTV - Compact Summary

## What Was Built
**File**: `customer_segmentation.py` → `reports/customer_segmentation.xlsx` (33,743 rows)

Segments 196,783 customers by:
- **Subscriber Type**: Single Item Sub | Multi Item Sub | OTP
- **First Product**: 11 target products + All
- **All Products**: 11 target products + All  
- **Time**: 66 months (Jan 2021 - Jun 2026)

## Key Metrics Per Segment
- **count**: Unique customers
- **ltr**: Revenue per customer
- **ltv**: Profit per customer (revenue - COGS - fulfillment)
- **aov**: Average order value
- **ipo**: Items per order
- **orders**: Orders per customer

## How LTV Works

```
LTV = order_net_sales - order_cogs - order_fulfillment_cost
```

**COGS Calculation**:
- Load from `data/COGS FY22_27.xlsx` (321 SKUs, FY22-FY27)
- Match by SKU + fiscal year (May onwards → next FY)
- Bundles: use child SKU costs only
- 1,862,826 orders have COGS calculated

**Fulfillment Cost Allocation**:
- Load from `data/fulfilment costs.csv` (monthly totals)
- Weight: first orders = 1.32x, repeat = 1.0x
- Monthly total × (order_weight / total_weight) = order_fc
- 1,991,997 orders have fulfillment allocated

## Data Quality

✓ All 196,783 valid customers accounted for  
✓ Count validation: consult + no_consult = All  
✓ LTV < LTR everywhere (costs reduce revenue)  
✓ 910,174 orders in 12-month window  

## Ready For Streamlit

Columns support interactive filtering:
- Month dropdown
- Fiscal year dropdown
- Subscriber type dropdown
- First product dropdown
- All products dropdown

Display any metric: count, ltr, ltv, aov, ipo, orders

## File Locations

- **Script**: `customer_segmentation.py`
- **Output**: `reports/customer_segmentation.xlsx`
- **COGS**: `data/COGS FY22_27.xlsx`
- **Fulfillment**: `data/fulfilment costs.csv`
- **Source data**: `subscriptions.parquet`

## Next Step

Build Streamlit dashboard with filters and charts to explore segments interactively.
