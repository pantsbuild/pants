#!/usr/bin/env bash

# We use some subshell pipelines to collect target lists, make sure target collection failing
# fails the build.
set -o pipefail

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd "$(git rev-parse --show-toplevel)" && pwd)
cd ${REPO_ROOT}

source build-support/common.sh

function usage() {
  cat <<EOF
Runs commons tests for local or hosted CI.

Usage: $0 (-h|-2fxbkmrjlpuneycitzs)
 -h           print out this help message
 -2           Run using Python 2 (defaults to using Python 3).
 -f           run python code formatting checks
 -x           run bootstrap clean-all (assume bootstrapping from a
              fresh clone)
 -b           skip bootstrapping pants from local sources
 -m           run sanity checks of bootstrapped pants and repo BUILD
              files
 -r           run doc generation tests
 -j           run core jvm tests
 -l           run internal backends python tests
 -p           run core python tests
 -u SHARD_NUMBER/TOTAL_SHARDS
              if running core python tests, divide them into
              TOTAL_SHARDS shards and just run those in SHARD_NUMBER
              to run only even tests: '-u 0/2', odd: '-u 1/2'
 -n           run contrib python tests
 -e           run rust tests
 -s           run clippy on rust code
 -a           run cargo audit of rust dependencies
 -y SHARD_NUMBER/TOTAL_SHARDS
              if running contrib python tests, divide them into
              TOTAL_SHARDS shards and just run those in SHARD_NUMBER
              to run only even tests: '-u 0/2', odd: '-u 1/2'
 -c           run pants integration tests (includes examples and testprojects)
 -i SHARD_NUMBER/TOTAL_SHARDS
              if running integration tests, divide them into
              TOTAL_SHARDS shards and just run those in SHARD_NUMBER
              to run only even tests: '-i 0/2', odd: '-i 1/2'
 -t           run lint
 -z           test platform-specific behavior
EOF
  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

# No python test sharding (1 shard) by default.
python_unit_shard="0/1"
python_contrib_shard="0/1"
python_intg_shard="0/1"
python_two="false"

while getopts "h2fxbmrjlpeasu:ny:ci:tz" opt; do
  case ${opt} in
    h) usage ;;
    2) python_two="true" ;;
    f) run_pre_commit_checks="true" ;;
    x) run_bootstrap_clean="true" ;;
    b) run_bootstrap="false" ;;
    m) run_sanity_checks="true" ;;
    r) run_docs="true" ;;
    j) run_jvm="true" ;;
    l) run_internal_backends="true" ;;
    p) run_python="true" ;;
    u) python_unit_shard=${OPTARG} ;;
    e) run_rust_tests="true" ;;
    a) run_cargo_audit="true" ;;
    s) run_rust_clippy="true" ;;
    n) run_contrib="true" ;;
    y) python_contrib_shard=${OPTARG} ;;
    c) run_integration="true" ;;
    i) python_intg_shard=${OPTARG} ;;
    t) run_lint="true" ;;
    z) test_platform_specific_behavior="true" ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done
shift $((${OPTIND} - 1))

echo
if [[ $# > 0 ]]; then
  banner "CI BEGINS: $@"
else
  banner "CI BEGINS"
fi

case "${OSTYPE}" in
  darwin*) export CXX="clang++";
           ;;
  *)       export CXX="g++";
           ;;
esac

# We're running against a Pants clone.
export PANTS_DEV=1

# Determine interpreter for both under-the-hood and for subprocesses.
# Order matters here. We must constrain subprocesses before running the bootstrap stage,
# or we will encounter the _Py_Dealloc error when running `./pants.pex -V` with Python 3 under-the-hood.
if [[ "${python_two:-false}" == "false" ]]; then
  py_version_number="3"
  pants_script="./pants3"
  export PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS='["CPython>=3.6,<4"]'
else
  py_version_number="2"
  pants_script="./pants"
fi
banner "Using Python ${py_version_number} to execute subprocesses."

if [[ "${run_bootstrap:-true}" == "true" ]]; then
  start_travis_section "Bootstrap" "Bootstrapping pants with Python ${py_version_number} under-the-hood."
  (
    if [[ "${run_bootstrap_clean:-false}" == "true" ]]; then
      ./build-support/python/clean.sh || die "Failed to clean before bootstrapping pants."
    fi
    ${pants_script} binary \
      src/python/pants/bin:pants_local_binary && \
    mv dist/pants_local_binary.pex pants.pex && \
    ./pants.pex -V
  ) || die "Failed to bootstrap pants."
  end_travis_section
fi

# We want all invocations of ./pants (apart from the bootstrapping one above) to delegate
# to ./pants.pex, and not themselves attempt to bootstrap.
# In this file we invoke ./pants.pex directly anyway, but some of those invocations will run
# integration tests that shell out to `./pants`, so we set this env var for those cases.
export RUN_PANTS_FROM_PEX=1

# TODO: Clear interpreters, otherwise this constraint does not end up applying due to a cache
# bug between the `./pants binary` and further runs.
./pants.pex clean-all

if [[ "${run_pre_commit_checks:-false}" == "true" ]]; then
  start_travis_section "PreCommit" "Running pre-commit checks"
  FULL_CHECK=1 ./build-support/bin/pre-commit.sh || exit 1
  end_travis_section
fi

