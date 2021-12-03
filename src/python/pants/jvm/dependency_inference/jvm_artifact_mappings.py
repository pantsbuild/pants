# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

JVM_ARTIFACT_MAPPINGS = {
    "aQute.bnd.**": "biz.aQute:bnd",
    "com.fasterxml.jackson.databind.**": "com.fasterxml.jackson.core:jackson-databind",
    "com.google.common.collect.**": "com.google.guava:guava",
    "com.google.common.testing.**": "com.google.guava:guava-testlib",
    "com.google.common.truth.**": "com.google.truth:truth",
    "javax.inject.**": "javax.inject:javax.inject",
    "junit.framework.**": "junit:junit",
    "org.aopalliance.**": "aopalliance:aopalliance",
    "org.atinject.tck.**": "javax.inject:javax.inject-tck",
    "org.junit.**": "junit:junit",
    "org.objectweb.asm.**": "org.ow2.asm:asm",
    "org.osgi.framework.**": "org.osgi:osgi.core",
    "org.springframework.beans.**": "org.springframework:spring-beans",
}
