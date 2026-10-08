from enum import Enum


class BuildMode(Enum):
    Debug = "debug"
    Release = "release"


class Compiler(Enum):
    Clang = "clang"
    AppleClang = "apple_clang"
    GCC = "gcc"
    MSVC = "msvc"


class Platform(Enum):
    Windows = "windows"
    Linux = "linux"
    Darwin = "macos"


class Architecture(Enum):
    X86_64 = "x86_64"
    X86 = "x86"
    ARM64 = "arm64"
    ARM = "arm"
