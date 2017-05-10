namespace java org.pantsbuild.thrift_exports.thriftjava
#@namespace scala org.pantsbuild.thrift_exports.thriftscala

include "org/pantsbuild/thrift_exports/A.thrift"

struct FooB {
  1: i64 id,
  2: optional A.FooA foo_a
}(persisted='true')
