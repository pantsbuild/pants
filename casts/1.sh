#!/bin/bash
set -e

git checkout bd154d493 >/dev/null 2>&1

echo -e "\n# The library:"
git show --oneline -- src/python/pants/option/parser.py
sleep 2
echo -e "\n# The test:"
rg -A6 'def test_respects_passthrough_args' src/python/pants/backend/python/lint/isort/rules_integration_test.py
sleep 2
echo -e "\n# Does it pass?"
sleep 2
echo "$ ./pants test src/python/pants/backend/python/lint/isort/rules_integration_test.py -- -k test_respects_passthrough_args"
./pants test src/python/pants/backend/python/lint/isort/rules_integration_test.py -- -k test_respects_passthrough_args || true
echo -e "\n# Not yet!"
sleep 2
