#!/usr/bin/env bash
# Remove only the "ironman" kind cluster (other clusters are untouched).
set -euo pipefail
kind delete cluster --name ironman
