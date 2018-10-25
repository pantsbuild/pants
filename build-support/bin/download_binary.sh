#!/bin/bash -eu

# Downloads the specified binary at the specified version from the specified binary host if it's not already present.
# Uses a reimplementation of the BinaryUtils mechanism.
# Outputs an absolute path to the binary, whether fetched or already present, to stdout.

# Use this version as a fallback for platform-specific binaries to download if we are on a version
# of OSX that we don't explicitly have binaries for yet.
# TODO: Keep this up to date automatically somehow!
MOST_RECENT_SUPPORTED_MACOS_VERSION='10.13'

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

function make_download_path_for_os {
  local os_string="$1"
  echo "bin/${util_name}/${os_string}/${version}/${filename}"
}

function curl_output_file_with_fail {
  local download_url="$1"
  local output_path="$2"
  echo >&2 "Downloading ${download_url} ..."
  curl --fail "$download_url" > "$output_path"
}

path="$(make_download_path_for_os "$("${REPO_ROOT}/build-support/bin/get_os.sh")")"
readonly cache_path="${CACHE_ROOT}/${path}"

maybe_alternate_os="$([[ "$(uname)" == 'Darwin' ]] \
    && echo "mac/${MOST_RECENT_SUPPORTED_MACOS_VERSION}")"

if [[ ! -f "${cache_path}" ]]; then
  mkdir -p "$(dirname "${cache_path}")"

  readonly binary_url="https://${host}/${path}"
  readonly output_tmp_file="${cache_path}.tmp"
  readonly curl_err_tmp_file="${cache_path}.curl.err.tmp"

  curl_output_file_with_fail "${binary_url}" "$output_tmp_file" \
                             2> >(tee >&2 "$curl_err_tmp_file") \
    || if grep -q -F 'The requested URL returned error: 404' "$curl_err_tmp_file" \
           && [[ -n "$maybe_alternate_os" ]]; then
    echo >&2 "Failed initial curl, trying an alternate url..."
    alternate_intermediate_path="$(make_download_path_for_os "$maybe_alternate_os")"
    readonly alternate_binary_url="https://${host}/${alternate_intermediate_path}"
    curl_output_file_with_fail "$alternate_binary_url" "$output_tmp_file"
  else
    exit 1
  fi

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
