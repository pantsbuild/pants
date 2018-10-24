#include "some_math.h"
#include "some_more_math.hpp"
#include "wrapped_math.h"

int wrapped_function(int x) { return add_two(multiply_by_three(x)); };
