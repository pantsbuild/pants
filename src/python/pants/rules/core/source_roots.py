# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import text_type

from pants.engine.fs import Digest, PrefixStrippedDirectory
from pants.engine.rules import optionable_rule, rule
from pants.source.source_root import SourceRootConfig


# @rule(PrefixStrippedDirectory, [text_type, Digest, SourceRootConfig])
# def apply_source_root(address_spec, directory_digest, source_root_config):
#   source_roots = source_root_config.get_source_roots()
#   root = source_roots.find_by_path(address_spec)
#   yield PrefixStrippedDirectory(directory_digest, root.path)


# def rules():
#   return [
#     apply_source_root,
#     optionable_rule(SourceRootConfig),
#   ]

