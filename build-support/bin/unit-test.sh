#!/usr/bin/env bash
set -e
./pants test src/python/pants:: tests/python/pants_test:: --tag=-integration
