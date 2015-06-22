#!/usr/bin/env bash

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd "$(git rev-parse --show-toplevel)" && pwd)
cd ${REPO_ROOT}

source build-support/common.sh

function usage() {
  echo "Runs commons tests for local or hosted CI."
  echo
  echo "Usage: $0 (-h|-fxbkmsrjlpuncia)"
  echo " -h           print out this help message"
  echo " -f           skip python code formatting checks"
  echo " -x           skip bootstrap clean-all (assume bootstrapping from a"
  echo "              fresh clone)"
  echo " -b           skip bootstraping pants from local sources"
  echo " -k           skip bootstrapped pants self compile check"
  echo " -m           skip sanity checks of bootstrapped pants and repo BUILD"
  echo "              files"
  echo " -s           skip self-distribution tests"
  echo " -r           skip doc generation tests"
  echo " -j           skip core jvm tests"
  echo " -l           skip internal backends python tests"
  echo " -p           skip core python tests"
  echo " -u SHARD_NUMBER/TOTAL_SHARDS"
  echo "              if running core python tests, divide them into"
  echo "              TOTAL_SHARDS shards and just run those in SHARD_NUMBER"
  echo "              to run only even tests: '-u 0/2', odd: '-u 1/2'"
  echo " -n           skip contrib python tests"
  echo " -c           skip pants integration tests (includes examples and testprojects)"
  echo " -i SHARD_NUMBER/TOTAL_SHARDS"
  echo "              if running integration tests, divide them into"
  echo "              TOTAL_SHARDS shards and just run those in SHARD_NUMBER"
  echo "              to run only even tests: '-i 0/2', odd: '-i 1/2'"
  echo " -a           skip android targets when running tests"
  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

bootstrap_compile_args=(
  compile.python-eval
  --closure
  --fail-slow
)

# No python test sharding (1 shard) by default.
python_unit_shard="0/1"
python_intg_shard="0/1"

while getopts "hfxbkmsrjlpu:nci:a" opt; do
  case ${opt} in
    h) usage ;;
    f) skip_pre_commit_checks="true" ;;
    x) skip_bootstrap_clean="true" ;;
    b) skip_bootstrap="true" ;;
    k) bootstrap_compile_args=() ;;
    m) skip_sanity_checks="true" ;;
    s) skip_distribution="true" ;;
    r) skip_docs="true" ;;
    j) skip_jvm="true" ;;
    l) skip_internal_backends="true" ;;
    p) skip_python="true" ;;
    u) python_unit_shard=${OPTARG} ;;
    n) skip_contrib="true" ;;
    c) skip_integration="true" ;;
    i) python_intg_shard=${OPTARG} ;;
    a) skip_android="true" ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done
shift $((${OPTIND} - 1))

# Android testing requires the SDK to be installed and configured in Pants.
# Skip if ANDROID_HOME isn't configured in the environment
if [[ -z "${ANDROID_HOME}"  || "${skip_android:-false}" == "true" ]] ; then
  export SKIP_ANDROID="true"
else
  export SKIP_ANDROID="false"
fi

