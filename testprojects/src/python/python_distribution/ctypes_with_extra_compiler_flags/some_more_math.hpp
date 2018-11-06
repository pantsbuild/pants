#ifndef __SOME_MORE_MATH_HPP__
#define __SOME_MORE_MATH_HPP__

#ifdef _ASDF
    #if _ASDF == 0
        #define SOMETHING 800000
    #else
        #define SOMETHING 100000
    #endif
#else
    #define SOMETHING -1
#endif

int mangled_function(int);

extern "C" int multiply_by_something(int);

#endif
