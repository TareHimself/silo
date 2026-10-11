import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from silo.enums import BuildMode
from silo.platform import backend_for
from silo.silo_package import SiloPackage
from silo.tools.cmake.cmake_generator import TOOLCHAIN_FILE, CMakeGenerator

PRESETS_FILE = "CMakePresets.json"
# The oldest preset format with ${fileDir}, which CMake 3.25 and later read
PRESETS_VERSION = 6

CacheValue = str | bool | int


@dataclass
class Preset:
    """One configure preset with the build and test presets that go with it.

    `cache` and `environment` cover the common needs. Anything else CMake accepts in a
    preset goes straight into `configure`, `build` or `test`.
    """

    name: str
    cache: dict[str, CacheValue] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    configure: dict[str, Any] = field(default_factory=dict)
    build: dict[str, Any] = field(default_factory=dict)
    test: dict[str, Any] = field(default_factory=dict)


def _cache_text(value: CacheValue) -> str:
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    return str(value)


def base_preset_name(build_type: BuildMode) -> str:
    return f"silo-{build_type.value}"


class CMakePresets:
    """Writes a hidden preset holding what silo knows, and the presets a recipe adds on top.

    The hidden preset is silo-debug or silo-release: the toolchain file, the generator and
    the compiler's environment, and the cache entries of the toolchain generator it is given.
    Presets written by hand can inherit it too.
    """

    def __init__(self, package: SiloPackage[Any], toolchain: CMakeGenerator[Any]) -> None:
        self.package = package
        self.toolchain = toolchain
        self.presets: list[Preset] = []

    def add(
        self, name: str, build_dir: str | None = None, build_type: BuildMode | None = None
    ) -> Preset:
        """Add a preset. `build_dir` is relative to the project and defaults to build/<name>."""
        context = self.package.context
        build_type = build_type or context.build_type
        preset = Preset(name)
        preset.cache["CMAKE_BUILD_TYPE"] = "Debug" if build_type is BuildMode.Debug else "Release"
        preset.configure["binaryDir"] = "${sourceDir}/" + (build_dir or f"build/{name}")
        self.presets.append(preset)
        return preset

    def _base_preset(self) -> dict[str, Any]:
        context = self.package.context
        backend = backend_for(context.profile.settings.os)
        environment = {
            key: context.env[key] for key in backend.compiler_environment if key in context.env
        }
        base: dict[str, Any] = {
            "name": base_preset_name(context.build_type),
            "hidden": True,
            "generator": "Ninja",
            "toolchainFile": "${fileDir}/" + TOOLCHAIN_FILE,
            "environment": environment,
        }
        if self.toolchain.cache:
            base["cacheVariables"] = self.toolchain.cache
        cmake = shutil.which("cmake", path=context.env.get("PATH"))
        if cmake:
            base["cmakeExecutable"] = Path(cmake).as_posix()
        return base

    def document(self) -> dict[str, Any]:
        base = self._base_preset()
        configure, build, test = [base], [], []
        for preset in self.presets:
            entry: dict[str, Any] = {"name": preset.name, "inherits": base["name"]}
            entry["cacheVariables"] = {key: _cache_text(v) for key, v in preset.cache.items()}
            if preset.environment:
                entry["environment"] = preset.environment
            configure.append(entry | preset.configure)
            linked = {"name": preset.name, "configurePreset": preset.name}
            build.append(linked | preset.build)
            test.append(linked | preset.test)
        return {
            "version": PRESETS_VERSION,
            "configurePresets": configure,
            "buildPresets": build,
            "testPresets": test,
        }

    def generate(self) -> Path:
        context = self.package.context
        context.generated_dir.mkdir(parents=True, exist_ok=True)
        presets_file = context.generated_dir / PRESETS_FILE
        presets_file.write_text(json.dumps(self.document(), indent=2) + "\n", encoding="utf-8")
        if context.project_generated_dir:
            write_presets_index(context.project_generated_dir)
        return presets_file


def write_presets_index(project_generated_dir: Path) -> Path:
    """The one file a project includes: it pulls in each configuration's presets."""
    included = sorted(
        f"{folder.name}/{PRESETS_FILE}"
        for folder in project_generated_dir.iterdir()
        if (folder / PRESETS_FILE).is_file()
    )
    index = project_generated_dir / PRESETS_FILE
    document = {"version": PRESETS_VERSION, "include": included}
    index.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return index
