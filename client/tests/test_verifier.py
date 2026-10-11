import pytest

from silo.errors import SiloError
from silo.package import Component, Package, write_package
from silo.platform.windows import WindowsBackend
from silo.verifier import CHUNK_SIZE, files_containing, verify_no_install_prefix

PREFIX = "/silo-prefix-abc123"
SENTINEL = "silo-prefix-abc123"


def write_bytes(path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_a_clean_package_passes(tmp_path):
    write_bytes(tmp_path / "lib" / "demo.lib", b"\x00binary\x00data")
    write_bytes(tmp_path / "include" / "demo.h", b"#define DEMO 1\n")

    verify_no_install_prefix(tmp_path, "demo", PREFIX)


def test_the_prefix_in_a_text_or_binary_file_is_found(tmp_path):
    write_bytes(tmp_path / "bin" / "demo-config", f"prefix={PREFIX}\n".encode())
    write_bytes(tmp_path / "lib" / "demo.lib", b"\x00\x01C:/" + SENTINEL.encode() + b"/share\x00")
    write_bytes(tmp_path / "include" / "demo.h", b"clean")

    assert files_containing(tmp_path, SENTINEL) == ["bin/demo-config", "lib/demo.lib"]


def test_the_prefix_as_wide_characters_is_found(tmp_path):
    write_bytes(tmp_path / "bin" / "demo.exe", b"MZ\x00" + SENTINEL.encode("utf-16-le"))

    assert files_containing(tmp_path, SENTINEL) == ["bin/demo.exe"]


def test_the_prefix_split_across_two_read_chunks_is_found(tmp_path):
    split_at = CHUNK_SIZE - len(SENTINEL) // 2
    write_bytes(tmp_path / "big.lib", b"x" * split_at + SENTINEL.encode() + b"x" * 100)

    assert files_containing(tmp_path, SENTINEL) == ["big.lib"]


def test_the_error_names_the_package_and_the_files(tmp_path):
    write_bytes(tmp_path / "lib" / "demo.lib", SENTINEL.encode())

    with pytest.raises(SiloError, match=r"demo has its install prefix .* lib/demo\.lib"):
        verify_no_install_prefix(tmp_path, "demo", PREFIX)


def test_a_leaking_package_is_not_stored_but_dropped_files_do_not_count(tmp_path):
    install = tmp_path / "install"
    write_bytes(install / "lib" / "demo.lib", b"clean")
    write_bytes(install / "lib" / "pkgconfig" / "demo.pc", f"prefix={PREFIX}".encode())
    write_bytes(install / "lib" / "leaky.lib", SENTINEL.encode())
    store = tmp_path / "store"
    backend = WindowsBackend()

    clean = Package([Component("demo", static_libs=["lib/demo.lib"])])
    write_package(
        clean, install, store / "demo-ok", "demo", "1.0", "abc", backend, install_prefix=PREFIX
    )
    assert (store / "demo-ok" / "lib" / "demo.lib").is_file()

    leaky = Package([Component("demo", static_libs=["lib/leaky.lib"])])
    with pytest.raises(SiloError, match=r"lib/leaky\.lib"):
        write_package(
            leaky, install, store / "demo-bad", "demo", "1.0", "abc", backend, install_prefix=PREFIX
        )
    assert [path.name for path in store.iterdir()] == ["demo-ok"]
