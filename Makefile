# Clearcost — common tasks. Run `make help` for the list.
MRF ?= data/mrfs

help:
	@echo "make install   install python deps (ijson)"
	@echo "make data      parse MRFs in \$$(MRF) into data/data.json"
	@echo "make build     bake data/data.json into index.html"
	@echo "make all       data + build"
	@echo "make serve     preview at http://localhost:8000"

install:
	pip install -r requirements.txt

data:
	python pipeline/ingest.py "$(MRF)" data/data.json

build:
	python build.py

all: data build

serve:
	python -m http.server 8000

.PHONY: help install data build all serve
