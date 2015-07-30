package main

import (
  "flag"
  "fmt"

  "contrib/go/examples/src/go/libC"
)

func main() {
  n := flag.Int("n", 1, "print message n times")
  flag.Parse()
  for i := 0; i < *n; i++ {
    fmt.Println("Hello, world!")
  }
  libC.Baz()
}