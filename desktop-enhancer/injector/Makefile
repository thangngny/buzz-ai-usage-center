CC ?= gcc
CFLAGS ?= -shared -fPIC -O2 -Wall -Wextra
LDFLAGS ?= -ldl

TARGET = libbuzz_enhancer.so
SRC = libbuzz_enhancer.c

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) $(SRC) -o $(TARGET) $(LDFLAGS)

clean:
	rm -f $(TARGET)

.PHONY: all clean
