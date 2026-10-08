#include <cstdio>

#include <ft2build.h>
#include FT_FREETYPE_H

const char* greeting();

int main() {
    FT_Library library;
    if (FT_Init_FreeType(&library) != 0) {
        return 1;
    }
    FT_Int major, minor, patch;
    FT_Library_Version(library, &major, &minor, &patch);
    std::printf("%s, linked against freetype %d.%d.%d\n", greeting(), major, minor, patch);
    FT_Done_FreeType(library);
    return 0;
}
