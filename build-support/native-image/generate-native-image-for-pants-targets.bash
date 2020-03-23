#!/usr/bin/env bash
# Script to generate a platform-specific native-image of the pantsbuild zinc wrapper which works to
# compile macros, from a pants project.

# Works on OSX and Linux -- see the README.md in this directory for more usage info.

# TODO: This will be made automatic in pants via https://github.com/pantsbuild/pants/pull/6893.

set -euxo pipefail

# TODO: Right now, NATIVE_IMAGE_EXTRA_ARGS='-H:IncludeResourceBundles=org.scalactic.ScalacticBundle'
# is necessary to build any zinc native-image which compiles any code using scalatest. This
# information should be inferred by the native-image agent, but isn't yet.

# TODO: build off of a more recent graal sha (more recent ones fail to build scalac and more): see
# https://github.com/oracle/graal/issues/1448, as well as
# https://github.com/pantsbuild/pants/issues/7955!

### ARGUMENTS

# $@: Forwarded to a `./pants compile` invocation which runs with reflection tracing enabled.
# $NATIVE_IMAGE_EXTRA_ARGS: Forwarded to a `native-image` invocation.
# $ZINC_IMAGE_VERSION: Used in the compile test that runs to validate the native-image. Determines
#                      where the image is written to in the pants cachedir.

### CONSTANTS

SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"

# shellcheck source=build-support/native-image/build-zinc-native-image.bash
source "${SCRIPT_DIR}/build-zinc-native-image.bash"

GENERATED_CONFIG_DIRNAME="${GENERATED_CONFIG_DIRNAME:-generated-reflect-config}"
GENERATED_CONFIG_DIR="$(normalize_path_no_validation "$GENERATED_CONFIG_DIRNAME")"
GENERATED_CONFIG_JSON_FILE="${GENERATED_CONFIG_DIR}/reflect-config.json"
GENERATED_BUILD_FILE="${GENERATED_CONFIG_DIR}/BUILD"

ZINC_IMAGE_VERSION="${ZINC_IMAGE_VERSION:-0.0.15-from-image-script}"

# NB: Using $REPO_ROOT as calculated in other scripts in this repo seems to make this script fail
# when run from outside the pants repo!
DOWNLOAD_BINARY_SCRIPT="$(normalize_path_check_file "${SCRIPT_DIR}/../bin/download_binary.sh")"

### FUNCTIONS

function download_buildozer {
  "$DOWNLOAD_BINARY_SCRIPT" \
    'buildozer' \
    '0.6.0-80c7f0d45d7e40fa1f7362852697d4a03df557b3'
}

function build_agent_dylib {
  if is_osx; then
    local dylib_extension='.dylib'
  else
    local dylib_extension='.so'
  fi
  local desired_agent_dylib_path="libnative-image-agent${dylib_extension}"
  if [[ ! -f "$desired_agent_dylib_path" ]]; then
    mx build \
      && mx native-image --tool:native-image-agent --verbose \
      && cp -v {,lib}native-image-agent"$dylib_extension" \
        || return "$?"
  fi >&2
  normalize_path_check_file "$desired_agent_dylib_path"
}

# run with tracing on

function run_zinc_compile_with_tracing {
  local agent_lib_path="$(get_substratevm_dir | pushd_into_command_line build_agent_dylib)"
  if [[ ! -f "$GENERATED_CONFIG_JSON_FILE" ]]; then
    rm -rfv "$GENERATED_CONFIG_DIR"
    mkdir -v "$GENERATED_CONFIG_DIR"
    # TODO: jvm options are ignored from the command line, this is a bug and should be fixed.
    export PANTS_COMPILE_ZINC_JVM_OPTIONS="+['-agentpath:${agent_lib_path}=config-merge-dir=${GENERATED_CONFIG_DIR}']"
    # NB: --worker-count=1 is because the `config-merge-dir` option to the native-image agent will
    # clobber symbols from concurrent compiles.
    ./pants -ldebug \
            --no-zinc-native-image \
            compile.rsc \
            --execution-strategy=hermetic \
            --worker-count=1 \
            --no-incremental \
            --no-use-classpath-jars \
            --cache-ignore \
            "$@" \
      || return "$?"
    unset PANTS_COMPILE_ZINC_JVM_OPTIONS
  fi >&2
  normalize_path_check_dir "$GENERATED_CONFIG_DIR"
}

