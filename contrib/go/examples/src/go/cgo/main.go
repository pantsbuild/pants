package main

/*
#include <stdlib.h>
*/
import "C"

import "fmt"

func main() {
	fmt.Printf("Random from C: %d", int(C.random()))
}
