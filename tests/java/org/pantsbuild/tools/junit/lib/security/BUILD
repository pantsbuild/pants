java_library(
  name='test-dep',
  # We need to use explicit sources here since we want to own both library code in this directory
  # and code that looks like tests.
  sources=['**/*.java'],
  dependencies=[
    '3rdparty/jvm/com/squareup/burst:burst-junit4',
    '3rdparty:guava',
    '3rdparty:junit',
    '3rdparty/jvm/org/hamcrest:hamcrest-core',
    '3rdparty/jvm/org/mockito:mockito-core',
    'src/java/org/pantsbuild/junit/annotations',
    'src/java/org/pantsbuild/tools/junit',
  ],
)
