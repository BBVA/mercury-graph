#!/bin/bash

coverage run --omit '/usr/lib/*' -m pytest unit_tests/evidence/

coverage report -m --omit="mercury/graph/core/*,mercury/graph/ml/*,mercury/graph/viz/*,mercury/graph/embeddings/*,mercury/graph/__init__.py,mercury/graph/create_tutorials.py,unit_tests/conftest.py"
