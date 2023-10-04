#!/usr/bin/env bash
set -eu

mkdir tmp
unzip gh.archive -d tmp || tar -xzf gh.archive -C tmp
mv tmp/* gh/
