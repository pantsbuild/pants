package bar

import "testing"

func TestQuote(t *testing.T) {
	if Quote("hi") != ">> hi <<" {
		t.Fail()
	}
}
