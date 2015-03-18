#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd ${REPO_ROOT}

source build-support/common.sh

function usage() {
  echo "Checks import sort order for python files, optionally fixing incorrect"
  echo "sorts."
  echo
  echo "Usage: $0 (-h|-f)"
  echo " -h    print out this help message"
  echo " -f    instead of erroring on files with bad import sort order, fix"
  echo "       those files"
  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

isort_args=(
  --check-only
)

while getopts "hf" opt
do
  case ${opt} in
    h) usage ;;
    f) isort_args=() ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done

REQUIREMENTS=(
  "isort==3.9.5"
)

VENV_DIR="build-support/isort.venv"

function fingerprint_data() {
  openssl md5 | cut -d' ' -f2
}

function activate_venv() {
  source "${VENV_DIR}/bin/activate"
}

function create_venv() {
  rm -rf "${VENV_DIR}"
  ./build-support/virtualenv "${VENV_DIR}"
}

function activate_isort() {
  for req in ${REQUIREMENTS[@]}
  do
    fingerprint="$(echo "${fingerprint}${req}" | fingerprint_data)"
  done

 bootsrapped_file="${VENV_DIR}/BOOTSTRAPPED.${fingerprint}"
 if ! [ -f "${bootsrapped_file}" ]
 then
   create_venv || die "Failed to create venv."
   activate_venv || die "Failed to activate venv."
   for req in ${REQUIREMENTS[@]}
   do
     pip install --quiet ${req} || die "Failed to install requirements from ${req}."
   done
   touch "${bootsrapped_file}"
 else
   activate_venv || die "Failed to activate venv."
 fi
}

activate_isort

isort ${isort_args[@]} --recursive src tests pants-plugins examples contrib