# analyze tracing -- trim reflection down to just macros, then find those macros' targets with
# classmap

function trim_reflection_config_to_just_macros {
  # Scala macros are the only entries in reflect-config.json that appear to matter for the purposes
  # of compilation, so we filter down to only those.
  # TODO: do compiler plugins look different?
  jq '[.[] | select(.fields[]? | .name == "MODULE$")]' \
     <"$GENERATED_CONFIG_JSON_FILE" \
     >.tmp-reflect-config \
    && mv -v \
          .tmp-reflect-config \
          "$GENERATED_CONFIG_JSON_FILE"
}

function extract_macro_target_names_from_pants {
  ./pants classmap "$@" >.tmp-classmap || return "$?"

  # Get the class names of all the macro usages, then filter down the above `./pants classmap` to
  # find the targets which provide those classes.
  jq -r '.[] | .name' <"$GENERATED_CONFIG_JSON_FILE" | while read -r class_name; do
    grep -F "$class_name" .tmp-classmap \
      | sed -Ee 's#^.* (.*)$#\1#g'
  done | sort -u
}

# create a BUILD file of the appropriate dependencies

function template_BUILD_file {
  # The 'sed' output substitution within this heredoc will convert a list of pants target specs into
  # double-quoted entries in the 'dependencies' kwarg. It will also prepend '//' to each target
  # address so buildozer recognizes them.
  cat <<EOF
# This file was generated by the scripts in https://github.com/pantsbuild/pants/tree/master/build-support/native-image/.
# DO NOT EDIT!!!

jvm_binary(
  name='generated-native-image-binary',
  dependencies=[
    $(sed -Ee 's#^(.*)$#"//\1",#g')
  ],
)
EOF
}

# generate the deps jar and reflect config at known locations!!!

function chunk_and_normalize_pants_deps_for_buildozer {
  # Buildozer can only run one process in parallel, so we want to add as many dependencies into a
  # single invocation as possible (hence -L200). This function will read pants targets from stdin
  # and output long lines which are converted into a buildozer 'add dependencies' command.
  xargs -t -P1 -L200 printf "//%s " \
    && echo
}

function add_buildozer_macro_deps {
  local buildozer="$(download_buildozer)"
  # Ensure the buildozer download succeeds!
  rc="$?"; [[ "$rc" -ne 0 ]] && return "$rc"
  chunk_and_normalize_pants_deps_for_buildozer | while read -r buildozer_deps_flattened; do
    "$buildozer" "add dependencies ${buildozer_deps_flattened}" \
                 "//${GENERATED_CONFIG_DIRNAME}:generated-native-image-binary"
    rc="$?"; [[ "$rc" -eq 0 || "$rc" -eq 3 ]] || return "$rc"
  done
}

function generate_template_macro_deps_target {
  template_BUILD_file >"$GENERATED_BUILD_FILE"
}

function add_macro_deps_to_generated_target {
  # NB: dump dependencies to a file, then run `./pants list` to normalize them!
  cat >.tmp-deps
  ./pants --spec-file=.tmp-deps list | sort -u >.tmp-normalized-deps || return "$?"
  if [[ -f "$GENERATED_BUILD_FILE" ]]; then
    # If the generated BUILD file exists already, pull down buildozer to idempotently add the new
    # deps!
    add_buildozer_macro_deps <.tmp-normalized-deps
  else
    # Otherwise, generate a BUILD file next to the generated native-image json config.
    generate_template_macro_deps_target <.tmp-normalized-deps
  fi >&2
}

function generate_macro_deps_jar {
  # NB: This "gracefully" handles the case of having no macros to add by having pants succeed
  # without outputting any jar. This is passed to the native-image build classpath, which accepts
  # entries that don't exist.
  >&2 extract_macro_target_names_from_pants "$@" \
    | add_macro_deps_to_generated_target \
    || return "$?"

  >&2 ./pants -ldebug binary "//${GENERATED_CONFIG_DIRNAME}:generated-native-image-binary" \
    || return "$?"

  normalize_path_check_file dist/generated-native-image-binary.jar
}

