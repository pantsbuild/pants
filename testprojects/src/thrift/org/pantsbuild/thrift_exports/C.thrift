namespace java org.pantsbuild.thrift_exports.thriftjava
#@namespace scala org.pantsbuild.thrift_exports.thriftscala

include "org/pantsbuild/thrift_exports/B.thrift"

struct FooC {
  1: B.FooB foo_b
}(persisted='true')
