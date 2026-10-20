.PHONY: setup test lint testdb up down seed logs
CTX=kind-ironman

setup:
	uv sync --extra dev --extra ml

lint:
	uv run ruff check src tests && uv run ruff format --check src tests

# Throwaway TimescaleDB for the test-suite on :55432
testdb:
	docker run -d --name ironman-testdb -e POSTGRES_USER=ironman -e POSTGRES_PASSWORD=ironman \
	  -e POSTGRES_DB=ironman -p 55432:5432 timescale/timescaledb:latest-pg16

test:
	uv run pytest -q

up:
	./scripts/local-up.sh

down:
	./scripts/local-down.sh

# Load synthetic demo workouts into the cluster's database and publish sanitized data
seed:
	kubectl --context $(CTX) exec deploy/private-api -- python -m ironman.demo
	kubectl --context $(CTX) create job --from=cronjob/sanitize sanitize-now-$$(date +%s)

logs:
	kubectl --context $(CTX) logs -l tier=private --tail=50 --prefix
