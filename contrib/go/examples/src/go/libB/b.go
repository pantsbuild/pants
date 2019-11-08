package libB

import (
	"libD"
)

func SpeakPrologue() string {
	return "Hello from libB!"
}

func SpeakEpilogue() string {
	return "Bye from libB!"
}

func Speak() {
	println(SpeakPrologue())
	libD.Speak()
	println(SpeakEpilogue())
}
