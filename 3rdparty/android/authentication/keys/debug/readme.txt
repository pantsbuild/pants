# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


!!! Please do not put release keystores or passwords into BUILD.debug or any 'debug' namespace !!!

The debug.keystore BUILD definition is in the BUILD.debug file found at
3rdparty/android/authenticationBUILD.debug.

This debug key was generated with the following well-known definition:

    keytool -genkeypair -alias androiddebugkey -keypass android \
        -keystore debug.keystore -storepass android \
        -dname "CN=Android Debug,O=Android,C=US" -validity 9999
