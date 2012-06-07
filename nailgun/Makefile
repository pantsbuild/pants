
CC=gcc
CFLAGS=-Wall -pedantic -s -O3

ng: src/c/ng.c
	@echo "Building ng client"
	mkdir target
	${CC} ${CFLAGS} -o target/ng src/c/ng.c

clean:
	rm -rf target
