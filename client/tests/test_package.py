import json
import os

import pytest

from silo.errors import SiloError
from silo.package import Component, Package, write_package
from silo.platform.linux import LinuxBackend
from silo.platform.macos import MacOSBackend
from silo.platform.windows import WindowsBackend


def make_install_tree(root, files):
    for relative in files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    return root


def test_infer_builds_one_component_from_the_conventional_layout(tmp_path):
    install = make_install_tree(tmp_path, ["include/demo.h", "lib/demo.lib", "bin/demo.exe"])

    package = Package.infer(install, "demo", WindowsBackend())

    component = package.components[0]
    assert component.name == "demo"
    assert component.headers == ["include"]
    assert component.static_libs == ["lib/demo.lib"]
    assert component.executables == ["bin/demo.exe"]


def test_infer_refuses_to_pick_between_several_libraries(tmp_path):
    install = make_install_tree(tmp_path, ["lib/zlib.lib", "lib/zlibstatic.lib"])

    with pytest.raises(RuntimeError, match="several libraries"):
        Package.infer(install, "zlib", WindowsBackend())


@pytest.mark.parametrize(
    ("backend", "library_file"),
    [(WindowsBackend(), "lib/demo.lib"), (LinuxBackend(), "lib/libdemo.a")],
)
def test_write_package_resolves_bare_names_and_copies_only_listed_files(
    tmp_path, backend, library_file
):
    install = make_install_tree(
        tmp_path / "install", ["include/demo.h", library_file, "share/doc/readme.txt"]
    )
    store_path = tmp_path / "store" / "demo-1.0-abc"
    package = Package([Component("demo", headers=["include"], static_libs=["demo"])])

    write_package(package, install, store_path, "demo", "1.0", "abc", backend)

    manifest = json.loads((store_path / "silo" / "package.json").read_text(encoding="utf-8"))
    artifacts = manifest["components"]["demo"]["artifacts"]
    assert [artifact["path"] for artifact in artifacts] == ["include", library_file]
    assert sorted(manifest["files"]) == sorted(["include/demo.h", library_file])
    assert not (store_path / "share").exists()


def test_write_package_reports_a_missing_library(tmp_path):
    install = make_install_tree(tmp_path / "install", ["include/demo.h"])
    package = Package([Component("demo", static_libs=["demo"])])

    with pytest.raises(RuntimeError, match="'demo' was not found"):
        write_package(package, install, tmp_path / "out", "demo", "1.0", "abc", WindowsBackend())


def stored_requires(tmp_path, component, dependency_components):
    install = make_install_tree(tmp_path / "install", ["include/demo.h"])
    store_path = tmp_path / "store" / "demo-1.0-abc"
    package = Package([component, Component("extra")])
    write_package(
        package, install, store_path, "demo", "1.0", "abc", WindowsBackend(), dependency_components
    )
    manifest = json.loads((store_path / "silo" / "package.json").read_text(encoding="utf-8"))
    return manifest["components"][component.name]["requires"]


DEPENDENCIES = {"zlib": ["zlib"], "openssl": ["ssl", "crypto"]}


def test_nothing_is_required_unless_the_recipe_says_so(tmp_path):
    assert stored_requires(tmp_path, Component("demo"), DEPENDENCIES) == []


def test_a_bare_package_name_requires_all_of_its_components(tmp_path):
    requires = stored_requires(tmp_path, Component("demo", requires=["openssl"]), DEPENDENCIES)

    assert requires == ["openssl::ssl", "openssl::crypto"]


def test_requires_can_name_one_component_or_a_sibling(tmp_path):
    component = Component("demo", requires=["openssl::crypto", "demo::extra"])

    assert stored_requires(tmp_path, component, DEPENDENCIES) == ["openssl::crypto", "demo::extra"]


@pytest.mark.parametrize(
    ("reference", "message"),
    [("libpng", "neither this package nor one of its direct dependencies"), ("zlib::z", "has no")],
)
def test_requiring_something_unknown_is_an_error(tmp_path, reference, message):
    with pytest.raises(SiloError, match=message):
        stored_requires(tmp_path, Component("demo", requires=[reference]), DEPENDENCIES)


