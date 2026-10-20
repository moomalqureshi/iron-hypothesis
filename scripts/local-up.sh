#!/usr/bin/env bash
# Create (or reuse) a local kind cluster named "ironman", build and load images, and install the chart.
set -euo pipefail
cd "$(dirname "$0")/.."
CLUSTER=ironman
CTX=kind-$CLUSTER
K="kubectl --context $CTX"

for t in docker kind kubectl helm; do
  command -v "$t" >/dev/null || { echo "missing required tool: $t" >&2; exit 1; }
done

if ! kind get clusters | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER" --config scripts/kind-config.yaml
fi

if ! $K get ns ingress-nginx >/dev/null 2>&1; then
  $K apply -f https://kind.sigs.k8s.io/examples/ingress/deploy-ingress-nginx.yaml
fi
$K -n ingress-nginx rollout status deploy/ingress-nginx-controller --timeout=180s

docker build -t ironman:local .
docker build -t ironman-web:local web
kind load docker-image ironman:local ironman-web:local --name "$CLUSTER"

# Credentials live only in the cluster Secret. Generated once; Strava/LLM values come from .env.
if ! $K get secret ironman-secrets >/dev/null 2>&1; then
  # shellcheck source=/dev/null
  [ -f .env ] && set -a && . ./.env && set +a
  rnd() { head -c 32 /dev/urandom | base64 | tr -d '/+=\n' | head -c 40; }
  $K create secret generic ironman-secrets \
    --from-literal=POSTGRES_PASSWORD="$(rnd)" \
    --from-literal=POSTGRES_PUBLIC_PASSWORD="$(rnd)" \
    --from-literal=IRONMAN_SECRET_KEY="$(rnd)" \
    --from-literal=IRONMAN_PSEUDONYM_KEY="$(rnd)" \
    --from-literal=IRONMAN_STRAVA_VERIFY_TOKEN="$(rnd)" \
    --from-literal=IRONMAN_STRAVA_CLIENT_ID="${IRONMAN_STRAVA_CLIENT_ID:-}" \
    --from-literal=IRONMAN_STRAVA_CLIENT_SECRET="${IRONMAN_STRAVA_CLIENT_SECRET:-}" \
    --from-literal=IRONMAN_LLM_API_KEY="${IRONMAN_LLM_API_KEY:-}"
fi

helm --kube-context "$CTX" upgrade --install ironman charts/ironman --wait --timeout 5m
# The image tag is constant, so restart workloads to pick up a rebuilt image.
$K rollout restart deploy/private-api deploy/public-api deploy/sync-worker deploy/web
$K rollout status deploy/private-api deploy/public-api deploy/sync-worker deploy/web --timeout=180s
echo
echo "Ready: http://localhost:8080  (owner)   http://localhost:8080/public.html?demo=1  (demo)"
