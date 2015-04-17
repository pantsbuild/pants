#!/usr/bin/env bash

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd "$(git rev-parse --show-toplevel)" && pwd)
cd ${REPO_ROOT}

source build-support/common.sh

function usage() {
  echo "Runs commons tests for local or hosted CI."
  echo
  echo "Usage: $0 (-h|-fxbkmsrjlpncieat)"
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
  echo " -n           skip contrib python tests"
  echo " -c           skip pants integration tests"
  echo " -i TOTAL_SHARDS:SHARD_NUMBER"
  echo "              if running integration tests, divide them into"
  echo "              TOTAL_SHARDS shards and just run those in SHARD_NUMBER"
  echo "              to run only even tests: '-i 2:0', odd: '-i 2:1'"
  echo " -e           skip example tests"
  echo " -a           skip android targets when running tests"
  echo " -t           skip testprojects tests"
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

while getopts "hfxbkmsrjlpnci:eat" opt; do
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
    n) skip_contrib="true" ;;
    c) skip_integration="true" ;;
    i)
      if [[ "valid" != "$(echo ${OPTARG} | sed -E 's|[0-9]+:[0-9]+|valid|')" ]]; then
        usage "Invalid shard specification '${OPTARG}'"
      fi
      TOTAL_SHARDS=${OPTARG%%:*}
      SHARD_NUMBER=${OPTARG##*:}
      ;;
    e) skip_examples="true" ;;
    a) skip_android="true" ;;
    t) skip_testprojects="true" ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done
shift $((${OPTIND} - 1))

# Android testing requires the SDK to be installed and configured in Pants.
# Skip if ANDROID_HOME isn't configured in the environment
if [[ -z "${ANDROID_HOME}"  || "${skip_android:-false}" == "true" ]] ; then
  android_test_opts="--exclude-target-regexp=.*android.*"
else
  android_test_opts=""
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
  banner "Sanity checking bootrapped pants and repo BUILD files"
  ./pants.pex ${PANTS_ARGS[@]} clean-all || die "Failed to clean-all."
  ./pants.pex ${PANTS_ARGS[@]} goals || die "Failed to list goals."
  ./pants.pex ${PANTS_ARGS[@]} list :: || die "Failed to list all targets."
  ./pants.pex ${PANTS_ARGS[@]} targets || die "Failed to show target help."
fi

if [[ "${skip_distribution:-false}" == "false" ]]; then
  banner "Running pants distribution tests"
  (
    # The published pants should need no local plugins beyond the python backend to distribute
    # itself so we override backends to ensure a minimal env works.
    config=$(mktemp -t pants-ci.XXXXXX.ini) && \
    (cat << EOF > ${config}
[backends]
packages: [
    # TODO(John Sirois): When we have fine grained plugins, include the python backend here
    "internal_backend.utilities",
  ]
EOF
    ) && \
    ./pants.pex ${INTERPRETER_ARGS[@]} --config-override=${config} binary \
      src/python/pants/bin:pants && \
    mv dist/pants.pex dist/self.pex && \
    ./dist/self.pex ${INTERPRETER_ARGS[@]} --config-override=${config} binary \
      src/python/pants/bin:pants && \
    ./build-support/bin/release.sh -pn
  ) || die "Failed to create pants distributions."
fi

if [[ "${skip_docs:-false}" == "false" ]]; then
  banner "Running site doc generation test"
  ./build-support/bin/publish_docs.sh || die "Failed to generate site docs."
fi

if [[ "${skip_jvm:-false}" == "false" ]]; then
  banner "Running core jvm tests"
  (
    ./pants.pex ${PANTS_ARGS[@]} test tests/java::
  ) || die "Core jvm test failure"
fi

if [[ "${skip_internal_backends:-false}" == "false" ]]; then
  banner "Running internal backend python tests"
  (
    PANTS_PYTHON_TEST_FAILSOFT=1 \
      ./pants.pex ${PANTS_ARGS[@]} test \
        $(./pants.pex list pants-plugins/tests/python:: | \
            xargs ./pants.pex filter --filter-type=python_tests | \
            grep -v integration)
  ) || die "Internal backend python test failure"
