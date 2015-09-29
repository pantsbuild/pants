#@namespace android thrift.android.test

include "contrib/scrooge/examples/src/thrift/org/pantsbuild/contrib/scrooge/dummy_generator/dummy.thrift"

typedef i32 MyInteger

enum Day {
  Mon = 1,
  Tue = 2,
}

struct Other {
}

struct Work {
  1: i32 num1 = 0,
  2: MyInteger num2,
  3: optional string comment,
  4: set<binary> test_set,
  5: double d1,
  6: map<string, string> test_map,
  7: binary test_binary,
  8: required i64 req_int,
  9: required Day day = 1,
  10: required Other other,
  11: list<string> test_list,
  12: required list<i64> user_ids,
  13: list<Other> other_list,
  14: required dummy.Krow krow,
}
