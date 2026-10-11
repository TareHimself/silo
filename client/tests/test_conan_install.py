import os

import pytest

from silo.build_context import BuildContext
from silo.enums import BuildMode
from silo.errors import SiloError
from silo.paths import conan_dir
from silo.source import SourceSpec, fetch_source
from silo.tools.conan import ConanInstall
from silo.tools.conan.conan_install import conan_settings


@pytest.fixture
def demo_package(load_demo_recipe, windows_profile, tmp_path, monkeypatch):
    def make(path: str = ""):
        package = load_demo_recipe("")
        package._context = BuildContext(
            profile=windows_profile,
            build_type=BuildMode.Debug,
            env={"PATH": path},
            source_dir=tmp_path / "src",
            build_dir=tmp_path / "build",
            stage_dir=tmp_path / "stage",
            generated_dir=tmp_path / "generated",
            install_prefix="/silo-prefix-abc",
            local_source=False,
        )
        package.commands = []

        def run(args, env=None, **_):
            package.commands.append(([str(argument) for argument in args], env))
            deployed = tmp_path / "build" / "conan" / "direct_deploy" / "libvpx" / "lib"
            deployed.mkdir(parents=True)
            (deployed / "vpx.lib").write_text("library", encoding="utf-8")

        monkeypatch.setattr(package, "run", run)
        return package

    return make


@pytest.fixture
def conan_tool(tmp_path):
    bin_dir = tmp_path / "conan-2.0-uv" / "bin"
    bin_dir.mkdir(parents=True)
    name = "conan.exe" if os.name == "nt" else "conan"
    (bin_dir / name).write_text("", encoding="utf-8")
    (bin_dir / name).chmod(0o755)
    return bin_dir


def test_the_profile_keeps_the_release_runtime_in_a_debug_build(windows_profile):
    settings = conan_settings(windows_profile, BuildMode.Debug)

    assert settings["build_type"] == "Debug"
    assert settings["compiler.runtime_type"] == "Release"
    assert settings["compiler.runtime"] == "dynamic"


def test_msvc_is_named_by_its_compiler_number(windows_profile):
    compiler = windows_profile.compiler.model_copy(update={"version": "14.44.35207"})
    profile = windows_profile.model_copy(update={"compiler": compiler})

    assert conan_settings(profile, BuildMode.Release)["compiler.version"] == "194"


def test_install_asks_conan_for_the_package_and_copies_it_in(demo_package, conan_tool):
    package = demo_package(str(conan_tool))

    ConanInstall(package).install("libvpx/1.14.1", options={"shared": False})

    command, env = package.commands[0]
    assert "--requires=libvpx/1.14.1" in command
    assert command[command.index("--options") + 1] == "libvpx/*:shared=False"
    assert env["PYTHONPATH"] == str(conan_tool.parent)
    assert (package.install_dir / "lib" / "vpx.lib").is_file()


def test_an_option_can_name_a_dependency_of_the_package(demo_package, conan_tool):
    package = demo_package(str(conan_tool))

    ConanInstall(package).install(
        "libvpx/1.14.1", options={"shared": False, "libcurl/*:with_ssl": "schannel"}
    )

    command, _ = package.commands[0]
    options = [command[i + 1] for i, part in enumerate(command) if part == "--options"]
    assert options == ["libvpx/*:shared=False", "libcurl/*:with_ssl=schannel"]


def test_conan_keeps_its_files_in_silos_cache(demo_package, conan_tool):
    package = demo_package(str(conan_tool))

    ConanInstall(package).install("libvpx/1.14.1")

    _, env = package.commands[0]
    assert env["CONAN_HOME"] == str(conan_dir())


def test_a_recipe_can_replace_settings_conan_refuses(demo_package, conan_tool):
    package = demo_package(str(conan_tool))

    ConanInstall(package).install("libvpx/1.14.1", settings={"compiler.version": "194"})

    profile = (package.context.generated_dir / "conan-profile").read_text(encoding="utf-8")
    assert "compiler.version=194" in profile


def test_install_without_the_conan_tool_says_how_to_get_it(demo_package):
    with pytest.raises(SiloError, match=r'self.tool\("conan@2"\)'):
        ConanInstall(demo_package()).install("libvpx/1.14.1")


def test_an_empty_source_is_an_empty_folder(tmp_path):
    spec = SourceSpec()
    spec.empty()

    fetch_source(spec, tmp_path / "src")

    assert spec.id == "empty"
    assert list((tmp_path / "src").iterdir()) == []
