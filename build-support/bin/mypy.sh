#!/usr/bin/env bash

./pants mypy --config-file=build-support/mypy/mypy.ini $@
