# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

!!! Please do not put a release keystore or password into BUILD.debug or any 'debug' namespace !!!

To safely keep release keystores and passwords out of vcs, create a BUILD.release file in
this directory and fill out a build definition like below.

keystore(
  name='release',
  build_type='release',
  source='my-release-key.keystore',
  keystore_alias='alias_name',
  keystore_password='store_password',
  key_password='key_password'
)

Neither the BUILD.release nor any new 3rdparty/android/authentication/release files
will be added to git.