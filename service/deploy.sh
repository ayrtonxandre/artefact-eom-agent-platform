#!/usr/bin/env bash
set -e

PROJECT_ID="privategpt-437907"
REGION="europe-west1"
SERVICE_NAME="eom-workspace-service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOKEN_FILE="$SCRIPT_DIR/../drive_token.json"

echo "================================================================="
echo "🚀 Deploying Artefact EOM Workspace Tool Service to Cloud Run"
echo "================================================================="
echo "Project: $PROJECT_ID"
echo "Region:  $REGION"
echo "Service: $SERVICE_NAME"

ENV_VARS="GCP_PROJECT=$PROJECT_ID"

if [ -f "$TOKEN_FILE" ]; then
  echo "🔑 Packaging local drive_token.json into Cloud Run environment..."
  TOKEN_BASE64=$(cat "$TOKEN_FILE" | base64 | tr -d '\n\r')
  ENV_VARS="$ENV_VARS,DRIVE_TOKEN_JSON=$TOKEN_BASE64"
else
  echo "⚠️  drive_token.json not found in parent directory. Cloud Run will use default Service Account credentials."
fi

gcloud run deploy "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source "$SCRIPT_DIR" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "$ENV_VARS"

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)')

echo "================================================================="
echo "✅ Cloud Run Service deployed successfully!"
echo "Service URL: $SERVICE_URL"
echo ""
echo "👉 Next: Update openapi.yaml with this URL:"
echo "servers:"
echo "  - url: $SERVICE_URL"
echo "================================================================="
