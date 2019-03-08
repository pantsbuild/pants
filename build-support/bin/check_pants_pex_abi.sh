#!/usr/bin/env bash

# Check that the ./pants.pex was built using the passed abi specification.

REPO_ROOT="$(git rev-parse --show-toplevel)"
source ${REPO_ROOT}/build-support/common.sh
CHECK_FOLDER="${REPO_ROOT}/pants_pex_abi_check"

if [ ! -f "${REPO_ROOT}/pants.pex" ]; then
  die "pants.pex not found in the repository root! Run './build-support/bin/ci.sh -b'."
fi

function parse_wheel_abi() {
  # See https://www.python.org/dev/peps/pep-0425/#use for how wheel names are defined.
  wheel_filename="$1"
  IFS='-' read -r -a components <<< "${wheel_filename}"
  # Check if optional build tag
  if [ ${#components[@]} -eq 6 ]; then
    abi="${components[4]}"
  else
    abi="${components[3]}"
  fi
  echo "${abi}"
}

function cleanup() {
  rm -rf "${CHECK_FOLDER}"
}

# Determine expected abi
EXPECTED_ABI="$1"
if [ -z "${EXPECTED_ABI}" ]; then
  cleanup
  die "Must pass the expected abi as an argument. E.g. 'abi3' or 'cp27mu'."
fi

# Extract pex
mkdir "${CHECK_FOLDER}"
cp "${REPO_ROOT}/pants.pex" "${CHECK_FOLDER}/pants.pex"
unzip -qq "${CHECK_FOLDER}/pants.pex" -d "${CHECK_FOLDER}"

# Grab wheel filenames
distributions_section=$(cat "${CHECK_FOLDER}/PEX-INFO" | sed 's/.*"distributions": {\(.*\)},.*$/\1/')
IFS=' ' read -r -a wheel_filenames_and_shas <<< "${distributions_section}"
WHEEL_FILENAMES=()
for filename_or_sha in ${wheel_filenames_and_shas[@]}; do
  if [[ "${filename_or_sha}" = *'.whl":' ]] ; then
    wheel_filename=$(echo "${filename_or_sha}" | sed 's/"\(.*\)".*$/\1/')
    WHEEL_FILENAMES+=("${wheel_filename}")
  fi
done

# # Parse each wheel's abi
PARSED_ABIS=()
for filename in ${WHEEL_FILENAMES[@]}; do
  parsed_abi=$(parse_wheel_abi "${filename}")
  if [[ "${parsed_abi}" != "none" ]]; then
    PARSED_ABIS+=("${parsed_abi}")
  fi
done

# Ensure exactly one abi found
PARSED_ABIS=($(for abi in "${PARSED_ABIS[@]}"; do echo "$abi"; done | sort -u))
if [ ${#PARSED_ABIS[@]} -lt 1 ]; then
  cleanup
  die "No abi tag found. Expected: ${EXPECTED_ABI}."
elif [ ${#PARSED_ABIS[@]} -gt 1 ]; then
  cleanup
  die "Multiple abi tags found. Expected: ${EXPECTED_ABI}, found: ${PARSED_ABIS[@]}."
fi
FOUND_ABI="${PARSED_ABIS[0]}"

# Fail if invalid
if [[ "${FOUND_ABI}" != "${EXPECTED_ABI}" ]]; then
  cleanup
  die "pants.pex was built with the incorrect ABI. Expected: ${EXPECTED_ABI}, found: ${FOUND_ABI}."
fi

cleanup
