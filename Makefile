.PHONY: setup test smoke

setup:
	test -d .venv || python3 -m venv .venv
	pip install -r requirements.txt

test:
	python3 -m unittest discover -s tests -v

smoke:
	python3 -m roombrain --help
