# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='test-application',
  basename='test-application',
  source='Application.java',
  main='com.twitter.common.application.Application',
  dependencies=[
    pants('3rdparty/jvm/com/twitter/common:application'),
    pants('3rdparty/jvm/com/twitter/common:base'),
  ],
)

