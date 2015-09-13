#!/usr/bin/env bash

# A script file to generate IntelliJ project from using the Intellij Pants Plugin.
# Note: for any modification in this file please modify ExportIntegrationTest#test_intellij_integration

# We don't want to include targets which are used in unit tests in our project so let's exclude them.
./pants export src/python/:: tests/python/pants_test:all contrib/:: \
    --exclude-target-regexp='.*go/examples.*' \
    --exclude-target-regexp='.*scrooge/tests/thrift.*' \
    --exclude-target-regexp='.*spindle/tests/thrift.*' \
    --exclude-target-regexp='.*spindle/tests/jvm.*'
