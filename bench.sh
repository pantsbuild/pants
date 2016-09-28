#!/bin/bash

set -e

# NB: Order matters.
BASE_COMMANDS=(
  "-ldebug goals"
  "list ::"
  "changed --changed-parent=HEAD~300"
  "minimize ::"
  "filter --type=python_binary,python_library,python_tests ::"
  "clean-all"
  "test tests/java/org/pantsbuild/tools/runner:jar"
)

EXTRA_ARGS=(
  "--no-enable-v2-engine"
  "--enable-v2-engine"
  "--config-override=pants.daemon.ini"
)

RUNS=( "1" "2" )

for extra_args in "${EXTRA_ARGS[@]}"; do
  for base_command in "${BASE_COMMANDS[@]}"; do
    for run in "${RUNS[@]}"; do
      command="./pants ${extra_args} ${base_command}"
      echo "run ${run} for: ${command}"
      { time $command > /dev/null 2>&1 ; } 2>&1
    done
  done
done
