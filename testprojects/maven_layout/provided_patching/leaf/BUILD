# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Here we have three modules, each module with its own version of 'Common.java' and 'Shadow.java'.
# The purpose of this is to demonstrate that we can mix and match classes from different modules,
# and that the appropriate behavior is observed at compile-time and runtime. The 'Common.java' files
# just reference their Shadow counterparts, to demonstrate what happens when the Shadow class does
# not match up with what the Common class expects.

jvm_binary(name='one',
  source='src/main/java/org/pantsbuild/testproject/provided_patching/UseShadow.java',
  main='org.pantsbuild.testproject.provided_patching.UseShadow',
  dependencies=[
    'testprojects/maven_layout/provided_patching/two/src/main/java:common',
    'testprojects/maven_layout/provided_patching/one/src/main/java:shadow',
  ],
)

jvm_binary(name='two',
  source='src/main/java/org/pantsbuild/testproject/provided_patching/UseShadow.java',
  main='org.pantsbuild.testproject.provided_patching.UseShadow',
  dependencies=[
    'testprojects/maven_layout/provided_patching/three/src/main/java:common',
    'testprojects/maven_layout/provided_patching/two/src/main/java:shadow',
  ],
)

jvm_binary(name='three',
  source='src/main/java/org/pantsbuild/testproject/provided_patching/UseShadow.java',
  main='org.pantsbuild.testproject.provided_patching.UseShadow',
  dependencies=[
    'testprojects/maven_layout/provided_patching/one/src/main/java:common',
    'testprojects/maven_layout/provided_patching/three/src/main/java:shadow',
  ],
)

jvm_binary(name='fail',
  source='src/main/java/org/pantsbuild/testproject/provided_patching/UseShadow.java',
  main='org.pantsbuild.testproject.provided_patching.UseShadow',
  dependencies=[
    'testprojects/maven_layout/provided_patching/one/src/main/java:common',
  ],
)

java_tests(name='test',
  sources=[
    'src/test/java/org/pantsbuild/testproject/provided_patching/ShadowTest.java',
  ],
  dependencies=[
    '3rdparty:junit',
    'testprojects/maven_layout/provided_patching/one/src/main/java:common',
    'testprojects/maven_layout/provided_patching/three/src/main/java:common',
    provided('testprojects/maven_layout/provided_patching/two/src/main/java:shadow'),
  ],
)
