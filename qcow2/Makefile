PREFIX ?= /opt/xensource/libexec
DESTDIR ?=
DEBUGDIR ?= /opt/xensource/debug


OPTS := -D _GNU_SOURCE -D_FILE_OFFSET_BITS=64 -D_LARGEFILE64_SOURCE -Wall -fopenmp -Ofast

SRC := qcow2_helper.c

BIN := qcow2_helper

all: qcow2_helper

qcow2_helper: qcow2_helper.c
	$(CC) $(OPTS) $(SRC) -o $(BIN)

install: install_qcow2_helper

install_qcow2_helper: qcow2_helper
	mkdir -p $(DESTDIR)$(PREFIX)
	install -m 755 $^ $(DESTDIR)$(PREFIX)

clean:
	rm -f qcow2_helper
