#!/bin/bash
set -e

git checkout bd154d493 >/dev/null 2>&1

echo -e "\n# Does the library depend on TOML?"
echo "$ ./pants dependencies src/python/pants/option/parser.py"
./pants dependencies src/python/pants/option/parser.py
sleep 2
echo -e "\n# Doesn't look like it!"
sleep 2
