#include <filesystem>
#include <fstream>

int main(int argc, char** argv) {
    if (argc != 2) {
        return 1;
    }
    std::filesystem::path header{argv[1]};
    std::filesystem::create_directories(header.parent_path());
    std::ofstream{header} << "#define ZAPP_GREETING \"hello from zapp\"\n";
    return 0;
}
