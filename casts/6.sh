#!/bin/bash
set -e

git reset --hard HEAD >/dev/null 2>&1
git checkout 8598ca47 >/dev/null 2>&1

echo -e "\n# What happens if we change an unrelated file?"
sleep 2
echo "$ vim src/python/pants/backend/python/lint/bandit/rules.py"
sleep 1
vim src/python/pants/backend/python/lint/bandit/rules.py
echo -e "\n# And then re-run our previous testcase:"
sleep 2
echo "$ ./pants test src/python/pants/backend/python/lint/isort/rules_integration_test.py -- -k test_respects_passthrough_args"
./pants test src/python/pants/backend/python/lint/isort/rules_integration_test.py -- -k test_respects_passthrough_args
sleep 1
echo -e "\n# It was cached, and didn't need to re-run!"
sleep 1
echo -e "\n# Which is great, because that means that..."
sleep 1
echo "$ ./pants list '**/*' | wc -l"
./pants list '**/*' | wc -l
sleep 1
echo -e "\n# ...we can ignore the hundreds of other files in this repository!"

git checkout -- src/python/pants/backend/python/lint/bandit/rules.py >/dev/null 2>&1
