.PHONY: install test lint demo run docker helm-lint

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check .

demo:            ## offline demo, no cluster or LLM key needed
	PYTHONPATH=src python -m aiops_agent.demo examples/alert-oom.json
	PYTHONPATH=src python -m aiops_agent.demo examples/alert-latency.json

run:             ## local API on :8080 in demo mode
	AIOPS_DEMO=1 PYTHONPATH=src uvicorn --factory aiops_agent.app:create_app --port 8080 --reload

docker:
	docker build -t aiops-incident-agent:dev .

helm-lint:
	helm lint deploy/helm/aiops-agent