if [[ "${run_sanity_checks:-false}" == "true" ]]; then
  start_travis_section "SanityCheck" "Sanity checking bootstrapped pants and repo BUILD files"
  sanity_tests=(
    "bash-completion"
    "reference"
    "clean-all"
    "goals"
    "list ::"
    "roots"
    "targets"
  )
  for cur_test in "${sanity_tests[@]}"; do
    cmd="./pants.pex ${cur_test}"
    echo "* Executing command '${cmd}' as a sanity test"
    ${cmd} >/dev/null 2>&1 || die "Failed to execute '${cmd}'."
  done
  end_travis_section
fi

if [[ "${run_lint:-false}" == "true" ]]; then
  start_travis_section "Lint" "Running lint checks"
  (
    ./pants.pex --tag=-nolint lint contrib:: examples:: src:: tests:: zinc::
  ) || die "Lint check failure"
  end_travis_section
fi

if [[ "${run_docs:-false}" == "true" ]]; then
  start_travis_section "DocGen" "Running site doc generation test"
  ./build-support/bin/publish_docs.sh || die "Failed to generate site docs."
  end_travis_section
fi

if [[ "${run_jvm:-false}" == "true" ]]; then
  start_travis_section "CoreJVM" "Running core jvm tests"
  (
    ./pants.pex doc test {src,tests}/{java,scala}:: zinc::
  ) || die "Core jvm test failure"
  end_travis_section
fi

if [[ "${run_internal_backends:-false}" == "true" ]]; then
  start_travis_section "BackendTests" "Running internal backend python tests"
  (
    ./pants.pex test.pytest \
    pants-plugins/tests/python:: -- ${PYTEST_PASSTHRU_ARGS}
  ) || die "Internal backend python test failure"
  end_travis_section
fi

if [[ "${run_python:-false}" == "true" ]]; then
  if [[ "0/1" != "${python_unit_shard}" ]]; then
    shard_desc=" [shard ${python_unit_shard}]"
  fi
  start_travis_section "CoreTests" "Running core python tests${shard_desc}"
  (
    ./pants.pex --tag='-integration' test.pytest --chroot \
      --test-pytest-test-shard=${python_unit_shard} \
      tests/python:: -- ${PYTEST_PASSTHRU_ARGS}
  ) || die "Core python test failure"
  end_travis_section
fi

if [[ "${run_contrib:-false}" == "true" ]]; then
  if [[ "0/1" != "${python_contrib_shard}" ]]; then
    shard_desc=" [shard ${python_contrib_shard}]"
  fi
  start_travis_section "ContribTests" "Running contrib python tests${shard_desc}"
  (
    ./pants.pex --exclude-target-regexp='.*/testprojects/.*' test.pytest \
    --test-pytest-test-shard=${python_contrib_shard} \
    contrib:: -- ${PYTEST_PASSTHRU_ARGS}
  ) || die "Contrib python test failure"
  end_travis_section
fi

if [[ "${run_rust_tests:-false}" == "true" ]]; then
  start_travis_section "RustTests" "Running Pants rust tests"
  (
    test_threads_flag=""
    if [[ "$(uname)" == "Darwin" ]]; then
      # The osx travis environment has a low file descriptors ulimit, so we avoid running too many
      # tests in parallel.
      test_threads_flag="--test-threads=1"
    fi

    # We pass --tests to skip doc tests, because our generated protos contain invalid doc tests in their comments.
    RUST_BACKTRACE=all "${REPO_ROOT}/build-support/bin/native/cargo" test --all --tests \
      --manifest-path="${REPO_ROOT}/src/rust/engine/Cargo.toml" -- "${test_threads_flag}" --nocapture
  ) || die "Pants rust test failure"
  end_travis_section
fi

if [[ "${run_cargo_audit:-false}" == "true" ]]; then
  start_travis_section "CargoAudit" "Running cargo audit on rust code"
  (
    "${REPO_ROOT}/build-support/bin/native/cargo" ensure-installed --package=cargo-audit --version=0.5.2
    "${REPO_ROOT}/build-support/bin/native/cargo" audit -f "${REPO_ROOT}/src/rust/engine/Cargo.lock"
  ) || die "Cargo audit failure"
fi


if [[ "${run_rust_clippy:-false}" == "true" ]]; then
  start_travis_section "RustClippy" "Running Clippy on rust code"
  (
    "${REPO_ROOT}/build-support/bin/check_clippy.sh"
  ) || die "Pants clippy failure"
fi

# NB: this only tests python tests right now -- the command needs to be edited if test targets in
# other languages are tagged with 'platform_specific_behavior' in the future.
if [[ "${test_platform_specific_behavior:-false}" == 'true' ]]; then
  start_travis_section "Platform-specific tests" \
                       "Running platform-specific testing on platform: $(uname)"
  (
    ./pants.pex --tag='+platform_specific_behavior' test \
                tests/python:: -- ${PYTEST_PASSTHRU_ARGS}
  ) || die "Pants platform-specific test failure"
  end_travis_section
fi


if [[ "${run_integration:-false}" == "true" ]]; then
  if [[ "0/1" != "${python_intg_shard}" ]]; then
    shard_desc=" [shard ${python_intg_shard}]"
  fi
  start_travis_section "IntegrationTests" "Running Pants Integration tests${shard_desc}"
  (
    ./pants.pex --tag='+integration' test.pytest \
      --test-pytest-test-shard=${python_intg_shard} \
      tests/python:: -- ${PYTEST_PASSTHRU_ARGS}
  ) || die "Pants Integration test failure"
  end_travis_section
fi

banner "CI ENDS"
echo
green "SUCCESS"
