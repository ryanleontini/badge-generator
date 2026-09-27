# Run from the repo root. Override the Blender binary with: make BLENDER=/path/to/blender
BLENDER ?= blender
RUN = $(BLENDER) --background --factory-startup --quiet --python-exit-code 1 --python

.PHONY: front rear text test unit smoke check clean

front:
	$(RUN) badge_gen.py -- --config configs/front.toml

rear:
	$(RUN) badge_gen.py -- --config configs/rear.toml

text:
	$(RUN) badge_gen.py -- --config configs/example_text.toml
	$(RUN) tests/stl_check.py -- out/*.stl

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

clean:
	rm -rf out
