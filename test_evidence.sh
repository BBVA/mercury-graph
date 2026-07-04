#!/bin/bash

coverage run --omit '/usr/lib/*' -m pytest unit_tests/evidence/

coverage report -m
