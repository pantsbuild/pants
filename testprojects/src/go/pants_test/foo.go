package main

import (
	"fmt"
	"os"
	"github.com/pantsbuild/pants/testprojects/src/go/pants_test/bar"
)

func main() {
	for i, arg := range os.Args {
		fmt.Printf("arg[%d] = %s\n", i, bar.Quote(arg))
	}
}
