# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.protobuf.java.java_protobuf_library import JavaProtobufLibrary
from pants.base.deprecated import deprecated_module


deprecated_module('1.5.0.dev0', 'Use pants.backend.codegen.protobuf.java instead')

JavaProtobufLibrary = JavaProtobufLibrary
