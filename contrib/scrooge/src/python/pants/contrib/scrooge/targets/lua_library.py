# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.resources import Resources


class LuaLibrary(Resources):
    """A Lua library.

    Abstracts a collection of Lua files.
    A JVM resource file might might depend on this library to package them into a `.jar`.
    """

    def __init__(self, address=None, payload=None, sources=None, provides=None, **kwargs):
        """
        :param sources: Files to "include". Paths are relative to the
          BUILD file's directory.
        :type sources: ``Fileset`` or list of strings
        """
        super(LuaLibrary, self).__init__(address=address, payload=payload, sources=sources, **kwargs)
        self.add_labels('lua')

    def has_sources(self, extension=''):
        return self._sources_field.has_sources(extension)
