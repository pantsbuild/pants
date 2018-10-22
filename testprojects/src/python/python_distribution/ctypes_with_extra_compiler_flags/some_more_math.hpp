#ifndef __SOME_MORE_MATH_HPP__
#define __SOME_MORE_MATH_HPP__

#ifdef NDEBUG
#define assert(condition) ((void)0)
#else
#define assert(condition)
#endif

#ifdef _GLIBCXX_USE_CXX11_ABI
#if _GLIBCXX_USE_CXX11_ABI == 0
#define SOMETHING 800000
#else
#define SOMETHING 1
#endif
#endif

int mangled_function(int);

extern "C" int multiply_by_something(int);

#endif
