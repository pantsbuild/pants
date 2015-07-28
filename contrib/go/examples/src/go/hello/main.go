package main

import (
  "fmt"

  "contrib/go/examples/src/go/libC"
)

func main() {
  fmt.Println("Hello, world!")
  libC.Baz()
  panic("AAAAAAAAAHHHHHH")
}