package libA

import (
  "libB"
  "libC"
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
