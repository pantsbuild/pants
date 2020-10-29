#!/bin/bash
set -e

git reset --hard HEAD >/dev/null 2>&1
git checkout bd154d493 >/dev/null 2>&1

echo -e "\n# Let's import \`toml\`:"
sleep 2
echo "$ vim src/python/pants/option/parser.py"
sleep 1
vim src/python/pants/option/parser.py
echo -e "\n# And then try again..."
sleep 2
echo "$ ./pants dependencies src/python/pants/option/parser.py | grep --color -C100 'toml'"
./pants dependencies src/python/pants/option/parser.py | grep --color -C100 'toml'
sleep 2
echo -e "\n# There we go."
sleep 2

git checkout -- src/python/pants/option/parser.py >/dev/null 2>&1
