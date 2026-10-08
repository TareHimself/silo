from silo.enums import BuildMode
from silo.platform import backend_for
from silo.silo_package import SiloPackage
from silo.tools.cmake.cmake_deps import write_dependency_configs

CacheValue = str | bool | int

# Make find_package() see silo's generated configs and nothing registered on the machine.
# PREFER_CONFIG matters because CMake otherwise tries its own FindZLIB-style modules first.
ISOLATION: dict[str, CacheValue] = {
    "CMAKE_FIND_USE_PACKAGE_REGISTRY": False,
    "CMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY": False,
    "CMAKE_FIND_USE_CMAKE_SYSTEM_PATH": False,
    "CMAKE_FIND_PACKAGE_PREFER_CONFIG": True,
}


def _cache_argument(key: str, value: CacheValue) -> str:
    if isinstance(value, bool):
        value = "ON" if value else "OFF"
    return f"-D{key}={value}"


class CMakeBuild:
    def __init__(self, package: SiloPackage) -> None:
        self.package = package

    def configure(self, **cache: CacheValue) -> None:
        context = self.package.context
        profile = context.profile
        backend = backend_for(profile.settings.os)
        is_debug = context.build_type is BuildMode.Debug
        compiler = profile.compiler.executable.as_posix()

        entries: dict[str, CacheValue] = {
            "CMAKE_BUILD_TYPE": "Debug" if is_debug else "Release",
            "CMAKE_INSTALL_PREFIX": context.install_prefix,
            "CMAKE_C_COMPILER": compiler,
            "CMAKE_CXX_COMPILER": compiler,
            **ISOLATION,
            **backend.cmake_cache_entries(profile),
        }
        if is_debug and not self.package.is_c_only:
            defines = backend.hardening_defines(profile)
            # _INIT adds to CMake's default flags, where CMAKE_CXX_FLAGS would replace them
            entries["CMAKE_CXX_FLAGS_INIT"] = " ".join(f"-D{define}" for define in defines)
        configs_dir = context.generated_dir / "cmake"
        write_dependency_configs(
            context.dependency_packages, configs_dir, context.dependency_aliases
        )
        entries["CMAKE_PREFIX_PATH"] = configs_dir.as_posix()
        entries |= cache
        self.package.run(
            ["cmake", "-S", context.source_dir, "-B", context.build_dir, "-G", "Ninja"]
            + [_cache_argument(key, value) for key, value in entries.items()]
        )

    def build(self) -> None:
        self.package.run(["cmake", "--build", self.package.build_dir])

    def install(self) -> None:
        # The prefix is a sentinel, so DESTDIR is what puts the files in the stage dir
        self.package.run(
            ["cmake", "--install", self.package.build_dir],
            env={"DESTDIR": str(self.package.context.stage_dir)},
        )
