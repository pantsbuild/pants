#!/usr/bin/env bash
set -e
./pants test tests/python/pants_test:: --tag=-integration
