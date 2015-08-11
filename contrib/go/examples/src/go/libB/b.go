package libB

import (
  "contrib/go/examples/src/go/libD"
)

func Speak() {
	println("Hello from libB!")
  libD.Speak()
  println("Bye from libB!")
}
