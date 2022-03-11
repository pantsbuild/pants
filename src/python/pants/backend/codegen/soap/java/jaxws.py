# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.util.docutil import git_url


class JaxWsTools(JvmToolBase):
    options_scope = "jaxws"
    help = "The JAX-WS Import tool (https://javaee.github.io/metro-jax-ws/)"

    default_version = "2.3.5"
    default_artifacts = ("com.sun.xml.ws:jaxws-tools:{version}",)
    default_lockfile_resource = (
        "pants.backend.codegen.soap.java",
        "jaxws.default.lockfile.txt",
    )
    default_lockfile_path = "pants/backend/codegen/soap/java/jaxws.default.lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
