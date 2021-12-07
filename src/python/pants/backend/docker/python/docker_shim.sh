#!/usr/bin/env bash
set -euf

img_args=
run_args=

function parse_args {
  for arg; do
    case "$arg" in
      --)
        run_args="$run_args --entrypoint \"$2\""
        shift
        shift
        img_args="$@"
        return
        ;;
      PYENV_ROOT | HOME | PATH)
        # Do not propagate these env vars into the container.
        shift
        ;;
      *)
        run_args="$run_args --env $1"
        shift
        ;;
    esac
  done
}

parse_args "$@"

exec $_DOCKER_BIN_ run --rm --volume $(pwd):/sandbox --workdir /sandbox $run_args $_DOCKER_IMAGE_ $img_args
