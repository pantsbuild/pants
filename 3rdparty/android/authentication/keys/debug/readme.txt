# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


!!! Please do not put release keystore or passwords into BUILD.debug or any 'debug' namespace !!!

The debug.keystore definition is in the BUILD.debug file found at
3rdparty/android/authenticationBUILD.debug.

This debug key was generated with the following well-known definition:

    keytool -genkey -v -keystore debug.keystore -storepass android -alias \
    androiddebugkey -keypass android -keyalg RSA -keysize 2048 -validity 10000
