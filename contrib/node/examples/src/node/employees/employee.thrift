namespace js gen.employees.thriftjs

include "employee-dep/dep.thrift"

struct employee {
  1: required dep.Name name;
}