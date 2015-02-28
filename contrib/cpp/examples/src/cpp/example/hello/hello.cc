#include <iostream>

#include "hello.h"

namespace example {
namespace hello {

Hello::Hello() {
  std::cout << "Hello, pants!\n";
}

Hello::~Hello() {
  std::cout << "Goodbye, pants!\n";
}

}  // namespace hello
}  // namespace example
