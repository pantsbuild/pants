#!/bin/bash -eu

# Outputs the current operating system and variant, as used by BinaryUtils.
# Example output: mac/10.13
# Example output: linux/x86_64

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
    echo >&2 "Unknown platform"
    exit 1
    ;;
esac

echo "${os}/${os_version}"
