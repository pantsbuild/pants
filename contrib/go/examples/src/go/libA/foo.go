package libA

import (
  "fmt"

  "github.com/fatih/set"
)

func Foo() {
  fmt.Println("Foo from libA!")
}

func Add(a int, b int) int {
  return a + b
}

func SetSize(s *set.Set) int {
  return s.Size()
}