from silo.dependency_graph import resolve
from silo.enums import BuildMode

LOCAL_RECIPE = """\
from silo import SiloPackage


class App(SiloPackage):
    name = "app"
    version = "1.0"

    def source(self, src):
        src.local(".")
"""

FETCHED_RECIPE = """\
from silo import SiloPackage


class Zlib(SiloPackage):
    name = "zlib"
    version = "1.3.1"

    def source(self, src):
        src.fetch("https://example.com/zlib.tar.gz", sha256="aa")
"""

ROOT_WITH_SOURCE_OVERRIDE = """\
from silo import SiloPackage


class App(SiloPackage):
    name = "app"
    version = "1.0"

    def source(self, src):
        src.local(".")

    def deps(self):
        self.dep("../zlib")
        self.override("zlib", source="../zlib-checkout", version="1.4.0")
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_local_source_id_follows_the_files_on_disk(git_repo):
    write(git_repo / "silopkg.py", LOCAL_RECIPE)
    write(git_repo / "main.cpp", "int main() {}")
    first = resolve(git_repo, BuildMode.Release).nodes["app"].source

    write(git_repo / "main.cpp", "int main() { return 1; }")
    second = resolve(git_repo, BuildMode.Release).nodes["app"].source

    assert first.local_source
    assert first.id.startswith("local:")
    assert first.id != second.id


def test_root_can_point_a_dependency_at_a_local_checkout(git_repo):
    write(git_repo / "app" / "silopkg.py", ROOT_WITH_SOURCE_OVERRIDE)
    write(git_repo / "zlib" / "silopkg.py", FETCHED_RECIPE)
    write(git_repo / "zlib-checkout" / "zlib.c", "int z;")

    graph = resolve(git_repo / "app", BuildMode.Release)

    zlib = graph.nodes["zlib"]
    assert zlib.source.local_dir == (git_repo / "zlib-checkout").resolve()
    assert zlib.version == "1.4.0"
    seen_by_app = graph.nodes["app"].package.dependencies["zlib"]
    assert seen_by_app.local_source
    assert seen_by_app.version == "1.4.0"
