import re

ChunkKey = tuple[bool, int, str]

_CHUNK = re.compile(r"\d+|[A-Za-z]+")


def _chunk_key(chunk: str) -> ChunkKey:
    if chunk.isdigit():
        return (True, int(chunk), "")
    return (False, 0, chunk.lower())


def version_key(version: str) -> tuple[ChunkKey, ...]:
    """Sort key for loose versions: "1.10" > "1.9", "1.1.1w" > "1.1.1", "1.0rc1" < "1.0.1"."""
    return tuple(_chunk_key(chunk) for chunk in _CHUNK.findall(version))


def matches_prefix(version: str, spec: str | None) -> bool:
    """A spec of "4.3" matches "4.3" and "4.3.4", but not "4.30"."""
    return spec is None or version == spec or version.startswith(spec + ".")