def test_license_files_are_copied_from_the_source_and_recorded(tmp_path):
    install = make_install_tree(tmp_path / "install", ["include/demo.h"])
    source = make_install_tree(tmp_path / "source", ["LICENSE", "docs/FTL.TXT", "main.c"])
    store_path = tmp_path / "store" / "demo-1.0-abc"

    write_package(
        Package([Component("demo", headers=["include"])], licenses=["LICENSE", "docs/FTL.TXT"]),
        install,
        store_path,
        "demo",
        "1.0",
        "abc",
        WindowsBackend(),
        source_dir=source,
    )

    manifest = json.loads((store_path / "silo" / "package.json").read_text(encoding="utf-8"))
    assert manifest["license_files"] == ["licenses/LICENSE", "licenses/docs/FTL.TXT"]
    assert (store_path / "licenses" / "docs" / "FTL.TXT").read_text(encoding="utf-8")
    assert "licenses/LICENSE" in manifest["files"]


def test_a_listed_license_file_missing_from_the_source_is_an_error(tmp_path):
    install = make_install_tree(tmp_path / "install", ["include/demo.h"])
    source = make_install_tree(tmp_path / "source", ["main.c"])

    with pytest.raises(SiloError, match="lists the license file 'COPYING'"):
        write_package(
            Package([Component("demo", headers=["include"])], licenses=["COPYING"]),
            install,
            tmp_path / "store" / "demo",
            "demo",
            "1.0",
            "abc",
            WindowsBackend(),
            source_dir=source,
        )
    assert not (tmp_path / "store" / "demo").exists()


@pytest.mark.parametrize(
    ("backend", "files", "expected"),
    [
        (WindowsBackend(), ["bin/demo.dll", "lib/demo.lib"], ("bin/demo.dll", "lib/demo.lib")),
        (LinuxBackend(), ["lib/libdemo.so"], ("lib/libdemo.so", None)),
        (MacOSBackend(), ["lib/libdemo.dylib"], ("lib/libdemo.dylib", None)),
    ],
)
def test_a_bare_shared_library_name_is_found_per_platform(tmp_path, backend, files, expected):
    install = make_install_tree(tmp_path / "install", files)
    store_path = tmp_path / "store" / "demo-1.0-abc"
    package = Package([Component("demo", shared_libs=["demo"])])

    write_package(package, install, store_path, "demo", "1.0", "abc", backend)

    manifest = json.loads((store_path / "silo" / "package.json").read_text(encoding="utf-8"))
    artifact = manifest["components"]["demo"]["artifacts"][0]
    assert (artifact["type"], artifact["path"], artifact.get("import")) == ("shared_lib", *expected)
    assert sorted(manifest["files"]) == sorted(files)


def test_a_missing_shared_library_is_reported(tmp_path):
    install = make_install_tree(tmp_path / "install", ["lib/demo.lib"])
    package = Package([Component("demo", shared_libs=["demo"])])

    with pytest.raises(RuntimeError, match=r"Shared library 'demo' was not found.*bin/demo\.dll"):
        write_package(package, install, tmp_path / "out", "demo", "1.0", "abc", WindowsBackend())


def test_an_inferred_program_keeps_the_files_installed_beside_it(tmp_path):
    install = make_install_tree(tmp_path, ["bin/demo.exe", "bin/dependency.dll"])

    package = Package.infer(install, "demo", WindowsBackend())

    assert package.components[0].content == ["bin"]


@pytest.mark.skipif(os.name == "nt", reason="needs symbolic links")
def test_a_shared_library_keeps_its_versioned_names(tmp_path):
    install = make_install_tree(tmp_path / "install", ["include/z.h", "lib/libz.so.1.3.1"])
    (install / "lib" / "libz.so.1").symlink_to("libz.so.1.3.1")
    (install / "lib" / "libz.so").symlink_to("libz.so.1")
    package = Package(components=[Component("zlib", shared_libs=["z"])])

    write_package(
        package, install, tmp_path / "store" / "zlib-1", "zlib", "1.3.1", "1", LinuxBackend()
    )

    library = tmp_path / "store" / "zlib-1" / "lib"
    assert not (library / "libz.so").is_symlink()
    assert (library / "libz.so.1").resolve() == (library / "libz.so").resolve()
    assert (library / "libz.so.1.3.1").resolve() == (library / "libz.so").resolve()
