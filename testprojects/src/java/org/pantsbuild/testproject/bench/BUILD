benchmark(
  dependencies=[':caliper'],
  sources=['CaliperBench.java']
)

jar_library(
  name= 'caliper',
  jars=[
    jar(org='com.google.caliper', name='caliper', rev='0.5-rc1', excludes=[
      exclude(org='com.google.guava', name='guava'),
    ]),
  ],
)

java_library(name='jmh',
  dependencies=[
    '3rdparty/jvm/org/openjdk/jmh:jmh',
  ],
  sources=['JmhBench.java'],
  # Turn off zinc provided file manager, incompatible with jmh.
  # See https://github.com/sbt/zinc/issues/185
  zinc_file_manager=False,
)
