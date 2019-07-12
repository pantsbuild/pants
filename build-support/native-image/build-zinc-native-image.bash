# ???

# TODO: build off of a more recent graal sha (more recent ones fail to build scalac and more): see
# https://github.com/oracle/graal/issues/1448.

set -euxo pipefail

# shellcheck source=build-support/native-image/utils.bash
source "${SCRIPT_DIR}/utils.bash"

# FUNCTIONS

function _get_coursier_impl {
  if [[ ! -f ./coursier ]]; then
    curl -Lo coursier https://git.io/coursier-cli || return "$?"
    chmod +x coursier
    ./coursier --help >&2 || return "$?"
  fi >&2
  normalize_path coursier
}

function get_coursier {
  do_within_cache_dir _get_coursier_impl
}

function bootstrap_environment {
  # Install necessary tools for the ubuntu:latest container on docker hub.
  if ! is_osx; then
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
  do_within_cache_dir clone_repo_somewhat_idempotently \
                      graal/ \
                      https://github.com/cosmicexplorer/graal \
                      graal-make-zinc-again
}

function clone_mx {
  do_within_cache_dir clone_repo_somewhat_idempotently \
                      mx/ \
                      https://github.com/graalvm/mx \
    && with_pushd "${NATIVE_IMAGE_BUILD_CACHE_DIR}/mx" \
                  ./mx update
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
  >&2 with_pushd "$(get_substratevm_dir)" \
             mx build || return "$?"
  get_substratevm_dir
}

function fetch_scala_compiler_jars {
  # TODO: the scala version used to build the pants zinc wrapper must also be changed if this is!
  version='2.12.8'
  "$(get_coursier)" fetch \
                    org.scala-lang:scala-{compiler,library,reflect}:"$version" \
    | merge_jars
}

function fetch_pants_zinc_wrapper_jars {
  "$(get_coursier)" fetch org.pantsbuild:zinc-compiler_2.12:0.0.15 \
    | merge_jars
}

function create_zinc_image {
  scala_compiler_jars="$(fetch_scala_compiler_jars)"
  native_image_suite="$(do_within_cache_dir build_native_image_tool)"
  pants_zinc_wrapper_jars="$(fetch_pants_zinc_wrapper_jars)"

  expected_output="zinc-pants-native-$(uname)"

  time mx -p "$native_image_suite" native-image \
       -cp "${scala_compiler_jars}:${pants_zinc_wrapper_jars}" \
       org.pantsbuild.zinc.compiler.Main \
       -H:Name="$expected_output" \
       -J-Xmx7g -O0 \
       --verbose -H:+ReportExceptionStackTraces \
       --no-fallback \
       -Djava.io.tmpdir=/tmp \
       "$@" \
       >&2

  normalize_path "$expected_output" \
    && [[ -f "$(pwd)/${expected_output}" ]]
}
