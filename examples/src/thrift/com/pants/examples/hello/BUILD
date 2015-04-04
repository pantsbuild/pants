java_thrift_library(name='hello',
  sources=globs('*.thrift'),
  provides = artifact(org='com.twitter',
                      name='hello-java',
                      repo=public),
  dependencies = [
   'examples/src/thrift/com/pants/examples/person'
  ]
)