fi

if [[ "${skip_python:-false}" == "false" ]]; then
  banner "Running core python tests"
  (
    PANTS_PY_COVERAGE=paths:pants/ \
      PANTS_PYTHON_TEST_FAILSOFT=1 \
      ./pants.pex ${PANTS_ARGS[@]} test \
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
    PANTS_PYTHON_TEST_FAILSOFT=1 ./pants.pex ${PANTS_ARGS[@]} test.pytest --no-fast contrib::
  ) || die "Contrib python test failure"
fi

if [[ "${skip_testprojects:-false}" == "false" ]]; then

  # TODO(Eric Ayers) find a better way to deal with tests that are known to fail.
  # right now, just split them into two categories and ignore them.

  # Targets that fail but shouldn't
  known_failing_targets=(
    testprojects/maven_layout/resource_collision/example_a/src/test/java/org/pantsbuild/duplicateres/examplea:examplea
    testprojects/maven_layout/resource_collision/example_b/src/test/java/org/pantsbuild/duplicateres/exampleb:exampleb
  )

  # Targets that are intended to fail
  negative_test_targets=(
    testprojects/src/antlr/pants/backend/python/test:antlr_failure
    testprojects/src/java/org/pantsbuild/testproject/cycle1
    testprojects/src/java/org/pantsbuild/testproject/cycle2
    testprojects/src/java/org/pantsbuild/testproject/missingdepswhitelist.*
    testprojects/src/python/antlr:test_antlr_failure
    testprojects/src/thrift/org/pantsbuild/thrift_linter:
    testprojects/tests/java/org/pantsbuild/testproject/dummies:failing_target
    testprojects/tests/python/pants/dummies:failing_targe
  )

  targets_to_exclude=(
    ${known_failing_targets[@]}
    ${negative_test_targets[@]}
  )
  exclude_opts="${targets_to_exclude[@]/#/--exclude-target-regexp=}"

  run()
  {
    local strategy=$1
    banner "Running tests in testprojects/ with the $strategy strategy"
    (
      ./pants.pex ${PANTS_ARGS[@]} test \
        --compile-apt-strategy=$strategy \
        --compile-java-strategy=$strategy \
        --compile-scala-strategy=$strategy \
        testprojects:: $android_test_opts $exclude_opts
    ) || die "test failure in testprojects/ with the $strategy strategy"
  }

  run "global"
  run "isolated"
fi

if [[ "${skip_examples:-false}" == "false" ]]; then
  run()
  {
    local strategy=$1
    banner "Running example tests with the $strategy strategy"
    (
      ./pants.pex ${PANTS_ARGS[@]} test \
        --compile-apt-strategy=$strategy \
        --compile-java-strategy=$strategy \
        --compile-scala-strategy=$strategy \
        examples:: \
        $android_test_opts
    ) || die "Examples tests failure with the $strategy strategy"
  }

  run "global"
  run "isolated"
fi


if [[ "${skip_integration:-false}" == "false" ]]; then
  if [[ ! -z "${TOTAL_SHARDS}" ]]; then
    shard_desc=" [shard $((SHARD_NUMBER+1)) of ${TOTAL_SHARDS}]"
  fi
  banner "Running Pants Integration tests${shard_desc}"
  (
    PANTS_PYTHON_TEST_FAILSOFT=1 \
      ./pants.pex ${PANTS_ARGS[@]} test \
        $(./pants.pex list tests/python:: | \
            xargs ./pants.pex filter --filter-type=python_tests | \
            grep integration | \
            sort | \
            awk "NR%${TOTAL_SHARDS:-1}==${SHARD_NUMBER:-0}")
  ) || die "Pants Integration test failure"
fi

banner "CI SUCCESS"
