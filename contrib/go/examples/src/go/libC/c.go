package libC

import (
	"libD"
	"libE"
)

func Speak() {
	println("Hello from libC!")
	libD.Speak()
	libE.Speak()
	println("Bye from libC!")
}
