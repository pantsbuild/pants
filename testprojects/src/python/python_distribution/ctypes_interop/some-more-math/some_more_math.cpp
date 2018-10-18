#ifdef __cplusplus
extern "C" {
#endif
#include "some_math.h"
#ifdef __cplusplus
}
#endif
#include "some_more_math.hpp"

int mangled_function(int x) { return add_two(x) ^ 3; }

extern "C" int multiply_by_three(int x) { return mangled_function(x * 3); }
