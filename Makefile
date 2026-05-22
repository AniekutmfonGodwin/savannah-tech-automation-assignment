.PHONY: help api-up api-down api-restart api-logs api-wait test smoke contract security fuzz load load-locust inspect lint clean

help:
	@echo "Common targets:"
	@echo "  make api-up       Start the API container (detached)"
	@echo "  make api-down     Stop and remove the API container"
	@echo "  make api-restart  Restart the API to clear its in-memory store"
	@echo "  make api-logs     Tail the API container logs"
	@echo "  make api-wait     Block until /swagger/doc.json is reachable"
	@echo "  make test         Run full pytest suite via Docker Compose (default)"
	@echo "  make smoke        Run only @pytest.mark.smoke (fast PR gate)"
	@echo "  make contract     Run only contract tests"
	@echo "  make security     Run pen-test / security suite (-m security)"
	@echo "  make fuzz         Run schemathesis property-based contract fuzz"
	@echo "  make load         Run pytest load suite (1000 RPM + write-heavy)"
	@echo "  make load-locust  Launch Locust mixed-tenant scenario"
	@echo "  make inspect      Inspect the API Docker image / binary"
	@echo "  make lint         Run ruff + mypy"
	@echo "  make clean        Remove reports and pytest caches"

api-up:
	docker compose up -d api
	$(MAKE) api-wait

api-down:
	docker compose down --remove-orphans

api-restart:
	docker compose restart api
	$(MAKE) api-wait

api-logs:
	docker compose logs -f api

api-wait:
	@echo "Waiting for API at $${FIREFLY_BASE_URL:-http://localhost:8080}/swagger/doc.json ..."
	@for i in $$(seq 1 30); do \
		if curl -sf $${FIREFLY_BASE_URL:-http://localhost:8080}/swagger/doc.json -o /dev/null; then \
			echo "API ready."; exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "API did not become ready within 30s." >&2; exit 1

test:
	./scripts/run_tests.sh

smoke:
	pytest -m smoke --html=reports/smoke.html --self-contained-html

contract:
	pytest -m contract --html=reports/contract.html --self-contained-html

security:
	pytest -m security --html=reports/security.html --self-contained-html

fuzz:
	pip install -e .[fuzz]
	pytest -m schemathesis --html=reports/fuzz.html --self-contained-html

load:
	pytest -m load --html=reports/load.html --self-contained-html

load-locust:
	pip install -e .[load]
	mkdir -p reports
	locust -f locustfile.py --headless -u 50 -r 10 -t 2m \
		--host $${FIREFLY_BASE_URL:-http://localhost:8080} \
		--html reports/locust.html --csv reports/locust

inspect:
	./scripts/inspect_image.sh

lint:
	pip install -e .[dev]
	ruff check src tests
	mypy src

clean:
	rm -rf reports/*
	rm -rf .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
