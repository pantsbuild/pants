package main

import (
	"fmt"
	"github.com/pantsbuild/pants/testprojects/src/go/pants_test/bar"
	"os"
)

func main() {
	for i, arg := range os.Args {
		fmt.Printf("arg[%d] = %s\n", i, bar.Quote(arg))
	}
}