if [[ $# > 0 ]]; then
  banner "CI BEGINS: $@"
else
  banner "CI BEGINS"
fi

if [[ "${skip_pre_commit_checks:-false}" == "false" ]]; then
  banner "Running pre-commit checks"

  ./build-support/bin/pre-commit.sh || exit 1
fi

# TODO(John sirois): Re-plumb build such that it grabs constraints from the built python_binary
# target(s).
INTERPRETER_CONSTRAINTS=(
  "CPython>=2.7,<3"
)
for constraint in ${INTERPRETER_CONSTRAINTS[@]}; do
  INTERPRETER_ARGS=(
    ${INTERPRETER_ARGS[@]}
    --interpreter="${constraint}"
  )
done

PANTS_ARGS=(
  "${INTERPRETER_ARGS[@]}"
)


if [[ "${skip_bootstrap:-false}" == "false" ]]; then
  banner "Bootstrapping pants"
  (
    if [[ "${skip_bootstrap_clean:-false}" == "false" ]]; then
      ./build-support/python/clean.sh || die "Failed to clean before bootstrapping pants."
    fi
    ./pants ${PANTS_ARGS[@]} ${bootstrap_compile_args[@]} binary \
      src/python/pants/bin:pants_local_binary && \
    mv dist/pants_local_binary.pex pants.pex && \
    ./pants.pex --version
  ) || die "Failed to bootstrap pants."
fi

if [[ "${skip_sanity_checks:-false}" == "false" ]]; then
  banner "Sanity checking bootstrapped pants and repo BUILD files"
  ./pants.pex ${PANTS_ARGS[@]} clean-all || die "Failed to clean-all."
  ./pants.pex ${PANTS_ARGS[@]} goals || die "Failed to list goals."
  ./pants.pex ${PANTS_ARGS[@]} list :: || die "Failed to list all targets."
  ./pants.pex ${PANTS_ARGS[@]} targets || die "Failed to show target help."
fi

if [[ "${skip_distribution:-false}" == "false" ]]; then
  banner "Running pants distribution tests"
  (
    ./build-support/bin/release.sh -n
  ) || die "Failed to create pants distributions."
fi

if [[ "${skip_docs:-false}" == "false" ]]; then
  banner "Running site doc generation test"
  ./build-support/bin/publish_docs.sh || die "Failed to generate site docs."
fi

if [[ "${skip_jvm:-false}" == "false" ]]; then
  banner "Running core jvm tests"
  (
    ./pants.pex ${PANTS_ARGS[@]} test tests/java:: src/{java,scala}:: zinc::
  ) || die "Core jvm test failure"
fi

if [[ "${skip_internal_backends:-false}" == "false" ]]; then
  banner "Running internal backend python tests"
  (
    ./pants.pex ${PANTS_ARGS[@]} test.pytest \
      --fail-slow \
        $(./pants.pex list pants-plugins/tests/python:: | \
            xargs ./pants.pex filter --filter-type=python_tests)
  ) || die "Internal backend python test failure"
fi

if [[ "${skip_python:-false}" == "false" ]]; then
  if [[ "0/1" != "${python_unit_shard}" ]]; then
    shard_desc=" [shard ${python_unit_shard}]"
  fi
  banner "Running core python tests${shard_desc}"
  (
    ./pants.pex ${PANTS_ARGS[@]} test.pytest \
      --fail-slow \
      --coverage=paths:pants/ \
      --shard=${python_unit_shard} \
        $(./pants.pex list tests/python:: | \
            xargs ./pants.pex filter --filter-type=python_tests | \
            grep -v integration)
  ) || die "Core python test failure"
fi

if [[ "${skip_contrib:-false}" == "false" ]]; then
  banner "Running contrib python tests"
  (
    # We run python tests using --no-fast - aka test chroot per target - to work around issues with
    # test (ie: pants_test.contrib) namespace packages.
    # TODO(John Sirois): Get to the bottom of the issue and kill --no-fast, see:
    #  https://github.com/pantsbuild/pants/issues/1149
    ./pants.pex ${PANTS_ARGS[@]} test.pytest --fail-slow --no-fast contrib::
  ) || die "Contrib python test failure"
fi

if [[ "${skip_integration:-false}" == "false" ]]; then
  if [[ "0/1" != "${python_intg_shard}" ]]; then
    shard_desc=" [shard ${python_intg_shard}]"
  fi
  banner "Running Pants Integration tests${shard_desc}"
  (
    ./pants.pex ${PANTS_ARGS[@]} test.pytest --fail-slow --shard=${python_intg_shard} \
      $(./pants.pex list tests/python:: | \
          xargs ./pants.pex filter --filter-type=python_tests | \
          grep integration)
  ) || die "Pants Integration test failure"
fi

banner "CI SUCCESS"
