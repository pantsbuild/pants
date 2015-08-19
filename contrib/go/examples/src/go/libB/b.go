package libB

import (
  "libD"
)

func Speak() {
	println("Hello from libB!")
  libD.Speak()
  println("Bye from libB!")
}
