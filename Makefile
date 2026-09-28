# Run from the repo root. Override the Blender binary with: make BLENDER=/path/to/blender
BLENDER ?= blender
RUN = $(BLENDER) --background --factory-startup --quiet --python-exit-code 1 --python

.PHONY: all front rear text web test unit smoke check docs clean

all: front rear text

front:
	$(RUN) badge_gen.py -- --config configs/front.toml

rear:
	$(RUN) badge_gen.py -- --config configs/rear.toml

text:
	$(RUN) badge_gen.py -- --config configs/example_text.toml

# Local web UI at http://127.0.0.1:8000 (Python standard library only).
web:
	python3 web/server.py

test: unit smoke

unit:
	$(RUN) tests/run_tests.py

smoke:
	$(RUN) badge_gen.py
	$(RUN) badge_gen.py -- --config configs/front.toml
	$(RUN) badge_gen.py -- --config configs/rear.toml
	$(RUN) badge_gen.py -- --config configs/example_text.toml
	$(RUN) tests/stl_check.py -- out/*.stl

check:
	$(RUN) tests/stl_check.py -- out/*.stl

# Refresh the README screenshots from the shipped configs.
docs: all
	mkdir -p docs/images
	cp out/front_preview.png out/rear_preview.png out/example_text_preview.png docs/images/

clean:
	rm -rf out
