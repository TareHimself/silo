#include <cstdio>
#include <zlib.h>

const char* greeting();

int main() {
    std::printf("%s, linked against zlib %s\n", greeting(), zlibVersion());
    return 0;
}
