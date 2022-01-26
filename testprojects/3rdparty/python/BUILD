# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TODO(#14268): Once python_requirements passes down `tags` and `compatible_resolves`, we can DRY
#  this again with that target generator.
common_kwargs = dict(
    experimental_compatible_resolves=["python-testprojects"],
    tags=["lockfile_ignore"],
)

python_requirement(
    name="checksumdir",
    requirements=["checksumdir==1.1.7"],
    **common_kwargs,
)

python_requirement(
    name="numpy",
    requirements=["numpy==1.14.5"],
    **common_kwargs,
)
