java_library(name='example',
  sources=['Example.java'],
  dependencies=[
    '3rdparty:autovalue',
  ],
)


jvm_binary(
  name='example_bin',
  dependencies=[
    ':example',
  ],
  source='Main.java',
  main='com.pants.examples.autovalue.example.Main',
)
