# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
    dependencies = [
        ":node_preinstalled_module_resolver",
        ":npm_resolver",
    ],
)

python_library(
    name = "npm_resolver",
    sources = ["npm_resolver.py"],
    dependencies = [
        ":node_resolver_base",
        "contrib/node/src/python/pants/contrib/node/targets:node_module",
        "contrib/node/src/python/pants/contrib/node/tasks:node_resolve",
        "src/python/pants/base:exceptions",
        "src/python/pants/base:workunit",
        "src/python/pants/subsystem",
        "src/python/pants/util:contextutil",
    ],
)

python_library(
    name = "node_preinstalled_module_resolver",
    sources = ["node_preinstalled_module_resolver.py"],
    dependencies = [
        ":node_resolver_base",
        "3rdparty/python:six",
        "contrib/node/src/python/pants/contrib/node/targets:node_preinstalled_module",
        "contrib/node/src/python/pants/contrib/node/tasks:node_resolve",
        "src/python/pants/base:build_environment",
        "src/python/pants/base:exceptions",
        "src/python/pants/fs",
        "src/python/pants/subsystem",
        "src/python/pants/util:contextutil",
        "src/python/pants/util:dirutil",
    ],
)

python_library(
    name = "node_resolver_base",
    sources = ["node_resolver_base.py"],
    dependencies = [
        "src/python/pants/base:build_environment",
        "src/python/pants/util:dirutil",
        "src/python/pants/util:meta",
    ],
)
