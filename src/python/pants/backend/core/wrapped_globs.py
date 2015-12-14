# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated_module
from pants.source.wrapped_globs import (FilesetRelPathWrapper, FilesetWithSpec, Globs, RGlobs,
                                        ZGlobs, globs_matches, matches_filespec)


deprecated_module('0.0.66',
                  hint_message='pants.backend.core.wrapped_globs has moved to pants.sources.wrapped_globs. '
                               'Replace deps on src/python/pants/backend/core:wrapped_globs with a dep on '
                               'src/python/pants/source and change imports accordingly.')


globs_matches = globs_matches
matches_filespec = matches_filespec
FilesetWithSpec = FilesetWithSpec
FilesetRelPathWrapper = FilesetRelPathWrapper
Globs = Globs
RGlobs = RGlobs
ZGlobs = ZGlobs
