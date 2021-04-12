package main

import (
	"fmt"
	"os"

	"github.com/toolchainlabs/toolchain/src/go/src/toolchain/pants_test/bar"
)

func main() {
	for i, arg := range os.Args {
		fmt.Printf("arg[%d] = %s\n", i, bar.Quote(arg))
	}
}
