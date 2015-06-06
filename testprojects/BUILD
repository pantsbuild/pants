# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TODO(Eric Ayers) Find a way to reduce source_root() invocations.  The declarations here are
# repetitive with those in examples/BUILD

# Projects used by tests to exercise pants functionality
source_root('src/antlr', page, java_antlr_library, python_antlr_library)
source_root('src/java', annotation_processor, jvm_binary, java_library, jar_library, page)
source_root('src/protobuf', java_protobuf_library, jar_library, page)
source_root('src/scala', jvm_binary, page, scala_library, benchmark)
source_root('src/thrift', java_thrift_library, page, python_thrift_library)

source_root('tests/java', java_library, junit_tests, page, jar_library)
source_root('tests/python', page, python_library, python_tests, python_test_suite, python_binary, resources)
source_root('tests/resources', page, resources)
source_root('tests/scala', page, junit_tests, scala_library)