function exercise_native_image_for_compilation {
  # Test that the just-built native-image can be executed successfully, including running a test
  # compile!
  local image_location="$1"
  local -a other_args=( "${@:2}" )

  "$image_location" --help || return "$?"
  echo >&2 "native image generated at ${image_location}. running test compile..."
  sleep 5

  # Put the native-image in the correct cache location for zinc 0.0.15, overwriting the current one
  # if necessary!
  if is_osx; then
    local zinc_image_base_pants_cachedir="${HOME}/.cache/pants/bin/zinc-pants-native-image/mac/10.13"
  else
    local zinc_image_base_pants_cachedir="${HOME}/.cache/pants/bin/zinc-pants-native-image/linux/x86_64"
  fi
  local zinc_image_pants_cached="${zinc_image_base_pants_cachedir}/${ZINC_IMAGE_VERSION}"
  mkdir -pv "$zinc_image_pants_cached" || return "$?"

  cp -v "$image_location" "${zinc_image_pants_cached}/zinc-pants-native-image"

  export PANTS_COMPILE_ZINC_JVM_OPTIONS='[]'
  ./pants --zinc-native-image --zinc-version="$ZINC_IMAGE_VERSION" \
          compile.rsc --execution-strategy=hermetic --no-incremental --cache-ignore \
          test \
          "${other_args[@]}" \
    || return "$?"
  unset PANTS_COMPILE_ZINC_JVM_OPTIONS
}

# actually build the zinc image!!!

### EXECUTING!
# NB: We create files named `.tmp-*` in many methods in this script. These files aren't used for
# caching, just as temporary outputs for parts of the script since we can't yet do this in Pants
# directly (see https://github.com/pantsbuild/pants/pull/6893). This will remove all of those files.
_orig_pwd="$(pwd)"
trap 'find "$_orig_pwd" -maxdepth 1 -type f -name ".tmp-*" -exec rm {} "+"' EXIT

# NB: It's not clear whether it's possible to set the locale in some ubuntu containers, so we
# simply ignore it here.
export PANTS_IGNORE_UNRECOGNIZED_ENCODING=1
# NB: This is necessary to make download_binary.sh work!
export PY="$(which python3)"

# NB: We support having empty extra args, so this check for the 'xxx' sentinel will only capture
# when the $NATIVE_IMAGE_EXTRA_ARGS variable is truly unset.
if [[ "${NATIVE_IMAGE_EXTRA_ARGS:-xxx}" == 'xxx' ]]; then
  export NATIVE_IMAGE_EXTRA_ARGS='-H:IncludeResourceBundles=org.scalactic.ScalacticBundle'
  cat >&2 <<EOF
Including the scalactic resource bundle via the default NATIVE_IMAGE_EXTRA_ARGS='${NATIVE_IMAGE_EXTRA_ARGS}'.
This is necessary for any repo using scalatest, but if it breaks yours, you may try setting:
NATIVE_IMAGE_EXTRA_ARGS=' '
EOF
  sleep 5
fi

bootstrap_environment >&2

ensure_has_executable \
  'jq' \
  "jq must be installed to be able to manipulate the native-image json config." \
  "Please see https://stedolan.github.io/jq/!" \
  >&2

export JAVA_HOME="$(extract_openjdk_jvmci)"
PATH="$(clone_mx):${PATH}"

run_zinc_compile_with_tracing "$@" \
  | >&2 pushd_into_command_line \
        trim_reflection_config_to_just_macros
readonly MACRO_DEPS_JAR="$(generate_macro_deps_jar "$@")"

# NB: We also echo the image location to stdout, while piping everything else to stderr. This
# means that the script can be invoked from another script to get a single line of stdout
# containing the path to the just-built native-image.
create_zinc_image \
  -H:ConfigurationFileDirectories="$GENERATED_CONFIG_DIR" \
  -cp "$MACRO_DEPS_JAR" \
  ${NATIVE_IMAGE_EXTRA_ARGS:-} \
  | command_line_with_side_effect \
      exercise_native_image_for_compilation "$@"

# TODO(#7955): if the native-image build fails, and you see the following in the output:
#
#     Caused by: java.lang.VerifyError: class scala.tools.nsc.Global overrides final method isDeveloper.()Z
#
# Please re-run the script at most two more times. This can occur nondeterministically for some
# reason right now. https://github.com/pantsbuild/pants/issues/7955 is intended to cover solving
# this issue, along with others.
