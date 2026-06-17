#!/bin/bash
set -e

echo "=== Subscription Dashboard - GCP Cloud Run Deployment ==="
echo ""

# Prompt for project ID
read -p "Enter your GCP Project ID: " PROJECT_ID
read -p "Enter the service name (default: subscription-dashboard): " SERVICE_NAME
SERVICE_NAME=${SERVICE_NAME:-subscription-dashboard}
REGION="us-central1"

echo ""
echo "Configuration:"
echo "  Project ID: $PROJECT_ID"
echo "  Service: $SERVICE_NAME"
echo "  Region: $REGION"
echo ""

# Set project
gcloud config set project $PROJECT_ID

# Enable APIs
echo "Enabling required GCP APIs..."
gcloud services enable run.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable cloudbuild.googleapis.com

# Create Artifact Registry repo
echo "Creating Artifact Registry repository..."
gcloud artifacts repositories create $SERVICE_NAME \
  --repository-format=docker \
  --location=$REGION \
  --description="Subscription dashboard" \
  2>/dev/null || echo "Repository already exists"

# Build and push
IMAGE_NAME="$REGION-docker.pkg.dev/$PROJECT_ID/$SERVICE_NAME/dashboard"
echo ""
echo "Building and pushing Docker image..."
echo "Image: $IMAGE_NAME"
gcloud builds submit --tag $IMAGE_NAME:latest

# Deploy to Cloud Run
echo ""
echo "Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image=$IMAGE_NAME:latest \
  --platform=managed \
  --region=$REGION \
  --memory=2Gi \
  --cpu=1 \
  --timeout=3600 \
  --no-allow-unauthenticated \
  --allow-unauthenticated=false

# Get URL
echo ""
echo "=== Deployment Complete ==="
URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --format='value(status.url)')
echo "Dashboard URL: $URL"
echo ""
echo "Next steps:"
echo "1. Grant team access:"
echo "   gcloud run services add-iam-policy-binding $SERVICE_NAME \\"
echo "     --region=$REGION \\"
echo "     --member=group:data-team@company.com \\"
echo "     --role=roles/run.invoker"
echo ""
echo "2. Share the URL with your team"
echo "3. Team members sign in with their Google account"
echo ""
