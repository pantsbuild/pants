# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.docgen.targets.doc import Page, Wiki, WikiArtifact
from pants.base.deprecated import deprecated_module


deprecated_module('0.0.66',
                  hint_message='pants.backend.core.targets.doc has moved to '
                               'pants.backend.docgen.targets.doc. Replace deps on '
                               'src/python/pants/backend/core/targets:all or '
                               'src/python/pants/backend/core/targets:common with a dep on '
                               'src/python/pants/backend/docgen/targets and change imports accordingly.')


Page = Page
Wiki = Wiki
WikiArtifact = WikiArtifact
