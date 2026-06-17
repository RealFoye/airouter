.PHONY: dev web test-unit test-integration test-cli test-all lint smoke install clean

install:
	pip install -e ".[dev]"

dev:
	uvicorn airouter.api.main:app --reload --host 0.0.0.0 --port 8000

web:
	streamlit run web/app.py --server.address 127.0.0.1 --server.port 8501

test-unit:
	pytest tests/unit/ -v --cov=src/airouter --cov-report=term-missing

test-integration:
	@if ls tests/integration/test_*.py 1>/dev/null 2>&1; then \
		pytest tests/integration/ -v; \
	else \
		echo "No integration tests yet, skipping."; \
	fi

test-cli:
	@if [ -f tests/integration/test_cli.py ]; then \
		pytest tests/integration/test_cli.py -v; \
	else \
		echo "No CLI tests yet, skipping."; \
	fi

test-all: lint test-unit test-integration

lint:
	ruff check src/ tests/
	mypy src/

smoke:
	docker-compose up --build

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov dist *.egg-info
