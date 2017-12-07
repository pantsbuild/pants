# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

android_library(
    include_patterns = [
        "android/**/*.class",
    ],
    libraries = ["contrib/android/examples/3rdparty/android:android-support-v4"],
    manifest = "AndroidManifest.xml",
    dependencies = [
        ":gms-library",
        ":resources",
    ],
)

android_resources(
    name = "resources",
    manifest = "AndroidManifest.xml",
    resource_dir = "res",
)

android_library(
    name = "gms-library",
    include_patterns = [
        "**/*.class",
    ],
    libraries = ["contrib/android/examples/3rdparty/android:google-play-services"],
    dependencies = [
    ],
)
