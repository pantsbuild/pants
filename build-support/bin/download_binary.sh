#!/bin/bash -eu

# Downloads the specified binary at the specified version from the specified binary host if it's not already present.
# Uses a reimplementation of the BinaryUtils mechanism.
# Outputs an absolute path to the binary, whether fetched or already present, to stdout.

# If the file ends in ".tar.gz", untars the file and outputs the directory to which the files were untar'd.
# Otherwise, makes the file executable.

if [[ $# -ne 3 && $# -ne 4 ]]; then
  echo >&2 "Usage: $0 host util_name version [filename]"
  echo >&2 "Example: $0 binaries.pantsbuild.org go 1.7.3 go.tar.gz"
  exit 1
fi
host="$1"
util_name="$2"
version="$3"
filename="${4:-${util_name}}"


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

path="bin/${util_name}/$("${SCRIPT_DIR}/get_os.sh")/${version}/${filename}"
cache_path="${HOME}/.cache/pants/${path}"

if [[ ! -f "${cache_path}" ]]; then
  mkdir -p "$(dirname "${cache_path}")"
  curl --fail "https://${host}/${path}" > "${cache_path}".tmp
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
