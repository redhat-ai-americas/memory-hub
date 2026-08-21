#!/bin/bash
set -e
python seed-memories.py
exec python harness.py
