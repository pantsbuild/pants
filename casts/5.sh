#!/bin/bash
set -e

git reset --hard HEAD >/dev/null 2>&1
git checkout bf63445099 >/dev/null 2>&1

echo -e "\n# Use some first party helper code to produce TOML in the test:"
sleep 2
echo "$ git apply changes/produce-toml.diff"
git apply changes/produce-toml.diff
sleep 1
echo "$ git diff"
git diff
sleep 2
echo -e "\n# And try re-running our test..."
sleep 2
echo "$ ./pants test src/python/pants/backend/python/lint/isort/rules_integration_test.py -- -k test_respects_passthrough_args"
./pants test src/python/pants/backend/python/lint/isort/rules_integration_test.py -- -k test_respects_passthrough_args
sleep 1
echo -e "\n# It passes!"
sleep 2

git checkout -- src/python/pants/backend/python/lint/isort/rules_integration_test.py >/dev/null 2>&1
