# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='shading',
  main='org.pantsbuild.testproject.shading.Main',
  basename='shading',
  dependencies=[
    ':lib',
  ],
  shading_rules=[
    shading_exclude('org.pantsbuild.testproject.shadingdep.PleaseDoNotShadeMe'),
    shading_relocate('org.pantsbuild.testproject.shadingdep.otherpackage.ShadeWithTargetId'),
    shading_relocate('org.pantsbuild.testproject.shadingdep.CompletelyRename',
                     'org.pantsbuild.testproject.foo.bar.MyNameIsDifferentNow'),
    shading_relocate_package('org.pantsbuild.testproject.shadingdep'),
    shading_relocate('org.pantsbuild.testproject.shading.ShadeSelf')
  ],
)

java_library(name='lib',
  dependencies=[
    'testprojects/src/java/org/pantsbuild/testproject/shadingdep/otherpackage',
    'testprojects/src/java/org/pantsbuild/testproject/shadingdep/subpackage',
    'testprojects/src/java/org/pantsbuild/testproject/shadingdep:lib',
    'testprojects/src/java/org/pantsbuild/testproject/shadingdep:other',
  ],
  sources=[
    'Main.java',
    'ShadeSelf.java',
  ],
)

java_library(name='third_lib',
  sources=[
    'Third.java',
    'Second.java',
  ],
  platform='java7',
  dependencies=[
    '3rdparty:gson',
  ],
)

jvm_binary(name='third',
  basename='third',
  main='org.pantsbuild.testproject.shading.Third',
  platform='java7',
  dependencies=[
    ':third_lib',
  ],
  shading_rules=[
    shading_exclude('org.pantsbuild.testproject.shading.Third'),
    shading_relocate_package('org.pantsbuild', shade_prefix='hello.'),
    shading_relocate('com.google.gson.**', shade_pattern='moc.elgoog.nosg.@1'),
  ],
)
