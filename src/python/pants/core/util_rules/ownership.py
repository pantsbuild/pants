# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from collections.abc import Iterable

from pants.core.goals.tailor import AllOwnedSources, PutativeTargetsRequest
from pants.engine.intrinsics import path_globs_to_paths


async def get_unowned_files_for_globs(
    request: PutativeTargetsRequest,
    all_owned_sources: AllOwnedSources,
    filename_globs: Iterable[str],
) -> set[str]:
    matching_paths = await path_globs_to_paths(request.path_globs(*filename_globs))
    return set(matching_paths.files) - set(all_owned_sources)
