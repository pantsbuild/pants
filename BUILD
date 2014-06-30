# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

source_root('src/android', page, android_resources, android_binary)
source_root('src/antlr', page, java_antlr_library, python_antlr_library)
source_root('src/java', annotation_processor, jvm_binary, java_library, page)
source_root('src/protobuf', java_protobuf_library, page)
source_root('src/python', page, python_binary, python_library, resources)
source_root('src/resources', page, resources, jaxb_library)
source_root('src/scala', jvm_binary, page, scala_library)
source_root('src/thrift', java_thrift_library, page, python_thrift_library)

source_root('tests/java', java_library, junit_tests, page)
source_root('tests/python', page, python_library, python_tests, python_test_suite, python_binary, resources)
source_root('tests/resources', page, resources)
source_root('tests/scala', page, junit_tests, scala_library, scala_specs)

page(name="readme",
  source="README.md")
