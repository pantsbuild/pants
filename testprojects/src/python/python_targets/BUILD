# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(name="binary_file", sources=["test_binary.py"], dependencies=[":test_library"])

pex_binary(name="test_binary", entry_point="test_binary.py", dependencies=[":binary_file"])

python_sources(name="test_library", sources=["test_library.py"])

python_sources(
    name="test_library_direct_dependee",
    sources=["test_direct_dependee.py"],
    dependencies=[":test_library"],
)

python_sources(
    name="test_library_transitive_dependee",
    sources=["test_library_transitive_dependee.py"],
    dependencies=[":test_library_direct_dependee"],
)

python_sources(
    name="test_library_transitive_dependee_2",
    sources=["test_library_transitive_dependee_2.py"],
    dependencies=[":test_library_transitive_dependee"],
)
