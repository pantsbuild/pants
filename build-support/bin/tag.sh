#!/usr/bin/env bash
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd "$(git rev-parse --show-toplevel)" && pwd)
source ${ROOT}/build-support/common.sh

# NB: Unlike `release.sh`, this script always operates on un-suffixed releases.
readonly PANTS_VERSION="$(run_local_pants --version 2>/dev/null)"

function tag_release() {
  release_version="${PANTS_VERSION}" && \
  tag_name="release_${release_version}" && \
  git tag -f \
    --local-user=$(get_pgp_keyid) \
    -m "pantsbuild.pants release ${release_version}" \
    ${tag_name} && \
  git push -f git@github.com:pantsbuild/pants.git ${tag_name}
}

banner "Tagging release for ${PANTS_VERSION}" && \
(
  check_clean_branch && check_pgp && tag_release && \
    banner "Successfully tagged ${PANTS_VERSION}"
) || die "Failed to tag release."
