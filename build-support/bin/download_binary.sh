#!/bin/bash -e

# Downloads the specified binary at the specified version from the specified binary host if it's not already present.
# Uses a reimplementation of the BinaryUtils mechanism.
# Outputs an absolute path to the binary, whether fetched or already present, to stdout.

# If the file ends in ".tar.gz", untars the file and outputs the directory to which the files were untar'd.
# Otherwise, makes the file executable.

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../.. && pwd -P)

# Defines:
# + CACHE_ROOT: The pants cache directory, ie: ~/.cache/pants.
source "${REPO_ROOT}/build-support/pants_venv"

if (( $# != 2 && $# != 3 )); then
  die "$(cat << USAGE
Usage: $0 util_name version [filename]
Example: $0 go 1.7.3 go.tar.gz
USAGE
)"
fi

readonly util_name="$1"
readonly version="$2"
readonly filename="${3:-${util_name}}"

readonly binary_helper_script="${REPO_ROOT}/build-support/bin/bootstrap_binary_util.py"

activate_pants_venv 1>&2
PYTHONPATH="${REPO_ROOT}/src/python" python "$binary_helper_script" \
          "$util_name" "$version" "$filename"
