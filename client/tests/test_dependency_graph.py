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


TOOL_RECIPE = """\
from silo import InvalidConfiguration, SiloPackage


class {cls}(SiloPackage):
    name = "{name}"
    version = "1.0"
    supports_shared = True

    def source(self, src):
        src.fetch("https://example.com/{name}.tar.gz", sha256="aa")

    def deps(self):
        {deps}
"""


def write_recipe(root, name: str, deps: str = "pass"):
    recipe = root / name / "silopkg.py"
    recipe.parent.mkdir(parents=True)
    recipe.write_text(TOOL_RECIPE.format(cls=name.title(), name=name, deps=deps), encoding="utf-8")


def test_a_tool_is_a_graph_of_its_own_and_is_not_linked(tmp_path):
    write_recipe(tmp_path, "zlib")
    write_recipe(tmp_path, "protoc", 'self.dep("../zlib")')
    write_recipe(tmp_path, "app", 'self.tool("../protoc")')

    graph = resolve(tmp_path / "app", BuildMode.Release)

    assert list(graph.nodes) == ["app"]
    assert graph.nodes["app"].tool_names == ["protoc"]
    tool = graph.nodes["app"].tools[0]
    assert [node.name for node in tool.build_order()] == ["zlib", "protoc"]


def test_a_tool_graph_knows_it_was_declared_transitive(tmp_path):
    write_recipe(tmp_path, "m4")
    write_recipe(tmp_path, "gperf")
    recipe = 'self.tool("../m4", transitive=True)\n        self.tool("../gperf")'
    write_recipe(tmp_path, "bison", recipe)

    graph = resolve(tmp_path / "bison", BuildMode.Release)

    assert [(tool.root, tool.transitive) for tool in graph.nodes["bison"].tools] == [
        ("m4", True),
        ("gperf", False),
    ]


def test_a_tool_recipe_can_be_given_options(tmp_path):
    write_recipe(tmp_path, "protoc")
    write_recipe(tmp_path, "app", 'self.tool("../protoc", options={"shared": True})')

    graph = resolve(tmp_path / "app", BuildMode.Release)

    tool = graph.nodes["app"].tools[0]
    assert tool.nodes["protoc"].package.options.shared is True


def test_two_recipes_can_use_one_tool_with_different_options(tmp_path):
    write_recipe(tmp_path, "protoc")
    write_recipe(tmp_path, "codec", 'self.tool("../protoc", options={"shared": True})')
    write_recipe(tmp_path, "app", 'self.dep("../codec")\n        self.tool("../protoc")')

    graph = resolve(tmp_path / "app", BuildMode.Release)

    def tool_is_shared(user: str) -> bool:
        return graph.nodes[user].tools[0].nodes["protoc"].package.options.shared

    assert tool_is_shared("codec") is True
    assert tool_is_shared("app") is False


def test_a_tool_links_its_own_copy_of_what_its_user_also_links(tmp_path):
    write_recipe(tmp_path, "zlib")
    write_recipe(tmp_path, "protoc", 'self.dep("../zlib")')
    recipe = 'self.dep("../zlib", options={"shared": True})\n        self.tool("../protoc")'
    write_recipe(tmp_path, "app", recipe)

    graph = resolve(tmp_path / "app", BuildMode.Debug, debug_all=True)

    tool = graph.nodes["app"].tools[0]
    assert graph.nodes["zlib"].package.options.shared is True
    assert graph.nodes["zlib"].build_type is BuildMode.Debug
    assert tool.nodes["zlib"].package.options.shared is False
    assert tool.nodes["zlib"].build_type is BuildMode.Release


def test_debug_all_leaves_tools_in_release(tmp_path):
    write_recipe(tmp_path, "protobuf")
    write_recipe(tmp_path, "app", 'self.dep("../protobuf")\n        self.tool("../protobuf")')

    graph = resolve(tmp_path / "app", BuildMode.Debug, debug_all=True)

    assert graph.nodes["protobuf"].build_type is BuildMode.Debug
    tool = graph.nodes["app"].tools[0]
    assert tool.nodes["protobuf"].build_type is BuildMode.Release


def test_the_roots_overrides_and_options_do_not_reach_tools(tmp_path):
    write_recipe(tmp_path, "protobuf")
    recipe = (
        'self.dep("../protobuf")\n        self.tool("../protobuf")\n        '
        'self.override("protobuf", options={"shared": True})'
    )
    write_recipe(tmp_path, "app", recipe)

    graph = resolve(tmp_path / "app", BuildMode.Release)

    assert graph.nodes["protobuf"].package.options.shared is True
    assert graph.nodes["app"].tools[0].nodes["protobuf"].package.options.shared is False


def test_a_tool_that_needs_itself_is_an_error(tmp_path):
    write_recipe(tmp_path, "codegen", 'self.dep("../runtime")')
    write_recipe(tmp_path, "runtime", 'self.tool("../codegen")')
    write_recipe(tmp_path, "app", 'self.tool("../codegen")')

    with pytest.raises(ResolutionError, match="Tool cycle: codegen -> codegen"):
        resolve(tmp_path / "app", BuildMode.Release)


def test_a_tools_recipes_are_validated_too(tmp_path):
    write_recipe(tmp_path, "protoc")
    recipe = tmp_path / "protoc" / "silopkg.py"
    recipe.write_text(
        recipe.read_text(encoding="utf-8")
        + "\n\n    def validate(self):\n        raise InvalidConfiguration('no good')\n",
        encoding="utf-8",
    )
    write_recipe(tmp_path, "app", 'self.tool("../protoc")')

    with pytest.raises(InvalidConfiguration, match="protoc: no good"):
        validate(resolve(tmp_path / "app", BuildMode.Release))


def test_asking_a_static_only_recipe_for_a_shared_library_is_an_error(recipes):
    recipes("zlib")
    app = recipes("app", deps('self.dep("../zlib", options={"shared": True})'))

    with pytest.raises(ResolutionError, match="zlib was asked for as a shared library"):
        resolve(app, BuildMode.Release)
    with pytest.raises(ResolutionError, match="app was asked for as a shared library"):
        resolve(app, BuildMode.Release, cli_options={"": {"shared": True}})


def test_a_recipe_that_supports_shared_can_be_asked_for_it(recipes):
    recipes("zlib", "    supports_shared = True\n")
    app = recipes("app", deps('self.dep("../zlib", options={"shared": True})'))

    graph = resolve(app, BuildMode.Release)

    assert graph.nodes["zlib"].package.options.shared is True


def test_a_recipe_can_pick_its_dependencies_by_the_target_system(recipes, windows_profile):
    recipes("wayland")
    body = (
        "    def deps(self):\n"
        '        if self.profile.settings.os.value == "linux":\n'
        '            self.dep("../wayland")\n'
    )
    app = recipes("app", body)

    graph = resolve(app, BuildMode.Release, profile=windows_profile)

    assert list(graph.nodes) == ["app"]
