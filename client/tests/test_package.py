import json

import pytest

from silo.errors import SiloError
from silo.package import Component, Package, write_package
from silo.platform.linux import LinuxBackend
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
