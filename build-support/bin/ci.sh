#!/usr/bin/env bash

source build-support/common.sh

function usage() {
  echo "Runs commons tests for local or hosted CI."
  echo
  echo "Usage: $0 (-h|-bsrdpceat)"
  echo " -h           print out this help message"
  echo " -b           skip bootstraping pants from local sources"
  echo " -s           skip self-distribution tests"
  echo " -r           skip doc generation tests"
  echo " -d           if running jvm tests, don't use nailgun daemons"
  echo " -p           skip core python tests"
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

daemons="--ng-daemons"

while getopts "hbsrdpci:eat" opt; do
  case ${opt} in
    h) usage ;;
    b) skip_bootstrap="true" ;;
    s) skip_distribution="true" ;;
    r) skip_docs="true" ;;
    d) daemons="--no-ng-daemons" ;;
    p) skip_python="true" ;;
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

# Android testing requires the SDK to be installed and configured in Pants.
# Skip if ANDROID_HOME isn't configured in the environment
if [[ -z "${ANDROID_HOME}"  || "${skip_android:-false}" == "true" ]] ; then
  android_test_opts="--exclude-target-regexp=.*android.*"
else
  android_test_opts=""
fi

banner "CI BEGINS"

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
  "--print-exception-stacktrace"
  "${INTERPRETER_ARGS[@]}"
)


if [[ "${skip_bootstrap:-false}" == "false" ]]; then
  banner "Bootstrapping pants"
  (
    ./build-support/python/clean.sh && \
    PANTS_DEV=1 PANTS_VERBOSE=1 PEX_VERBOSE=1 PYTHON_VERBOSE=1 \
      ./pants goal ${PANTS_ARGS[@]} binary src/python/pants/bin:pants_local_binary && \
    mv dist/pants_local_binary.pex ./pants.pex && \
    ./pants.pex goal goals ${PANTS_ARGS[@]}
  ) || die "Failed to bootstrap pants."
fi

# We don't allow code in our __init.py__ files. Reject changes that allow
# this to creep back in.
R=`find src tests -name __init__.py -not -empty|grep -v src/python/pants/__init__.py`
if [ ! -z "${R}" ]; then
  echo "ERROR: All '__init__.py' files should be empty, but the following contain code:"
  echo "$R"
  exit 1
fi

# Sanity checks
./pants.pex goal clean-all ${PANTS_ARGS[@]} || die "Failed to clean-all."
./pants.pex goal goals ${PANTS_ARGS[@]} || die "Failed to list goals."
./pants.pex goal list :: ${PANTS_ARGS[@]} || die "Failed to list all targets."
./pants.pex goal targets ${PANTS_ARGS[@]} || die "Failed to show target help."

if [[ "${skip_distribution:-false}" == "false" ]]; then
  # TODO(John Sirois): Take this further and dogfood a bootstrap from the sdists generated by
  # setup_py
  banner "Running pants distribution tests"
  (
    # The published pants should need no local plugins beyond the python backend to distribute
    # itself so we override backends to ensure a minimal env works.
    config=$(mktemp -t pants-ci.XXXXXX.ini) && \
    (cat << EOF > ${config}
[backends]
packages: [
    # TODO(John Sirois): When we have fine grained plugins, include the python backend here
  ]
EOF
    ) && \
    export PANTS_CONFIG_OVERRIDE=${config} && \
    ./pants.pex goal binary ${INTERPRETER_ARGS[@]} \
      src/python/pants:_pants_transitional_publishable_binary_ && \
    mv dist/_pants_transitional_publishable_binary_.pex dist/self.pex && \
    ./dist/self.pex goal binary ${INTERPRETER_ARGS[@]} \
      src/python/pants:_pants_transitional_publishable_binary_ && \
    ./dist/self.pex goal setup-py --recursive src/python/pants:pants-packaged
  ) || die "Failed to create pants distributions."
fi

if [[ "${skip_docs:-false}" == "false" ]]; then
  banner "Running site doc generation test"
  ./build-support/bin/publish_docs.sh || die "Failed to generate site docs."
fi

if [[ "${skip_python:-false}" == "false" ]]; then
  banner "Running core python tests"
  (
    PANTS_PY_COVERAGE=paths:pants/,internal_backend/ \
      PANTS_PYTHON_TEST_FAILSOFT=1 \
      ./pants.pex goal test ${PANTS_ARGS[@]} \
        $(./pants.pex goal list tests/python:: | \
            xargs ./pants goal filter --filter-type=python_tests | \
            grep -v integration)
  ) || die "Core python test failure"
fi

if [[ "${skip_testprojects:-false}" == "false" ]]; then

  # TODO(Eric Ayers) find a better way to deal with tests that are known to fail.
  # right now, just split them into two categories and ignore them.

  # Targets that fail but shouldn't
  known_failing_targets=(
    testprojects/maven_layout/resource_collision/example_a/src/test/java/com/pants/duplicateres/examplea:examplea
    testprojects/maven_layout/resource_collision/example_b/src/test/java/com/pants/duplicateres/exampleb:exampleb
  )

  # Targets that are intended to fail
  negative_test_targets=(
    testprojects/src/thrift/com/pants/thrift_linter:
  )

  targets_to_exclude=(
    ${known_failing_targets[@]}
    ${negative_test_targets[@]}
  )
  exclude_opts="${targets_to_exclude[@]/#/--exclude-target-regexp=}"

  banner "Running tests in testprojects/ "
  (
    ./pants.pex goal test testprojects:: $daemons $android_test_opts $exclude_opts ${PANTS_ARGS[@]}
  ) || die "test failure in testprojects/"
fi

if [[ "${skip_examples:-false}" == "false" ]]; then
  banner "Running example tests"
  (
    ./pants.pex goal test examples:: $daemons $android_test_opts ${PANTS_ARGS[@]}
  ) || die "Examples test failure"
fi


if [[ "${skip_integration:-false}" == "false" ]]; then
  if [[ ! -z "${TOTAL_SHARDS}" ]]; then
    shard_desc=" [shard $((SHARD_NUMBER+1)) of ${TOTAL_SHARDS}]"
  fi
  banner "Running Pants Integration tests${shard_desc}"
  (
    PANTS_PYTHON_TEST_FAILSOFT=1 \
      ./pants.pex goal test ${PANTS_ARGS[@]} \
        $(./pants.pex goal list tests/python:: | \
            xargs ./pants goal filter --filter-type=python_tests | \
            grep integration | \
            sort | \
            awk "NR%${TOTAL_SHARDS:-1}==${SHARD_NUMBER:-0}")
  ) || die "Pants Integration test failure"
fi

banner "CI SUCCESS"
