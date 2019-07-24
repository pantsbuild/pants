# Functions to simplify the multiple complex bootstrapping techniques currently necessary to build a
# zinc native-image.
# TODO: This will be made automatic in pants via https://github.com/pantsbuild/pants/pull/6893.

# TODO: build off of a more recent graal sha (more recent ones fail to build scalac and more): see
# https://github.com/oracle/graal/issues/1448.

# shellcheck source=build-support/native-image/utils.bash
source "${SCRIPT_DIR}/utils.bash"

# FUNCTIONS

function _get_coursier_impl {
  if [[ ! -f ./coursier ]]; then
    curl -Lo coursier https://git.io/coursier-cli || return "$?"
    chmod +x coursier
    ./coursier --help || return "$?"
  fi >&2
  normalize_path_check_file coursier
}

function get_coursier {
  do_within_cache_dir _get_coursier_impl
}

function bootstrap_environment {
  if is_osx; then
    # Install `realpath`.
    if ! hash realpath 2>/dev/null; then
      ensure_has_executable \
        'brew' \
        "homebrew must be installed to obtain the 'coreutils' package, which contains 'realpath'." \
        "Please see https://brew.sh/."
      brew install coreutils
    fi
  else
    # Install necessary tools for the ubuntu:latest container on docker hub.
    apt-get update
    apt-get -y install \
            g{cc,++} git curl aptitude zlib1g-dev make python{,3} git python3-pip \
            pkg-config libssl-dev libpython-dev openjdk-8-jdk

    # FIXME: Otherwise pants will fail at bootstrap with an unrecognized symbol `distutils.spawn`.
    pip3 install setuptools==40.0.0
  fi
  mkdir -pv "$NATIVE_IMAGE_BUILD_CACHE_DIR"
}

function get_base_native_image_build_script_graal_checkout {
  # TODO(#7955): See https://github.com/oracle/graal/issues/1448 and
  # https://github.com/pantsbuild/pants/issues/7955 to cover using a released graal instead of a
  # fork!
  # From https://github.com/cosmicexplorer/graal/tree/graal-make-zinc-again!
  do_within_cache_dir clone_repo_somewhat_idempotently \
                      graal/ \
                      https://github.com/cosmicexplorer/graal \
                      ac6f6dd4783cece28f1696b413f02c3776753890
}

function clone_mx {
  # From https://github.com/graalvm/mx/tree/master!
  do_within_cache_dir clone_repo_somewhat_idempotently \
                      mx/ \
                      https://github.com/graalvm/mx \
                      c01eef6e31cd5655b1f0682c445f4ed50aa5c05e
}

function extract_openjdk_jvmci {
  if is_osx; then
    outdir="openjdk1.8.0_202-jvmci-0.59/Contents/Home"
    url='https://github.com/graalvm/openjdk8-jvmci-builder/releases/download/jvmci-0.59/openjdk-8u202-jvmci-0.59-darwin-amd64.tar.gz'
  else
    outdir="openjdk1.8.0_202-jvmci-0.59"
    url='https://github.com/graalvm/openjdk8-jvmci-builder/releases/download/jvmci-0.59/openjdk-8u202-jvmci-0.59-linux-amd64.tar.gz'
  fi
  do_within_cache_dir extract_tgz \
                      "$outdir" \
                      "$url"
}

function get_substratevm_dir {
  echo "$(get_base_native_image_build_script_graal_checkout)/substratevm"
}

function build_native_image_tool {
  get_substratevm_dir \
    | pushd_into_command_line_with_side_effect \
        mx build
}

function fetch_scala_compiler_jars {
  # TODO: the scala version used to build the pants zinc wrapper must also be changed if this is!
  version='2.12.8'
  "$(get_coursier)" fetch \
                    org.scala-lang:scala-{compiler,library,reflect}:"$version"
}

function fetch_pants_zinc_wrapper_jars {
  pants_zinc_compiler_version='0.0.15'
  pants_underlying_zinc_dependency_version='1.1.7'
  # TODO: `native-image` emits a warning on later protobuf versions, which the pantsbuild
  # `zinc-compiler` artifact will pull in unless we exclude them here and also explicitly add a
  # protobuf artifact. We should fix this by making the change to the org.pantsbuild:zinc-compiler
  # artifact!
  "$(get_coursier)" fetch \
                    "org.pantsbuild:zinc-compiler_2.12:${pants_zinc_compiler_version}" \
                    "org.scala-sbt:compiler-bridge_2.12:${pants_underlying_zinc_dependency_version}" \
                    --exclude com.google.protobuf:protobuf-java \
                    com.google.protobuf:protobuf-java:2.5.0
}

function create_zinc_image {
  local scala_compiler_jars="$(fetch_scala_compiler_jars | merge_jars)"
  local native_image_suite="$(do_within_cache_dir build_native_image_tool)"
  local pants_zinc_wrapper_jars="$(fetch_pants_zinc_wrapper_jars | merge_jars)"

  local expected_output="zinc-pants-native-$(uname)"

  >&2 time mx -p "$native_image_suite" native-image \
       -cp "${scala_compiler_jars}:${pants_zinc_wrapper_jars}" \
       org.pantsbuild.zinc.compiler.Main \
       -H:Name="$expected_output" \
       -J-Xmx7g -O9 \
       --verbose -H:+ReportExceptionStackTraces \
       --no-fallback \
       -Djava.io.tmpdir=/tmp \
       "$@" \
    || return "$?"

  normalize_path_check_file "$expected_output" \
                            'pants zinc native-image failed to generate!'
}
