import pytest

from silo.versions import matches_prefix, version_key


@pytest.mark.parametrize(
    ("lower", "higher"),
    [
        ("1.9", "1.10"),
        ("1.1.1", "1.1.1w"),
        ("1.2.3", "1.2.3.4"),
        ("1.0rc1", "1.0.1"),
        ("20230920", "20240116.1"),
    ],
)
def test_version_key_orders_loose_versions(lower, higher):
    assert version_key(lower) < version_key(higher)


@pytest.mark.parametrize(
    ("version", "spec", "expected"),
    [
        ("4.3.4", "4.3", True),
        ("4.3", "4.3", True),
        ("4.30.1", "4.3", False),
        ("4.2.9", "4.3", False),
        ("1.13.2", None, True),
    ],
)
def test_matches_prefix(version, spec, expected):
    assert matches_prefix(version, spec) is expected
