#include "some_more_math.hpp"
#include <assert.h>

int mangled_function(int x) {
  return x * SOMETHING;
}

extern "C" int multiply_by_something(int x) { return mangled_function(x * 3); }
