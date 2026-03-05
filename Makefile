.PHONY: start api cli test

start:
	./start.sh

api:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

cli:
	python -m cli.main

test:
	pytest
