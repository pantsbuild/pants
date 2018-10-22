#include "some_more_math.hpp"
#include <assert.h>

int mangled_function(int x) {
  double y = -1.0;
  assert(y >= 0.0);
  return x * SOMETHING;
}

extern "C" int multiply_by_something(int x) { return mangled_function(x * 3); }
