package libA

import (
  "contrib/go/examples/src/go/libB"
  "contrib/go/examples/src/go/libC"
)

func Speak() {
  println("Hello from libA!")
  libB.Speak()
  libC.Speak()
  println("Bye from libA!")
}

func Add(a int, b int) int {
  return a + b
}