#include "some_more_math.hpp"
#include "rang.hpp"

int mangled_function(int x) {
	std::cout << "Plain text\n"
         << rang::style::bold << "Text from 3rdparty!"
         << rang::style::reset << std::endl;
	return x ^ 3;
}

extern "C" int multiply_by_three(int x) { return mangled_function(x * 3); }
