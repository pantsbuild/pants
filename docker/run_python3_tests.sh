#!/bin/bash

export PYTHONPATH=""
export PYTEST_TIMEOUT=0
export TIME=${TIME:-$(date +%Y-%m-%d:%H:%M:%S)}

trap clean_up INT

function clean_docker() {
    echo "Kill any leftover docker processes..."
    ps | grep docker | cut -f 1 -d " " | xargs kill -9
    echo "Done"
}

function clean_up() {
    clean_docker
}

function run_tests() {
    targets=$1

    if [[ "$ONE_BY_ONE" == "true" ]]; then
        name="$(echo $targets | sed -e 's/\//\./g')"
    else
        name="tests.all"
    fi

    name="${name}.${TIME}.py${PY}"

    if [[ "$_IN_DOCKER" == "true" ]]; then
        outfile="/results/${name}.docker"
    else
        outfile="$(pwd)/docker/${name}.local"
        ./pants clean-all > /dev/null;
    fi

    echo "Running tests... (In docker: ${_IN_DOCKER:-false} | With python ${PY} ${PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS} | With T=${TIME})"
    time ./pants --tag='-integration' test.pytest --chroot $targets -- --timeout=0 --verbose  > "${outfile}.out" 2> "${outfile}.err"
}

if  [[ "${_IN_DOCKER:-false}" == "true" ]]; then
    echo "In Docker..."
fi

echo "Run T=${TIME}"
if [[ "$DOCKERIZE" == "true" ]]; then
    echo "Build docker image..."
    docker build . -t pants:latest > /dev/null;
    echo "done."
    docker run --rm -e "ONE_BY_ONE=$ONE_BY_ONE" -e "PY=$PY" -e "_IN_DOCKER=true" -e "TIME=$TIME" -v $(pwd):/results pants:latest
else
    PY=${PY:-3}
    if [[ "$PY" == "3"  ]]; then
        export PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS='["CPython>=3.4,<4"]'
    else
        export PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS='["CPython>=2.6,<3"]'
    fi

    if  [[ "${_IN_DOCKER:-false}" == "false" ]]; then
        cd ..
    fi
    echo "Collecting unit tests..."

    if [[ "$RUN_ALL" == "true" ]]; then
        targets="$(comm -23 <(./pants --tag='-integration' list tests/python:: | grep '.' | sort) <(sort build-support/known_py3_failures.txt))"
        echo "Found $(echo $targets | wc -w) targets"

        run_tests $targets
    else
        echo "Running known bad..."
        targets=$(cat build-support/known_py3_failures.txt)

        if [[ "$ONE_BY_ONE" == "true" ]]; then
            echo "Running one by one..."
            for target in $targets
            do
                echo "Running tests for target: ${target}..."
                run_tests $target
            done
        else
            run_tests "$targets"
        fi
    fi
    echo "done..."
fi

if  [[ "${_IN_DOCKER:-false}" == "false" ]]; then
    echo "Failing targets:"
    grep FAILED tests*${TIME}*
fi
