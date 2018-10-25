#!/bin/bash

export PYTHONPATH=""
export PYTEST_TIMEOUT=0

trap clean_up INT

function clean_docker() {
    echo "Kill any leftover docker processes..."
    ps | grep docker | cut -f 1 -d " " | xargs kill -9
    echo "Done"
}

function clean_up() {
    clean_docker
}

PY=${$PY:-2}
if [[ "$PY" == "3"  ]]; then
    export PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS='["CPython>=3.4,<4"]'
fi

if [[ "$RUN_ALL" == "true" ]]; then
    echo "Collecting unit tests..."
    targets="$(comm -23 <(./pants --tag='-integration' list tests/python:: | grep '.' | sort) <(sort build-support/known_py3_failures.txt))"

    echo "Found $(echo $targets | wc -w) targets"
    ./pants --tag='-integration' test.pytest --chroot $targets
else
    echo "Running known bad..."
    targets=$(cat ../build-support/known_py3_failures.txt)

    if [[ "$ONE_BY_ONE" == "true" ]]; then
        echo "Running one by one..."
        for target in $targets
        do
            echo "Running tests for target: ${target}..."
            time docker run --rm -e "target=$target" -e "py=$PY" -v $(pwd):/results pants:latest
        done
        echo "done..."
        echo "Failing targets:"
    else
        pushd ..
        ./pants --tag='-integration' test.pytest --chroot $targets -- --verbose > tests.all.out 2> tests.all.err
        popd
    fi
    rg FAILED tests*
fi
