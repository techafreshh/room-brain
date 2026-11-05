.PHONY: setup test smoke demo-up register seed-local run-demo brief

setup:
	test -d .venv || python3 -m venv .venv
	pip install -r requirements.txt

test:
	python3 -m unittest discover -s tests -v

smoke:
	python3 -m roombrain --help

demo-up:
	docker compose -f docker-compose.demo.yml up

register:
	python3 -m roombrain register

seed-local:
	python3 -m roombrain seed-demo --local

run-demo:
	python3 -m roombrain run

brief:
	python3 -m roombrain brief
