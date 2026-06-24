package directives

/*
#include <stdio.h>

int addNumbers(int a, int b) {
  return a + b;
}

#cgo nocallback addNumbers
#cgo noescape addNumbers
*/
import "C"

func AddNumbersInC(a, b int) int {
	return int(C.addNumbers(C.int(a), C.int(b)))
}
