package libB

import (
	"testing"
)

func TestSpeak(t *testing.T) {
	got, exp := SpeakPrologue(), "Hello from libB!"
	if got != exp {
		t.Fatalf("got: %d, expected: %d", got, exp)
	}
	got2, exp2 := SpeakEpilogue(), "Bye from libB!"
	if got2 != exp2 {
		t.Fatalf("got: %d, expected: %d", got2, exp2)
	}
}
