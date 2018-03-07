#!/usr/bin/env bash

# We use some subshell pipelines to collect target lists, make sure target collection failing
# fails the build.
set -o pipefail

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd "$(git rev-parse --show-toplevel)" && pwd)
cd ${REPO_ROOT}

source build-support/common.sh

function usage() {
  echo "Runs commons tests for local or hosted CI."
  echo
  echo "Usage: $0 (-h|-fxbkmsrjlpuyncia)"
  echo " -h           print out this help message"
  echo " -f           skip python code formatting checks"
  echo " -x           skip bootstrap clean-all (assume bootstrapping from a"
  echo "              fresh clone)"
  echo " -b           skip bootstraping pants from local sources"
  echo " -k           skip bootstrapped pants self compile check"
  echo " -m           skip sanity checks of bootstrapped pants and repo BUILD"
  echo "              files"
  echo " -r           skip doc generation tests"
  echo " -j           skip core jvm tests"
  echo " -l           skip internal backends python tests"
  echo " -p           skip core python tests"
  echo " -u SHARD_NUMBER/TOTAL_SHARDS"
  echo "              if running core python tests, divide them into"
  echo "              TOTAL_SHARDS shards and just run those in SHARD_NUMBER"
  echo "              to run only even tests: '-u 0/2', odd: '-u 1/2'"
  echo " -a           skip android targets when running tests"
  echo " -n           skip contrib python tests"
  echo " -e           skip rust tests"
  echo " -y SHARD_NUMBER/TOTAL_SHARDS"
  echo "              if running contrib python tests, divide them into"
  echo "              TOTAL_SHARDS shards and just run those in SHARD_NUMBER"
  echo "              to run only even tests: '-u 0/2', odd: '-u 1/2'"
  echo " -c           skip pants integration tests (includes examples and testprojects)"
  echo " -i SHARD_NUMBER/TOTAL_SHARDS"
  echo "              if running integration tests, divide them into"
  echo "              TOTAL_SHARDS shards and just run those in SHARD_NUMBER"
  echo "              to run only even tests: '-i 0/2', odd: '-i 1/2'"
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

while getopts "hfxbkmsrjlpeu:ny:ci:at" opt; do
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
    a) skip_android="true" ;;
    t) skip_lint="true" ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done
shift $((${OPTIND} - 1))

# Android testing requires the SDK to be installed and configured in Pants.
# Skip if ANDROID_HOME isn't configured in the environment
if [[ -z "${ANDROID_HOME}"  || "${skip_android:-false}" == "true" ]] ; then
  export SKIP_ANDROID_PATTERN='contrib/android'
fi

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

# TODO(John sirois): Re-plumb build such that it grabs constraints from the built python_binary
# target(s).
# TODO: This doesn't seem necessary? We set this in pants.ini.
INTERPRETER_CONSTRAINTS=(
  "CPython>=2.7,<3"
)
for constraint in ${INTERPRETER_CONSTRAINTS[@]}; do
  INTERPRETER_ARGS=(
    ${INTERPRETER_ARGS[@]}
    --python-setup-interpreter-constraints="${constraint}"
  )
done

PANTS_ARGS=(
  "${INTERPRETER_ARGS[@]}"
)

if [[ "${skip_bootstrap:-false}" == "false" ]]; then
  start_travis_section "Bootstrap" "Bootstrapping pants"
  (
    if [[ "${skip_bootstrap_clean:-false}" == "false" ]]; then
      ./build-support/python/clean.sh || die "Failed to clean before bootstrapping pants."
    fi
    ./pants ${PANTS_ARGS[@]} ${bootstrap_compile_args[@]} binary \
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
    cmd="./pants.pex ${PANTS_ARGS[@]} ${cur_test}"
    echo "* Executing command '${cmd}' as a sanity test"
    ${cmd} >/dev/null 2>&1 || die "Failed to execute '${cmd}'."
  done
  end_travis_section
fi

if [[ "${skip_lint:-false}" == "false" ]]; then
  start_travis_section "Lint" "Running lint checks"
  (
    ./pants.pex ${PANTS_ARGS[@]} --tag=-nolint lint contrib:: examples:: src:: tests:: zinc::
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
    ./pants.pex ${PANTS_ARGS[@]} doc test {src,tests}/{java,scala}:: zinc::
  ) || die "Core jvm test failure"
  end_travis_section
fi

if [[ "${skip_internal_backends:-false}" == "false" ]]; then
  start_travis_section "BackendTests" "Running internal backend python tests"
  (
    ./pants.pex ${PANTS_ARGS[@]} test.pytest \
    pants-plugins/tests/python::
  ) || die "Internal backend python test failure"
  end_travis_section
fi

if [[ "${skip_python:-false}" == "false" ]]; then
  if [[ "0/1" != "${python_unit_shard}" ]]; then
    shard_desc=" [shard ${python_unit_shard}]"
  fi
  start_travis_section "CoreTests" "Running core python tests${shard_desc}"
  (
    ./pants.pex --tag='-integration' ${PANTS_ARGS[@]} test.pytest --chroot \
      --test-pytest-test-shard=${python_unit_shard} \
      tests/python::
  ) || die "Core python test failure"
  end_travis_section
fi

if [[ "${skip_contrib:-false}" == "false" ]]; then
  if [[ "0/1" != "${python_contrib_shard}" ]]; then
    shard_desc=" [shard ${python_contrib_shard}]"
  fi
  start_travis_section "ContribTests" "Running contrib python tests${shard_desc}"
  (
    ./pants.pex ${PANTS_ARGS[@]} --exclude-target-regexp='.*/testprojects/.*' \
    --build-ignore=$SKIP_ANDROID_PATTERN test.pytest \
    --test-pytest-test-shard=${python_contrib_shard} \
    contrib:: \
  ) || die "Contrib python test failure"
  end_travis_section
fi

if [[ "${skip_rust_tests:-false}" == "false" ]]; then
  start_travis_section "RustTests" "Running Pants rust tests"
  (
    source "${REPO_ROOT}/build-support/pants_venv"
    source "${REPO_ROOT}/build-support/bin/native/bootstrap.sh"
    activate_pants_venv
    RUST_BACKTRACE=1 PANTS_SRCPATH="${REPO_ROOT}/src/python" ensure_cffi_sources=1 run_cargo test "${MODE_FLAG}" --all --manifest-path="${REPO_ROOT}/src/rust/engine/Cargo.toml"
  ) || die "Pants rust test failure"
  end_travis_section
fi


if [[ "${skip_integration:-false}" == "false" ]]; then
  if [[ "0/1" != "${python_intg_shard}" ]]; then
    shard_desc=" [shard ${python_intg_shard}]"
  fi
  start_travis_section "IntegrationTests" "Running Pants Integration tests${shard_desc}"
  (
    ./pants.pex ${PANTS_ARGS[@]} --tag='+integration' test.pytest \
      --test-pytest-test-shard=${python_intg_shard} \
      tests/python::
  ) || die "Pants Integration test failure"
  end_travis_section
fi

banner "CI ENDS"
echo
green "SUCCESS"
