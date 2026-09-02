.PHONY: help install install-dev index run test lint format ci docker-build docker-run docker-verify docker-size jenkins-up jenkins-down jenkins-password clean

help:
	@echo "install       Install runtime dependencies"
	@echo "install-dev   Install runtime + dev dependencies"
	@echo "index         Build the FAISS vector index from data/*.pdf"
	@echo "run           Start the Gradio app locally"
	@echo "test          Run the pytest suite"
	@echo "lint          Run ruff"
	@echo "format        Format with black + ruff --fix"
	@echo "docker-build  Build the container image"
	@echo "docker-run    Run the container locally on :8080"
	@echo "docker-verify Staged checks on the built image"

install:
	pip install --upgrade pip && pip install -r requirements.txt

install-dev:
	pip install --upgrade pip && pip install -r requirements-dev.txt

index:
	python -m app.ingestion.build_index --force

run:
	python -m app.main

test:
	pytest -v --cov=app --cov-report=term-missing

lint:
	ruff check app tests scripts

format:
	black app tests scripts && ruff check --fix app tests scripts

docker-build:
	docker build -t medical-ai-rag-system:latest .

docker-run:
	docker run --rm -p 8080:8080 --env-file .env medical-ai-rag-system:latest

docker-verify:
	bash scripts/verify_docker.sh medical-ai-rag-system:latest

docker-size:
	docker image inspect medical-ai-rag-system:latest --format '{{.Size}}' | awk '{printf "image size: %.0f MB\n", $$1/1048576}'

jenkins-up:
	cd deploy/jenkins && docker compose up -d --build

jenkins-down:
	cd deploy/jenkins && docker compose down

jenkins-password:
	docker exec medical-rag-jenkins cat /var/jenkins_home/secrets/initialAdminPassword

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov

# Mirror the CI 'quality' job exactly, so failures surface locally not on GitHub.
ci:
	ruff check app tests scripts
	pytest -q --cov=app --cov-report=term-missing
	python scripts/preflight_git.py
