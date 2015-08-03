package libC

import (
  "contrib/go/examples/src/go/libD"
  "contrib/go/examples/src/go/libE"
)

func Speak() {
  println("Hello from libC!")
  libD.Speak()
  libE.Speak()
  println("Bye from libC!")
}