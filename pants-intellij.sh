#!/usr/bin/env bash

# A script file to generate IntelliJ project from using the Intellij Pants Plugin.
# Note: for any modification in this file please modify ExportIntegrationTest#test_intellij_integration

./pants export src/python/:: tests/python/pants_test:all contrib/:: \
    --exclude-target-regexp='.*examples.*' \
    --exclude-target-regexp='.*tests/thrift.*' \
     --exclude-target-regexp='.*tests/jvm.*'
