import json
import os
import sys
from pathlib import Path

import pytest

from silo.build_context import BuildContext
from silo.build_profile import CompilerProfile, Profile, Settings
from silo.enums import Architecture, BuildMode, Compiler, Platform
from silo.errors import SiloError
from silo.platform.linux import LinuxBackend
from silo.tools.cmake.cmake_generator import toolchain_text
from silo.tools.meson import MesonBuild, MesonGenerator
from silo.tools.pkgconfig.pkg_config_deps import pc_text, write_pc_files


@pytest.fixture
def linux_profile() -> Profile:
    return Profile(
        settings=Settings(os=Platform.Linux, arch=Architecture.X86_64),
        compiler=CompilerProfile(
            kind=Compiler.GCC,
            executable=Path("/usr/bin/gcc"),
            cxx_executable=Path("/usr/bin/g++"),
            version="13.3.0",
            target="x86_64-linux-gnu",
        ),
    )


@pytest.fixture
def demo_package(load_demo_recipe, linux_profile, tmp_path, monkeypatch):
    def make(path: str = "", build_type: BuildMode = BuildMode.Release):
        package = load_demo_recipe("")
        package._context = BuildContext(
            profile=linux_profile,
            build_type=build_type,
            env={"PATH": path},
            source_dir=tmp_path / "src",
            build_dir=tmp_path / "build",
            stage_dir=tmp_path / "stage",
            generated_dir=tmp_path / "generated",
            install_prefix="/silo-prefix-abc",
            local_source=False,
        )
        package.commands = []
        monkeypatch.setattr(
            package,
            "run",
            lambda args, env=None, **_: package.commands.append(([str(a) for a in args], env)),
        )
        return package

    return make


@pytest.fixture
def tool_bin(tmp_path):
    def make(name: str) -> Path:
        bin_dir = tmp_path / f"{name}-1.0-uv" / "bin"
        bin_dir.mkdir(parents=True)
        program = bin_dir / (f"{name}.exe" if os.name == "nt" else name)
        program.write_text("", encoding="utf-8")
        program.chmod(0o755)
        return bin_dir

    return make


def test_the_native_file_names_the_compilers_and_the_sentinel_prefix(demo_package):
    native_file = MesonGenerator(demo_package(build_type=BuildMode.Debug)).generate()

    text = native_file.read_text(encoding="utf-8")
    assert "c = '/usr/bin/gcc'" in text
    assert "cpp = '/usr/bin/g++'" in text
    assert "buildtype = 'debug'" in text
    assert "prefix = '/silo-prefix-abc'" in text
    assert "wrap_mode = 'nodownload'" in text


def test_a_recipes_options_land_in_their_own_sections(demo_package):
    meson = MesonGenerator(demo_package())
    meson.set_option("tests", False)
    meson.set_option("gtk", "disabled")
    meson.set_builtin("default_library", "shared")

    text = meson.generate().read_text(encoding="utf-8")

    project_options = text.split("[project options]")[1]
    assert "tests = false" in project_options
    assert "gtk = 'disabled'" in project_options
    assert "default_library = 'shared'" in text.split("[project options]")[0]


def test_pkg_config_is_named_when_the_recipe_declared_it(demo_package, tool_bin):
    without = MesonGenerator(demo_package()).generate().read_text(encoding="utf-8")
    with_tool = MesonGenerator(demo_package(str(tool_bin("pkgconf")))).generate()

    assert "pkg-config" not in without
    assert "pkg-config = '" in with_tool.read_text(encoding="utf-8")


def test_meson_runs_as_a_module_and_sees_only_silos_pc_files(demo_package, tool_bin):
    meson_bin = tool_bin("meson")
    package = demo_package(str(meson_bin))
    MesonGenerator(package).generate()

    MesonBuild(package).configure()

    command, env = package.commands[0]
    assert command[:4] == [sys.executable, "-m", "mesonbuild.mesonmain", "setup"]
    assert env["PYTHONPATH"] == str(meson_bin.parent)
    assert env["PKG_CONFIG_LIBDIR"] == str(package.context.generated_dir / "pkgconfig")


