from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from silo.dependency import Dependency, OptionValue, Override, ResolvedDependency
from silo.enums import BuildMode
from silo.errors import InvalidConfiguration, ResolutionError
from silo.options import Options
from silo.silo_package import SiloPackage
from silo.source import SourceSpec
from silo.utils import get_package_file_path, load_package_cls

OptionValues = dict[str, OptionValue]

# A recipe's deps() can depend on its options, and its options on what others request,
# so resolving repeats until a pass changes nothing.
MAX_PASSES = 10


@dataclass
class Node:
    package: SiloPackage
    version: str
    source: SourceSpec
    build_type: BuildMode
    overridden: bool
    dependency_names: list[str]

    @property
    def name(self) -> str:
        return self.package.name


@dataclass
class Graph:
    root: str
    nodes: dict[str, Node]

    def build_order(self) -> list[Node]:
        """Every node after all of its dependencies."""
        ordered: list[Node] = []
        visiting: list[str] = []

        def visit(name: str) -> None:
            node = self.nodes[name]
            if node in ordered:
                return
            if name in visiting:
                cycle = " -> ".join([*visiting[visiting.index(name) :], name])
                raise ResolutionError(f"Dependency cycle: {cycle}")
            visiting.append(name)
            for dependency in node.dependency_names:
                visit(dependency)
            visiting.pop()
            ordered.append(node)

        visit(self.root)
        return ordered

    def transitive_dependencies(self, name: str) -> list[str]:
        found: list[str] = []
        pending = list(self.nodes[name].dependency_names)
        while pending:
            dependency = pending.pop()
            if dependency not in found:
                found.append(dependency)
                pending.extend(self.nodes[dependency].dependency_names)
        return sorted(found)


@dataclass
class _Decisions:
    """What one pass learned that shapes the next: option requests and the root's overrides."""

    requests: dict[str, dict[str, OptionValues]] = field(default_factory=dict)
    overrides: dict[str, Override] = field(default_factory=dict)


@dataclass
class _Pass:
    packages: dict[str, SiloPackage]
    edges: dict[str, list[str]]
    decisions: _Decisions


class _Resolver:
    def __init__(self, root_dir: Path, cli_options: dict[str, OptionValues]) -> None:
        self.recipe_dirs: dict[str, Path] = {}
        self.recipe_classes: dict[Path, type[SiloPackage]] = {}
        self.root = self._load_recipe(root_dir)
        # On the command line, an option with no package name is for the root
        self.cli_options = {name or self.root: values for name, values in cli_options.items()}

    def _load_recipe(self, recipe_dir: Path) -> str:
        """Returns the package name, and fails if another recipe already uses it."""
        recipe_dir = recipe_dir.resolve()
        if recipe_dir not in self.recipe_classes:
            package_cls = load_package_cls(recipe_dir)
            for attribute in ("name", "version"):
                if not isinstance(getattr(package_cls, attribute, None), str):
                    raise TypeError(f"{package_cls.__name__} must define '{attribute}'")
            self.recipe_classes[recipe_dir] = package_cls

        name = self.recipe_classes[recipe_dir].name
        known_dir = self.recipe_dirs.setdefault(name, recipe_dir)
        if known_dir != recipe_dir:
            raise ResolutionError(
                f"Two recipes provide '{name}': {known_dir} and {recipe_dir}. "
                "A graph holds one copy of each package."
            )
        return name

    def _dependency_name(self, dependency: Dependency, declared_by: SiloPackage) -> str:
        if dependency.path is None:
            raise ResolutionError(
                f"{declared_by.name} depends on '{dependency.name}', but only path dependencies "
                'are implemented so far. Write self.dep("../path/to/recipe").'
            )
        return self._load_recipe(declared_by.recipe_dir / dependency.path)

    def _options_for(self, name: str, decisions: _Decisions) -> Options:
        override = decisions.overrides.get(name, Override())
        decided = override.options | self.cli_options.get(name, {})

        requested: OptionValues = {}
        requested_by: dict[str, str] = {}
        for requester, options in decisions.requests.get(name, {}).items():
            for key, value in options.items():
                if key in decided:
                    continue
                if key in requested and requested[key] != value:
                    raise ResolutionError(
                        f"{requested_by[key]} and {requester} request different values for "
                        f"{name}:{key} ({requested[key]!r} and {value!r}). Decide it in the "
                        f'root recipe with self.override("{name}", options={{"{key}": ...}}).'
                    )
                requested[key] = value
                requested_by[key] = requester

        options_class = self.recipe_classes[self.recipe_dirs[name]]._options_class
        try:
            return options_class.model_validate(requested | decided)
        except ValidationError as error:
            raise ResolutionError(f"Invalid options for {name}:\n{error}") from error

    def run_pass(self, decisions: _Decisions) -> _Pass:
        packages: dict[str, SiloPackage] = {}
        edges: dict[str, list[str]] = {}
        requests: dict[str, dict[str, OptionValues]] = defaultdict(dict)
        overrides = decisions.overrides

        pending = [self.root]
        while pending:
            name = pending.pop()
            if name in packages:
                continue
            recipe_dir = self.recipe_dirs[name]
            package_cls = self.recipe_classes[recipe_dir]
            package = package_cls(
                get_package_file_path(recipe_dir), self._options_for(name, decisions)
            )
            package.deps()
            packages[name] = package
            if name == self.root:
                overrides = dict(package._overrides)

            edges[name] = []
            for dependency in package._declared_deps:
                dependency_name = self._dependency_name(dependency, package)
                edges[name].append(dependency_name)
                if dependency.options:
                    requests[dependency_name][name] = dependency.options
                pending.append(dependency_name)

        return _Pass(packages, edges, _Decisions(dict(requests), overrides))

    def settle(self) -> _Pass:
        decisions = _Decisions()
        for _ in range(MAX_PASSES):
            result = self.run_pass(decisions)
            if result.decisions == decisions:
                return result
            decisions = result.decisions
        raise ResolutionError(
            f"The graph did not settle after {MAX_PASSES} passes. A recipe's deps() "
            "probably keeps changing in response to its own requests."
        )


