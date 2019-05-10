# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals


# from future.utils import text_type

# from pants.engine.fs import Digest, PrefixStrippedDirectory
# from pants.engine.rules import optionable_rule, rule
# from pants.source.source_root import SourceRootConfig
# from pants.util.objects import datatype


# TODO: improve name
# class SourceRootDigest(datatype([("digest", Digest)])): pass

# TODO: this rule doesn't work :/ Stu is investigating why.
# @rule(SourceRootDigest, [Digest, SourceRootConfig])
# def apply_source_root(directory_digest, source_root_config):
#   source_roots = source_root_config.get_source_roots()
#   # root = source_roots.find_by_path(address_spec)
#   result_digest = yield Get(Digest, PrefixStrippedDirectory(digest, "testprojects/tests/python"))
#   yield SourceRootDigest(result_digest)


# def rules():
#   return [
#     apply_source_root,
#     optionable_rule(SourceRootConfig),
#   ]
