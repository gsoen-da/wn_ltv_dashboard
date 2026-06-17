# GCP Cloud Run Deployment Guide

## Overview
- **Service:** Cloud Run (serverless, auto-scales)
- **Cost:** ~$0.40/month for light usage, scales with traffic
- **Setup Time:** 15-20 minutes
- **Access:** Restricted to team via IAM roles

---

## Prerequisites

1. **GCP Project** with billing enabled
2. **gcloud CLI** installed ([download](https://cloud.google.com/sdk/docs/install))
3. **Docker** installed locally (for testing)
4. Appropriate GCP permissions (Project Editor or Cloud Run Admin)

---

## Step 1: Prepare Your Code

### Update Dockerfile for Cloud Run

The existing `Dockerfile` needs one small update for Cloud Run:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app and data
COPY dashboard.py .
COPY reports/ reports/
COPY pipeline/ pipeline/
COPY data/ data/

# Cloud Run requires port 8080 (or set via PORT env var)
EXPOSE 8080

# Run streamlit on Cloud Run
CMD ["streamlit", "run", "dashboard.py", \
     "--server.port=${PORT:-8080}", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
```

Update `requirements.txt` if needed (add any missing packages).

---

## Step 2: Set Up GCP Project

```bash
# 1. Set your project ID
export PROJECT_ID="your-gcp-project-id"
gcloud config set project $PROJECT_ID

# 2. Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable cloudbuild.googleapis.com

# 3. Authenticate with Docker
gcloud auth configure-docker us-central1-docker.pkg.dev
```

---

## Step 3: Create Artifact Registry Repository

```bash
# Create Docker repository in Artifact Registry
gcloud artifacts repositories create subscription-dashboard \
  --repository-format=docker \
  --location=us-central1 \
  --description="Subscription dashboard images"
```

---

## Step 4: Build and Push Docker Image

```bash
# Set variables
export PROJECT_ID="your-gcp-project-id"
export IMAGE_NAME="us-central1-docker.pkg.dev/${PROJECT_ID}/subscription-dashboard/dashboard"

# Build image
docker build -t $IMAGE_NAME:latest .

# Push to Artifact Registry
docker push $IMAGE_NAME:latest
```

Or use Cloud Build (builds in GCP, no local Docker needed):

```bash
gcloud builds submit --tag $IMAGE_NAME:latest
```

---

## Step 5: Deploy to Cloud Run

```bash
export PROJECT_ID="your-gcp-project-id"
export IMAGE_NAME="us-central1-docker.pkg.dev/${PROJECT_ID}/subscription-dashboard/dashboard"
export SERVICE_NAME="subscription-dashboard"

gcloud run deploy $SERVICE_NAME \
  --image=$IMAGE_NAME:latest \
  --platform=managed \
  --region=us-central1 \
  --memory=2Gi \
  --cpu=1 \
  --timeout=3600 \
  --no-allow-unauthenticated
```

**Parameters explained:**
- `--no-allow-unauthenticated`: Only team with IAM role can access
- `--memory=2Gi`: 2GB RAM (sufficient for this app)
- `--cpu=1`: 1 CPU core
- `--timeout=3600`: 1 hour timeout (for data updates)
- `--region=us-central1`: Change to your preferred region

---

## Step 6: Get the Service URL

```bash
gcloud run services describe subscription-dashboard \
  --region=us-central1 \
  --format='value(status.url)'
```

You'll get something like:
```
https://subscription-dashboard-abc123-uc.a.run.app
```

---

## Step 7: Grant Team Access

### Option A: Grant Individual Users

```bash
# Grant user access
gcloud run services add-iam-policy-binding subscription-dashboard \
  --region=us-central1 \
  --member=user:colleague@company.com \
  --role=roles/run.invoker

# Repeat for each team member
gcloud run services add-iam-policy-binding subscription-dashboard \
  --region=us-central1 \
  --member=user:another@company.com \
  --role=roles/run.invoker
```

### Option B: Grant Google Group Access (Better)

```bash
# If your team has a Google Group (e.g., data-team@company.com)
gcloud run services add-iam-policy-binding subscription-dashboard \
  --region=us-central1 \
  --member=group:data-team@company.com \
  --role=roles/run.invoker
```

---

## Step 8: Test Access

1. Go to the URL from Step 6
2. You'll be prompted to sign in with Google
3. If you have the `roles/run.invoker` role, you'll see the dashboard
4. If not, you'll get a 403 Forbidden error

---

## Updating Data

### Option A: Manual Update (Easiest)

```bash
# Create Cloud Storage bucket for Excel files
gsutil mb gs://${PROJECT_ID}-dashboard-data

# Upload latest Excel file
gsutil cp reports/customer_segmentation.xlsx gs://${PROJECT_ID}-dashboard-data/

# Update the dashboard to read from Cloud Storage
# (See next section)
```

### Option B: Scheduled Updates (Best)

Create a Cloud Function to regenerate data on a schedule:

1. **Create `update_data.py`:**
```python
import functions_framework
from customer_segmentation import main
import storage
import datetime

@functions_framework.http
def update_data(request):
    try:
        # Run customer_segmentation.py
        main()
        
        # Upload to Cloud Storage
        bucket = storage.Client().bucket(f"{PROJECT_ID}-dashboard-data")
        blob = bucket.blob("customer_segmentation.xlsx")
        blob.upload_from_filename("reports/customer_segmentation.xlsx")
        
        return {"status": "success", "timestamp": datetime.datetime.now().isoformat()}
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500
```

2. **Deploy Cloud Function:**
```bash
gcloud functions deploy update-dashboard \
  --runtime python311 \
  --trigger-topic dashboard-update \
  --entry-point update_data \
  --memory 2GB \
  --timeout 3600
```

3. **Schedule with Cloud Scheduler:**
```bash
# Run every Sunday at 2 AM UTC
gcloud scheduler jobs create pubsub update-dashboard-weekly \
  --schedule "0 2 * * 0" \
  --topic dashboard-update \
  --message-body '{}'
```

---

## Monitoring & Logs

### View Logs
```bash
gcloud run services logs read subscription-dashboard \
  --region=us-central1 \
  --limit=50
```

### View Metrics
```bash
# In Cloud Console:
# Cloud Run > subscription-dashboard > Metrics
# - Requests, Errors, Latency, Execution Time
```

### Set Up Alerts
In Cloud Console:
1. Go to Cloud Run > subscription-dashboard
2. Create alert policy for error rate > 5%
3. Add email notification

---

## Cost Estimation

**Monthly costs (estimate):**
- Compute: $0.24/CPU-hour = ~$5-10/month (if 10 users × 2 hrs/month)
- Memory: $0.05/GB-hour = ~$2-5/month
- Requests: Free tier covers 2M requests/month
- **Total: $10-15/month for light usage**

---

## Troubleshooting

### Dashboard won't load
```bash
# Check logs
gcloud run services logs read subscription-dashboard --region=us-central1

# Common issues:
# - Port 8080 not exposed (update Dockerfile)
# - Missing data files (check COPY commands)
# - Streamlit port conflict (use $PORT env var)
```

### Access denied (403)
```bash
# Check IAM role
gcloud run services get-iam-policy subscription-dashboard --region=us-central1

# Add user again
gcloud run services add-iam-policy-binding subscription-dashboard \
  --region=us-central1 \
  --member=user:email@company.com \
  --role=roles/run.invoker
```

### Data is stale
- Run manual update: upload new Excel file to Cloud Storage
- OR set up scheduled Cloud Function (see Option B above)

---

## Next Steps

1. **Update Dockerfile** (change port to 8080)
2. **Run `gcloud builds submit`** to deploy
3. **Grant IAM roles** to team members
4. **Test the URL** and share with team
5. **Set up data refresh** (manual or scheduled)

---

## Quick Command Reference

```bash
# Deploy
gcloud builds submit --tag us-central1-docker.pkg.dev/$PROJECT_ID/subscription-dashboard/dashboard:latest && \
gcloud run deploy subscription-dashboard \
  --image=us-central1-docker.pkg.dev/$PROJECT_ID/subscription-dashboard/dashboard:latest \
  --platform=managed --region=us-central1 --no-allow-unauthenticated

# Get URL
gcloud run services describe subscription-dashboard --region=us-central1 --format='value(status.url)'

# Grant access
gcloud run services add-iam-policy-binding subscription-dashboard \
  --region=us-central1 --member=group:data-team@company.com --role=roles/run.invoker

# View logs
gcloud run services logs read subscription-dashboard --region=us-central1 --limit=50
```

---

## Questions?

- **Authentication issues?** Make sure you're signed in with a Google account in the `@company.com` domain
- **Data not updating?** Upload new Excel file or set up Cloud Scheduler
- **Performance slow?** Increase `--memory` and `--cpu` values
