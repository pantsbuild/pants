#!/bin/bash
set -e

git reset --hard HEAD >/dev/null 2>&1
git checkout 52949ccf1 >/dev/null 2>&1

echo -e "\n# Now let's actually use TOML to implement the feature in the library:"
sleep 2
echo "$ git apply --verbose changes/parse-with-toml.diff"
git apply --verbose changes/parse-with-toml.diff
echo -e "\n# And try re-running our test..."
sleep 2
echo "$ ./pants test src/python/pants/backend/python/lint/isort/rules_integration_test.py -- -k test_respects_passthrough_args"
./pants test src/python/pants/backend/python/lint/isort/rules_integration_test.py -- -k test_respects_passthrough_args || true
sleep 2
echo -e "\n# A TomlDecode error! Not there yet, but we're making progress."
sleep 2

git checkout -- src/python/pants/option/parser.py  >/dev/null 2>&1
