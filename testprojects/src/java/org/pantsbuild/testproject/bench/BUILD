benchmark(name='bench',
          dependencies=[':caliper'],
          sources=['CaliperBench.java'])

jar_library(
  name= 'caliper',
  jars=[
    jar(org='com.google.caliper', name='caliper', rev='0.5-rc1', excludes=[
      exclude(org='com.google.guava', name='guava'),
    ]),
  ],
)