.PHONY: install test lint eval run tf-check

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check .

eval:            ## LLMOps gate, offline baseline (set RAG_MODE=azure ... or use --api-url for real runs)
	python evals/run_eval.py

run:             ## local API on :8080, offline mode
	RAG_MODE=local PYTHONPATH=app uvicorn --factory rag.api:create_app --port 8080 --reload

tf-check:
	terraform -chdir=infra fmt -check -recursive
	terraform -chdir=infra init -backend=false
	terraform -chdir=infra validate
