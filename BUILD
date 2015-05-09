# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Pants source code
source_root('src/python', page, python_binary, python_library, resources)
source_root('src/java', page, java_library, jvm_binary)
source_root('src/resources', page, resources)
source_root('src/scala', page, scala_library, jvm_binary)

# Pants test code
source_root('tests/python', page, python_library, python_tests, python_test_suite, python_binary, resources)
source_root('tests/java', page, java_library, junit_tests, jvm_binary)
source_root('tests/resources', page, resources)

# Pants own plugins for this repo's exclusive use
source_root('pants-plugins/src/python', page, python_binary, python_library, resources)
source_root('pants-plugins/tests/python', page, python_library, python_tests, python_test_suite, python_binary, resources)

# TODO(Eric Ayers) Find a way to reduce  source_root() invocations.  The declarations in
# 'testprojects' and 'examples' are repetitive.

# Projects used by tests to exercise pants functionality
source_root('testprojects/src/antlr', page, java_antlr_library, python_antlr_library)
source_root('testprojects/src/java', annotation_processor, jvm_binary, java_library, jar_library, page)
source_root('testprojects/src/protobuf', java_protobuf_library, jar_library, page)
source_root('testprojects/src/scala', jvm_binary, page, scala_library, benchmark)
source_root('testprojects/src/thrift', java_thrift_library, page, python_thrift_library)

source_root('testprojects/tests/java', java_library, junit_tests, page, jar_library)
source_root('testprojects/tests/python', page, python_library, python_tests, python_test_suite, python_binary, resources)
source_root('testprojects/tests/resources', page, resources)
source_root('testprojects/tests/scala', page, junit_tests, scala_library, scala_specs)

# Example code intended to demonstrate to end users how to use Pants BUILD configuration
source_root('examples/src/android', page, android_resources, android_binary)
source_root('examples/src/antlr', page, java_antlr_library, python_antlr_library)
source_root('examples/src/java', annotation_processor, jvm_binary, java_library, page)
source_root('examples/src/protobuf', java_protobuf_library, jar_library, unpacked_jars, page)
source_root('examples/src/python', page, python_binary, python_library, resources)
source_root('examples/src/resources', page, resources, jaxb_library)
source_root('examples/src/scala', jvm_binary, page, scala_library, benchmark)
source_root('examples/src/thrift', java_thrift_library, page, python_thrift_library)
source_root('examples/src/wire', java_wire_library, page)

source_root('examples/tests/java', java_library, junit_tests, page)
source_root('examples/tests/python', page, python_library, python_tests, python_test_suite, python_binary, resources)
source_root('examples/tests/resources', page, resources)
source_root('examples/tests/scala', page, junit_tests, scala_library, scala_specs)


page(name="readme", source="README.md")
