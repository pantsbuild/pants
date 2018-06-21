#!/bin/bash -eu

# Downloads the specified binary at the specified version from the specified binary host if it's not already present.
# Uses a reimplementation of the BinaryUtils mechanism.
# Outputs an absolute path to the binary, whether fetched or already present, to stdout.

# If the file ends in ".tar.gz", untars the file and outputs the directory to which the files were untar'd.
# Otherwise, makes the file executable.

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../.. && pwd -P)

# Defines:
# + CACHE_ROOT: The pants cache directory, ie: ~/.cache/pants.
source "${REPO_ROOT}/build-support/common.sh"

if (( $# != 3 && $# != 4 )); then
  die "$(cat << USAGE
Usage: $0 host util_name version [filename]
Example: $0 binaries.pantsbuild.org go 1.7.3 go.tar.gz
USAGE
)"
fi
readonly host="$1"
readonly util_name="$2"
readonly version="$3"
readonly filename="${4:-${util_name}}"

os=$("${REPO_ROOT}/build-support/bin/get_os.sh")
readonly path="bin/${util_name}/${os}/${version}/${filename}"
readonly cache_path="${CACHE_ROOT}/${path}"

if [[ ! -f "${cache_path}" ]]; then
  mkdir -p "$(dirname "${cache_path}")"

  readonly binary_url="https://${host}/${path}"
  echo >&2 "Downloading ${binary_url} ..."
  curl --fail "${binary_url}" > "${cache_path}".tmp
  mv "${cache_path}"{.tmp,}
  if [[ "${filename}" == *tar.gz ]]; then
    tar -C "$(dirname "${cache_path}")" -xzf "${cache_path}"
  else
    chmod 0755 "${cache_path}"
  fi
fi

to_output="${cache_path}"
if [[ "${filename}" == *tar.gz ]]; then
  to_output="$(dirname "${to_output}")"
fi
echo "${to_output}"
