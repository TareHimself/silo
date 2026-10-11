#include <iostream>
#include <memory>

#include <webmdx/FileSource.h>
#include <webmdx/SourceDecoder.h>

int main(int argc, char **argv) {
    wdx::SourceDecoder decoder;
    if (argc < 2) {
        std::cout << "webmdx is linked. Pass a .webm file to read it.\n";
        return 0;
    }
    decoder.SetSource(std::make_shared<wdx::FileSource>(argv[1]));
    std::cout << decoder.GetDuration() << " seconds, " << decoder.GetVideoTrackCount()
              << " video and " << decoder.GetAudioTrackCount() << " audio tracks\n";
    return 0;
}
