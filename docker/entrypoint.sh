#!/bin/bash

export PYTEST_TIMEOUT=0
py=${py:-2}

echo "Starting tests for: $target (python $py)"

if [[ "$py" == "3" ]]; then
    export PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS='["CPython>=3.4,<4"]'
fi

outfile="/results/$(echo $target | sed -e 's/\//\./g').py${py}"

./pants --tag='-integration' test.pytest --chroot $target -- --timeout=0 --verbose > "${outfile}.out" 2> "${outfile}.err"

echo "$target: Done"
