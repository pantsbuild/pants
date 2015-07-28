package libB

import (
  "fmt"

  "contrib/go/examples/src/go/libA"
)

func Bar() {
	fmt.Println("Bar from libB!")
  libA.Foo()
}
