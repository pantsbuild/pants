#!/usr/bin/env bash

run_args=
img_args=

function parse_args {
    for arg; do
        case "$arg" in
            --)
                run_args="$run_args --entrypoint \"$2\""; shift; shift;
                img_args="$@"
                return;;
            *)
                run_args="$run_args --env "
        esac
    done
}

parse_args "$@"

exec $_DOCKER_BIN_ run --rm $docker_args $_DOCKER_IMAGE_ "$@"