def _check_overrides(result: _Pass, cli_options: dict[str, OptionValues]) -> None:
    for name in cli_options:
        if name not in result.packages:
            raise ResolutionError(f"Options were given for '{name}', which is not in the graph")
    for name, override in result.decisions.overrides.items():
        if name not in result.packages:
            raise ResolutionError(f"The root recipe overrides '{name}', which is not in the graph")
        actual = result.packages[name].version
        if override.version and not override.source and override.version != actual:
            raise ResolutionError(
                f"The root recipe pins {name} to {override.version}, but the recipe on disk is "
                f"{actual}. Version pins need version resolution, which is not implemented yet."
            )


def _resolve_source(package: SiloPackage, override: Override, root_dir: Path) -> SourceSpec:
    """The recipe's declared source, or the folder the root recipe pointed it at."""
    source = SourceSpec()
    if override.source:
        source.local(override.source)
        source.snapshot_local(root_dir)
        return source

    package.source(source)
    if source.local_source:
        source.snapshot_local(package.recipe_dir)
    return source


def resolve(
    root_dir: Path,
    root_build_type: BuildMode,
    cli_options: dict[str, OptionValues] | None = None,
) -> Graph:
    """Load the root recipe and everything it depends on, with overrides and options applied.

    `cli_options` maps a package name to its options. The key "" means the root package.
    """
    resolver = _Resolver(root_dir, cli_options or {})
    result = resolver.settle()
    _check_overrides(result, resolver.cli_options)

    overrides = result.decisions.overrides
    nodes: dict[str, Node] = {}
    for name, package in result.packages.items():
        override = overrides.get(name, Override())
        # Dependencies are release unless the root says otherwise, so prebuilts can be used
        default_build_type = root_build_type if name == resolver.root else BuildMode.Release
        source = _resolve_source(package, override, result.packages[resolver.root].recipe_dir)
        nodes[name] = Node(
            package=package,
            # A source override can say which version the folder it points at really is
            version=(override.source and override.version) or package.version,
            source=source,
            build_type=override.build_type or default_build_type,
            overridden=name in overrides or name in resolver.cli_options,
            dependency_names=result.edges[name],
        )

    for node in nodes.values():
        node.package._resolved_deps = {
            dependency: ResolvedDependency(
                name=dependency,
                version=nodes[dependency].version,
                options=nodes[dependency].package.options,
                build_type=nodes[dependency].build_type,
                overridden=nodes[dependency].overridden,
                local_source=nodes[dependency].source.local_source,
            )
            for dependency in node.dependency_names
        }
    return Graph(resolver.root, nodes)


def validate(graph: Graph) -> None:
    """Give every recipe the chance to reject the resolved graph, before anything builds."""
    for node in graph.nodes.values():
        try:
            node.package.validate()
        except InvalidConfiguration as error:
            raise InvalidConfiguration(f"{node.name}: {error}") from error
