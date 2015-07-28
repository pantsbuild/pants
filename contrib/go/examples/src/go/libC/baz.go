package libC

import (
  "fmt"

  "contrib/go/examples/src/go/libB"
)

func Baz() {
  fmt.Println("Baz from libC!")
  libB.Bar()
}