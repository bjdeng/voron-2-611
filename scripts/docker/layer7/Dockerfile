# Linux harness for Layer 7 macro behavior snapshots (run from macOS host).
#
# Klipper's chelper compiles against Linux kernel headers (sys/prctl.h,
# linux/can.h), so test_klippy.py cannot run on darwin. This image gives
# us a Linux Python 3.11 environment matching the CI ubuntu-22.04 job
# closely enough for `scripts/macro_behavior_diff.py` to capture
# reproducible before/after snapshots.
#
# Build:  make snapshot-image
# Run:    make snapshot-before / make snapshot-after
FROM python:3.11-slim

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Pin to the same versions the CI klippy job installs (klippy-requirements.txt
# + tests-requirements.txt at vendor/klipper pin 4767a8ed).
COPY klippy-requirements.txt tests-requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/klippy-requirements.txt -r /tmp/tests-requirements.txt

WORKDIR /work
