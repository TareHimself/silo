#include <cstdio>

#include <vpx/vp8dx.h>
#include <vpx/vpx_decoder.h>

int main() {
    std::printf("libvpx %s, decoder %s\n", vpx_codec_version_str(),
                vpx_codec_iface_name(vpx_codec_vp9_dx()));
    return 0;
}
