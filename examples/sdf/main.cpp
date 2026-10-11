#include <cstdio>

#include <msdfgen.h>
#include <msdfgen-ext.h>

// Usage: sdf <font file> <output.png>
int main(int argc, char** argv) {
    if (argc != 3) {
        std::puts("usage: sdf <font file> <output.png>");
        return 2;
    }
    msdfgen::FreetypeHandle* freetype = msdfgen::initializeFreetype();
    msdfgen::FontHandle* font = freetype ? msdfgen::loadFont(freetype, argv[1]) : nullptr;
    msdfgen::Shape shape;
    if (!font || !msdfgen::loadGlyph(shape, font, 'A', msdfgen::FONT_SCALING_EM_NORMALIZED)) {
        std::puts("could not load the glyph");
        return 1;
    }
    shape.normalize();
    msdfgen::edgeColoringSimple(shape, 3.0);
    msdfgen::Bitmap<float, 3> distance_field(32, 32);
    msdfgen::SDFTransformation transformation(
        msdfgen::Projection(32.0, msdfgen::Vector2(0.125, 0.125)), msdfgen::Range(0.125));
    msdfgen::generateMSDF(distance_field, shape, transformation);
    bool saved = msdfgen::savePng(distance_field, argv[2]);
    std::printf("%d contours, png %s\n", int(shape.contours.size()), saved ? "saved" : "failed");
    msdfgen::destroyFont(font);
    msdfgen::deinitializeFreetype(freetype);
    return saved ? 0 : 1;
}
