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

Usage: $0 (-h|-fxbkmsrjlpuyncia)
 -h           print out this help message
 -f           skip python code formatting checks
 -x           skip bootstrap clean-all (assume bootstrapping from a
              fresh clone)
 -b           skip bootstrapping pants from local sources
 -k           skip bootstrapped pants self compile check
 -m           skip sanity checks of bootstrapped pants and repo BUILD
              files
 -r           skip doc generation tests
 -j           skip core jvm tests
 -l           skip internal backends python tests
 -p           skip core python tests
 -u SHARD_NUMBER/TOTAL_SHARDS
              if running core python tests, divide them into
              TOTAL_SHARDS shards and just run those in SHARD_NUMBER
              to run only even tests: '-u 0/2', odd: '-u 1/2'
 -n           skip contrib python tests
 -e           skip rust tests
 -y SHARD_NUMBER/TOTAL_SHARDS
              if running contrib python tests, divide them into
              TOTAL_SHARDS shards and just run those in SHARD_NUMBER
              to run only even tests: '-u 0/2', odd: '-u 1/2'
 -c           skip pants integration tests (includes examples and testprojects)
 -i SHARD_NUMBER/TOTAL_SHARDS
              if running integration tests, divide them into
              TOTAL_SHARDS shards and just run those in SHARD_NUMBER
              to run only even tests: '-i 0/2', odd: '-i 1/2'
 -t           skip lint
 -z           test platform-specific behavior
EOF
  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

bootstrap_compile_args=(
  lint.python-eval
  --transitive
)

# No python test sharding (1 shard) by default.
python_unit_shard="0/1"
python_contrib_shard="0/1"
python_intg_shard="0/1"

while getopts "hfxbkmrjlpeu:ny:ci:tz" opt; do
  case ${opt} in
    h) usage ;;
    f) skip_pre_commit_checks="true" ;;
    x) skip_bootstrap_clean="true" ;;
    b) skip_bootstrap="true" ;;
    k) bootstrap_compile_args=() ;;
    m) skip_sanity_checks="true" ;;
    r) skip_docs="true" ;;
    j) skip_jvm="true" ;;
    l) skip_internal_backends="true" ;;
    p) skip_python="true" ;;
    u) python_unit_shard=${OPTARG} ;;
    e) skip_rust_tests="true" ;;
    n) skip_contrib="true" ;;
    y) python_contrib_shard=${OPTARG} ;;
    c) skip_integration="true" ;;
    i) python_intg_shard=${OPTARG} ;;
    t) skip_lint="true" ;;
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

if [[ "${skip_pre_commit_checks:-false}" == "false" ]]; then
  start_travis_section "PreCommit" "Running pre-commit checks"
  FULL_CHECK=1 ./build-support/bin/pre-commit.sh || exit 1
  end_travis_section
fi

if [[ "${skip_bootstrap:-false}" == "false" ]]; then
  start_travis_section "Bootstrap" "Bootstrapping pants"
  (
    if [[ "${skip_bootstrap_clean:-false}" == "false" ]]; then
      ./build-support/python/clean.sh || die "Failed to clean before bootstrapping pants."
    fi
    ./pants ${bootstrap_compile_args[@]} binary \
      src/python/pants/bin:pants_local_binary && \
    mv dist/pants_local_binary.pex pants.pex && \
    ./pants.pex -V
  ) || die "Failed to bootstrap pants."
  end_travis_section
fi

if [[ "${skip_sanity_checks:-false}" == "false" ]]; then
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

if [[ "${skip_lint:-false}" == "false" ]]; then
  start_travis_section "Lint" "Running lint checks"
  (
    ./pants.pex --tag=-nolint lint contrib:: examples:: src:: tests:: zinc::
  ) || die "Lint check failure"
  end_travis_section
fi

if [[ "${skip_docs:-false}" == "false" ]]; then
  start_travis_section "DocGen" "Running site doc generation test"
  ./build-support/bin/publish_docs.sh || die "Failed to generate site docs."
  end_travis_section
fi

if [[ "${skip_jvm:-false}" == "false" ]]; then
  start_travis_section "CoreJVM" "Running core jvm tests"
  (
    ./pants.pex doc test {src,tests}/{java,scala}:: zinc::
  ) || die "Core jvm test failure"
  end_travis_section
fi

if [[ "${skip_internal_backends:-false}" == "false" ]]; then
  start_travis_section "BackendTests" "Running internal backend python tests"
  (
    ./pants.pex test.pytest \
    pants-plugins/tests/python:: -- ${PYTEST_PASSTHRU_ARGS}
  ) || die "Internal backend python test failure"
  end_travis_section
fi

if [[ "${skip_python:-false}" == "false" ]]; then
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

if [[ "${skip_contrib:-false}" == "false" ]]; then
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

if [[ "${skip_rust_tests:-false}" == "false" ]]; then
  start_travis_section "RustTests" "Running Pants rust tests"
  (
    test_threads_flag=""
    if [[ "$(uname)" == "Darwin" ]]; then
      # The osx travis environment has a low file descriptors ulimit, so we avoid running too many
      # tests in parallel.
      test_threads_flag="--test-threads=1"
    fi

    RUST_BACKTRACE=all "${REPO_ROOT}/build-support/bin/native/cargo" test --all \
      --manifest-path="${REPO_ROOT}/src/rust/engine/Cargo.toml" -- "${test_threads_flag}" --nocapture
  ) || die "Pants rust test failure"
  end_travis_section
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


if [[ "${skip_integration:-false}" == "false" ]]; then
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
