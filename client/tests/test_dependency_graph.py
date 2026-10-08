from pathlib import Path

import pytest

from silo.dependency_graph import resolve, validate
from silo.enums import BuildMode
from silo.errors import InvalidConfiguration, ResolutionError

RECIPE = """\
from silo import InvalidConfiguration, Options, SiloPackage


class {class_name}Options(Options):
    flavor: str = "plain"


class {class_name}(SiloPackage[{class_name}Options]):
    name = "{name}"
    version = "1.0"
{body}
"""


@pytest.fixture
def recipes(tmp_path):
    """Write recipes side by side, so one can depend on another with self.dep("../name")."""

    def write(name: str, body: str = "") -> Path:
        recipe_dir = tmp_path / name
        recipe_dir.mkdir()
        text = RECIPE.format(class_name=name.capitalize(), name=name, body=body)
        (recipe_dir / "silopkg.py").write_text(text, encoding="utf-8")
        return recipe_dir

    return write


def deps(*lines: str) -> str:
    return "    def deps(self):\n" + "".join(f"        {line}\n" for line in lines)


def test_dependencies_build_before_their_dependents(recipes):
    recipes("zlib")
    recipes("freetype", deps('self.dep("../zlib")'))
    app = recipes("app", deps('self.dep("../freetype")'))

    graph = resolve(app, BuildMode.Release)

    assert [node.name for node in graph.build_order()] == ["zlib", "freetype", "app"]
    assert graph.transitive_dependencies("app") == ["freetype", "zlib"]


def test_only_the_root_follows_the_requested_build_type(recipes):
    recipes("zlib")
    app = recipes("app", deps('self.dep("../zlib")'))

    graph = resolve(app, BuildMode.Debug)

    assert graph.nodes["app"].build_type is BuildMode.Debug
    assert graph.nodes["zlib"].build_type is BuildMode.Release


def test_root_override_reaches_a_package_it_does_not_depend_on_directly(recipes):
    recipes("zlib")
    recipes("freetype", deps('self.dep("../zlib")'))
    app = recipes(
        "app",
        deps(
            'self.dep("../freetype")',
            'self.override("zlib", options={"flavor": "fast"}, build_type="debug")',
        ),
    )

    graph = resolve(app, BuildMode.Release)

    zlib = graph.nodes["zlib"]
    assert zlib.package.options.flavor == "fast"
    assert zlib.build_type is BuildMode.Debug
    assert zlib.overridden
    assert not graph.nodes["freetype"].overridden


def test_a_dependency_request_sets_an_option(recipes):
    recipes("zlib")
    app = recipes("app", deps('self.dep("../zlib", options={"flavor": "small"})'))

    graph = resolve(app, BuildMode.Release)

    assert graph.nodes["zlib"].package.options.flavor == "small"


def test_conflicting_requests_are_an_error(recipes):
    recipes("zlib")
    recipes("freetype", deps('self.dep("../zlib", options={"flavor": "small"})'))
    recipes("harfbuzz", deps('self.dep("../zlib", options={"flavor": "fast"})'))
    app = recipes("app", deps('self.dep("../freetype")', 'self.dep("../harfbuzz")'))

    with pytest.raises(ResolutionError, match="request different values for zlib:flavor"):
        resolve(app, BuildMode.Release)


def test_root_override_settles_conflicting_requests(recipes):
    recipes("zlib")
    recipes("freetype", deps('self.dep("../zlib", options={"flavor": "small"})'))
    recipes("harfbuzz", deps('self.dep("../zlib", options={"flavor": "fast"})'))
    app = recipes(
        "app",
        deps(
            'self.dep("../freetype")',
            'self.dep("../harfbuzz")',
            'self.override("zlib", options={"flavor": "fast"})',
        ),
    )

    graph = resolve(app, BuildMode.Release)

    assert graph.nodes["zlib"].package.options.flavor == "fast"


def test_command_line_beats_the_root_override(recipes):
    recipes("zlib")
    app = recipes(
        "app",
        deps('self.dep("../zlib")', 'self.override("zlib", options={"flavor": "fast"})'),
    )

    graph = resolve(app, BuildMode.Release, {"zlib": {"flavor": "cli"}, "": {"flavor": "root"}})

    assert graph.nodes["zlib"].package.options.flavor == "cli"
    assert graph.nodes["app"].package.options.flavor == "root"


def test_overrides_from_a_non_root_recipe_are_ignored(recipes):
    recipes("zlib")
    recipes(
        "freetype",
        deps('self.dep("../zlib")', 'self.override("zlib", options={"flavor": "fast"})'),
    )
    app = recipes("app", deps('self.dep("../freetype")'))

    graph = resolve(app, BuildMode.Release)

    assert graph.nodes["zlib"].package.options.flavor == "plain"


def test_overriding_a_package_outside_the_graph_is_an_error(recipes):
    app = recipes("app", deps('self.override("zlib", options={"flavor": "fast"})'))

    with pytest.raises(ResolutionError, match="'zlib', which is not in the graph"):
        resolve(app, BuildMode.Release)


def test_an_unknown_option_is_an_error(recipes):
    recipes("zlib")
    app = recipes("app", deps('self.dep("../zlib", options={"flavour": "typo"})'))

    with pytest.raises(ResolutionError, match="Invalid options for zlib"):
        resolve(app, BuildMode.Release)


def test_a_dependency_can_change_its_own_deps_based_on_a_requested_option(recipes):
    recipes("brotli")
    recipes(
        "freetype",
        "    def deps(self):\n"
        '        if self.options.flavor == "full":\n'
        '            self.dep("../brotli")\n',
    )
    app = recipes("app", deps('self.dep("../freetype", options={"flavor": "full"})'))

    graph = resolve(app, BuildMode.Release)

    assert graph.nodes["freetype"].dependency_names == ["brotli"]


def test_a_cycle_is_reported(recipes):
    recipes("a", deps('self.dep("../b")'))
    recipes("b", deps('self.dep("../a")'))

    with pytest.raises(ResolutionError, match="Dependency cycle: a -> b -> a"):
        resolve(recipes("app", deps('self.dep("../a")')), BuildMode.Release).build_order()


def test_a_named_dependency_explains_that_only_paths_work(recipes):
    app = recipes("app", deps('self.dep("zlib@1.3")'))

    with pytest.raises(ResolutionError, match="only path dependencies"):
        resolve(app, BuildMode.Release)


def test_validate_sees_how_a_dependency_was_resolved(recipes):
    recipes("zlib")
    recipes(
        "freetype",
        deps('self.dep("../zlib")') + "    def validate(self):\n"
        '        zlib = self.dependencies["zlib"]\n'
        '        if zlib.options.flavor == "fast":\n'
        '            raise InvalidConfiguration(f"cannot use a fast zlib {zlib.version}")\n',
    )
    app = recipes(
        "app",
        deps('self.dep("../freetype")', 'self.override("zlib", options={"flavor": "fast"})'),
    )

    graph = resolve(app, BuildMode.Release)

    assert graph.nodes["freetype"].package.dependencies["zlib"].overridden
    with pytest.raises(InvalidConfiguration, match=r"freetype: cannot use a fast zlib 1\.0"):
        validate(graph)
