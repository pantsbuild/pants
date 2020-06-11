# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '//:build_root',
    '//:pants_toml',
    'src/python/pants/option',
    'src/python/pants/option:global_options',
    'src/python/pants/option:options_bootstrapper',
    'src/python/pants/bin',  # NB: not explicitly used, but necessary for OptionsBootstrapper to be set up properly.
  ],
  tags = {"partially_type_checked"},
)
