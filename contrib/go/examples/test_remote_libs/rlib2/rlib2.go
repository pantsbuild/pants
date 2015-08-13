package rlib2

import (
  "fmt"

  "github.com/fakeuser/rlib3"
)

func Speak() {
  fmt.Println("Hello from rlib2!")
  rlib3.Speak()
  fmt.Println("Bye from rlib2!")
}