#include "some_more_math.hpp"
#include <assert.h>

int mangled_function(int x) {
  double y = -1.0;
  assert(y >= 0.0);
  return x ^ 3;
}

extern "C" int multiply_by_three(int x) { return mangled_function(x * 3); }
