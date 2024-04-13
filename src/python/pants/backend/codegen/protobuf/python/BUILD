# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])
resources(name="lockfile", sources=["mypy_protobuf.lock", "grpclib.lock"])
resource(name="test_lockfile", source="test_grpc_pre_v2_mypy_plugin.lock")

python_tests(
    name="python_protobuf_module_mapper_test", sources=["python_protobuf_module_mapper_test.py"]
)
python_tests(name="python_protobuf_subsystem_test", sources=["python_protobuf_subsystem_test.py"])
python_tests(
    name="rules_integration_test",
    sources=["rules_integration_test.py"],
    dependencies=[":test_lockfile"],
    timeout=330,
    # We want to make sure the default lockfile for MyPy Protobuf works for both macOS and Linux.
    tags=["platform_specific_behavior"],
)