def test_meson_without_its_tool_or_native_file_says_what_is_missing(demo_package, tool_bin):
    with pytest.raises(SiloError, match=r"MesonGenerator\(self\)\.generate\(\)"):
        MesonBuild(demo_package(str(tool_bin("meson")))).configure()
    package = demo_package()
    MesonGenerator(package).generate()
    with pytest.raises(SiloError, match=r'self.tool\("meson@1"\)'):
        MesonBuild(package).configure()


def component(**fields) -> dict:
    return {"artifacts": [], "requires": [], "defines": [], "system_libs": []} | fields


FREETYPE = {
    "name": "freetype",
    "version": "2.13.3",
    "components": {
        "freetype": component(
            artifacts=[
                {"type": "headers", "path": "include/freetype2"},
                {"type": "static_lib", "path": "lib/libfreetype.a"},
            ],
            requires=["zlib::zlib"],
            defines=["FT_STATIC"],
            system_libs=["m"],
        )
    },
}


def test_a_pc_file_points_into_the_store_under_silos_name_and_version():
    text = pc_text(FREETYPE, "freetype", Path("/store/freetype-1"), {"zlib::zlib": "zlib"})

    assert "prefix=/store/freetype-1" in text
    assert "Name: freetype\n" in text
    assert "Version: 2.13.3" in text
    assert "Requires: zlib" in text
    assert "Cflags: -I${prefix}/include/freetype2 -DFT_STATIC" in text
    assert "Libs: ${prefix}/lib/libfreetype.a -lm" in text


def stored(tmp_path, manifest: dict) -> Path:
    package_dir = tmp_path / "store" / f"{manifest['name']}-1"
    (package_dir / "silo").mkdir(parents=True)
    (package_dir / "silo" / "package.json").write_text(json.dumps(manifest))
    return package_dir


def test_pc_files_say_where_the_data_folder_and_the_programs_are(tmp_path):
    scanner = component(artifacts=[{"type": "executable", "path": "bin/wayland-scanner"}])
    manifest = {"name": "wayland", "version": "1.22.0", "components": {"wayland-scanner": scanner}}

    write_pc_files({"wayland": stored(tmp_path, manifest)}, tmp_path / "pc")

    text = (tmp_path / "pc" / "wayland-scanner.pc").read_text(encoding="utf-8")
    assert "datadir=${prefix}/share\n" in text
    assert "pkgdatadir=${datadir}/wayland\n" in text
    assert "wayland_scanner=${prefix}/bin/wayland-scanner\n" in text


def test_an_alias_is_the_same_file_under_the_name_a_build_asks_for(tmp_path):
    packages = {"freetype": stored(tmp_path, FREETYPE)}

    write_pc_files(packages, tmp_path / "pc", {"freetype2": "freetype::freetype"})

    own = (tmp_path / "pc" / "freetype.pc").read_text(encoding="utf-8")
    alias = (tmp_path / "pc" / "freetype2.pc").read_text(encoding="utf-8")
    assert alias == own.replace("Name: freetype\n", "Name: freetype2\n")
    assert "Version: 2.13.3" in alias


def test_an_alias_to_something_that_is_not_there_is_reported(tmp_path):
    packages = {"freetype": stored(tmp_path, FREETYPE)}

    with pytest.raises(SiloError, match="'zlib' is not a dependency"):
        write_pc_files(packages, tmp_path / "pc", {"z": "zlib::zlib"})
    with pytest.raises(SiloError, match="freetype has no component 'ft'"):
        write_pc_files(packages, tmp_path / "pc", {"freetype2": "freetype::ft"})


def test_a_linux_build_gets_both_compilers_and_position_independent_code(linux_profile, tmp_path):
    env = LinuxBackend().build_env(linux_profile, [Path("/tools/cmake")], tmp_path)
    toolchain = toolchain_text(linux_profile)

    assert env["CC"].endswith("gcc") and env["CXX"].endswith("g++")
    assert env["PATH"].split(os.pathsep)[0] == str(Path("/tools/cmake"))
    assert 'set(CMAKE_CXX_COMPILER "/usr/bin/g++")' in toolchain
    assert 'set(CMAKE_POSITION_INDEPENDENT_CODE "ON")' in toolchain
