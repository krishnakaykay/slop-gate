#!/usr/bin/env bash
# Deploy Slop Gate to Google Cloud Run (single-instance beta mode with sponsored Gemini key).
#
# Prerequisites:
#   gcloud auth login
#   gcloud config set project <YOUR_GCP_PROJECT_ID>
#
# Usage:
#   GEMINI_API_KEY="AIza..." \
#   SLOP_BETA_CODE="my-invite-code" \
#   SLOP_ADMIN_TOKEN="my-admin-secret" \
#   ./deploy_cloudrun.sh

set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-slop-gate}"
REGION="${REGION:-us-central1}"
DAILY_LIMIT="${SLOP_DAILY_RUN_LIMIT_PER_IP:-15}"

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "Error: GEMINI_API_KEY must be set in your environment to sponsor live beta runs."
  echo "Example:"
  echo '  GEMINI_API_KEY="AIza..." SLOP_BETA_CODE="beta2026" SLOP_ADMIN_TOKEN="secret" ./deploy_cloudrun.sh'
  exit 1
fi

ENV_VARS="GEMINI_API_KEY=${GEMINI_API_KEY},SLOP_DAILY_RUN_LIMIT_PER_IP=${DAILY_LIMIT},SLOP_JSON_LOGS=true"
if [[ -n "${SLOP_BETA_CODE:-}" ]]; then
  ENV_VARS="${ENV_VARS},SLOP_BETA_CODE=${SLOP_BETA_CODE}"
fi
if [[ -n "${SLOP_ADMIN_TOKEN:-}" ]]; then
  ENV_VARS="${ENV_VARS},SLOP_ADMIN_TOKEN=${SLOP_ADMIN_TOKEN}"
fi

echo "Deploying ${SERVICE_NAME} to Cloud Run (${REGION})..."
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --concurrency 20 \
  --min-instances 0 \
  --max-instances 1 \
  --set-env-vars "${ENV_VARS}"

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --region "${REGION}" --format 'value(status.url)')"
echo ""
echo "Deployed cleanly: ${SERVICE_URL}"
echo ""
echo "Useful Google Cloud Logging (Logs Explorer) queries:"
echo "  User feedback:  resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${SERVICE_NAME}\" jsonPayload.event=\"user_feedback\""
echo "  All errors:     resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${SERVICE_NAME}\" severity>=ERROR"
echo "  Funnel events:  resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${SERVICE_NAME}\" jsonPayload.event!=\"\""
if [[ -n "${SLOP_ADMIN_TOKEN:-}" ]]; then
  echo ""
  echo "Live in-instance telemetry summary:"
  echo "  curl -H \"X-Admin-Token: <YOUR_ADMIN_TOKEN>\" \"${SERVICE_URL}/api/admin/telemetry\""
fi
