package bar

import "github.com/google/uuid"

func GenUuid() string {
	return uuid.NewString()
}

func Quote(s string) string {
	return ">> " + s + " <<"
}
