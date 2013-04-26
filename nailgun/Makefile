# This Makefile has only been tested on linux.  It uses
# MinGW32 to cross-compile for windows.  To install and
# configure MinGW32 on linux, see http://www.mingw.org

# mingw32 compiler
# On Ubuntu 8.04 this is at:
# WIN32_CC=/usr/bin/i586-mingw32msvc-gcc
WIN32_CC=mingw32-gcc

CC=gcc
CFLAGS=-Wall -pedantic -s -O3
SRCDIR=src/c

ng: ${SRCDIR}/ng.c
	@echo "Building ng client.  To build a Windows binary, type 'make ng.exe'"
	${CC} ${CFLAGS} -o ng ${SRCDIR}/ng.c

install: ng
	install ng /usr/local/bin

ng.exe: ${SRCDIR}/ng.c
	${WIN32_CC} -o ng.exe ${SRCDIR}/ng.c -lwsock32 -O3 ${CFLAGS}
# any idea why the command line is so sensitive to the order of
# the arguments?  If CFLAGS is at the beginning, it won't link.

clean:
	@echo ""
	@echo "If you have a Windows binary, 'make clean' won't delete it."
	@echo "You must remove this manually.  Most users won't have MinGW"
	@echo "installed - so I'd rather not delete something you can't rebuild."
	@echo ""
	rm -f ng
#	rm -f ng.exe
