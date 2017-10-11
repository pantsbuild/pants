#!/bin/bash -eu

# Downloads the specified binary at the specified version from binaries.pantsbuild.org if it's not already present.
# Uses a reimplementation of the BinaryUtils mechanism.
# Outputs an absolute path to the binary, whether fetched or already present, to stdout.

# If the file ends in ".tar.gz", untars the file and outputs the directory to which the files were untar'd.
# Otherwise, makes the file executable.

if [[ $# -ne 2 && $# -ne 3 ]]; then
  echo >&2 "Usage: $0 util_name version [filename]"
  echo >&2 "Example: $0 go 1.7.3 go.tar.gz"
  exit 1
fi
util_name="$1"
version="$2"
filename="${3:-${util_name}}"

case "$(uname)" in
  "Darwin")
    os="mac"
    base="$(uname -r)"
    os_version="10.$(( ${base%%.*} - 4))"
    ;;
  "Linux")
    os="linux"
    os_version="$(uname -m)"
    ;;
  *)
    echo >&2 "Unknown platform when fetching binary"
    exit 1
    ;;
esac

path="bin/${util_name}/${os}/${os_version}/${version}/${filename}"
cache_path="${HOME}/.cache/pants/${path}"

if [[ ! -f "${cache_path}" ]]; then
  mkdir -p "$(dirname "${cache_path}")"
  curl --fail "https://binaries.pantsbuild.org/${path}" > "${cache_path}".tmp
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
