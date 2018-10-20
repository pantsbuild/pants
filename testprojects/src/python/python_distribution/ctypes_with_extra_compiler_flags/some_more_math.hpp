#ifndef __SOME_MORE_MATH_HPP__
#define __SOME_MORE_MATH_HPP__

#ifdef NDEBUG
#define assert(condition) ((void)0)
#else
#define assert(condition)
#endif

int mangled_function(int);

extern "C" int multiply_by_three(int);

#endif
