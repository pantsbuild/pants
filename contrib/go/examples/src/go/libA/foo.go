package libA

import (
  "fmt"
)

func Foo() {
  fmt.Println("Foo from libA!")
}

func Add(a int, b int) int {
  return a + b
}