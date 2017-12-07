# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_app(
    basename = "bundle-example",
    binary = ":bundle-bin",
    bundles = [
        bundle(fileset = globs("data/*")),
    ],
)

jvm_app(
    name = "mapper",
    binary = ":bundle-bin",
    bundles = [
        bundle(
            fileset = globs("a/b/*"),
            mapper = DirectoryReMapper("testprojects/src/java/org/pantsbuild/testproject/bundle/a/b", "bundle_files"),
        ),
    ],
)

jvm_app(
    name = "relative_to",
    binary = ":bundle-bin",
    bundles = [
        bundle(
            fileset = globs("a/b/*"),
            relative_to = "a",
        ),
    ],
)

jvm_app(
    name = "rel_path",
    binary = ":bundle-bin",
    bundles = [
        bundle(
            fileset = ["b/file1.txt"],
            rel_path = "testprojects/src/java/org/pantsbuild/testproject/bundle/a",
        ),
    ],
)

jvm_app(
    name = "directory",
    binary = ":bundle-bin",
    bundles = [
        bundle(
            fileset = ["a/b"],
        ),
    ],
)

jvm_app(
    name = "explicit_recursion",
    binary = ":bundle-bin",
    bundles = [
        bundle(
            fileset = ["a/**/*"],
        ),
    ],
)

# The binary, the "runnable" part:

jvm_binary(
    name = "bundle-bin",
    basename = "bundle-example-bin",
    main = "org.pantsbuild.testproject.bundle.BundleMain",
    source = "BundleMain.java",
    dependencies = [
        "3rdparty:guava",
        "testprojects/src/resources/org/pantsbuild/testproject/bundleresources:resources",
    ],
)

# This should fail because the relpath is wrong
jvm_app(
    name = "missing-files",
    basename = "bundle-example",
    binary = ":bundle-bin",
    bundles = [
        bundle(fileset = ["data/no-such-file"]),
    ],
)

# Tests resources ordering via integration test.
jvm_binary(
    name = "bundle-resource-ordering",
    main = "org.pantsbuild.testproject.bundle.BundleMain",
    source = "BundleMain.java",
    dependencies = [
        "3rdparty:guava",
        "testprojects/src/resources/org/pantsbuild/testproject/bundleresources:resources",
        "testprojects/tests/resources/org/pantsbuild/testproject/bundleresources:resources",
    ],
)
