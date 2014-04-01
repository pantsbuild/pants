# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='main',
  basename='pingpong',
  source='Main.java',
  main='com.pants.examples.pingpong.main.Main',
  dependencies=[
    pants('3rdparty:guava'),
    pants('3rdparty:guice'),
    pants('3rdparty/jvm/com/sun/jersey:jersey-client'),
    pants('3rdparty/jvm/com/sun/jersey:jersey-core'),
    pants('3rdparty/jvm/com/sun/jersey:jersey-guice'),
    pants('3rdparty/jvm/com/sun/jersey:jersey-server'),
    pants('3rdparty/jvm/com/sun/jersey:jersey-servlet'),
    pants('src/java/com/pants/examples/pingpong/handler'),
    pants('src/java/com/twitter/common/application'),
    pants('src/java/com/twitter/common/application/http'),
    pants('src/java/com/twitter/common/application/modules:http'),
    pants('src/java/com/twitter/common/application/modules:lifecycle'),
    pants('src/java/com/twitter/common/application/modules:log'),
    pants('src/java/com/twitter/common/application/modules:stats'),
    pants('src/java/com/twitter/common/args'),
  ]
)
