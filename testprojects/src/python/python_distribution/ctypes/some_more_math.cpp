#include "some_more_math.hpp"

int mangled_function(int x) { return x ^ 3; }

extern "C" int multiply_by_three(int x) { return mangled_function(x * 3); }
