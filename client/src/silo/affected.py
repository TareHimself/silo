import subprocess
from pathlib import Path

from silo.build_profile import Profile
from silo.dependency_graph import Graph, resolve, validate
from silo.enums import BuildMode
from silo.errors import InvalidConfiguration, SiloError
from silo.registry import POINTER_FILE, RECIPE_FILE, RECIPES_DIR, RecipeLookup, Registry


def registry_entries(root: Path) -> list[Path]:
    """Every recipes/<name>/<version> folder of the registry at `root`."""
    return sorted(
        entry
        for entry in (root / RECIPES_DIR).glob("*/*")
        if (entry / RECIPE_FILE).is_file() or (entry / POINTER_FILE).is_file()
    )


def _git(root: Path, *args: str) -> list[str]:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SiloError(f"git {' '.join(args)} failed in {root}:\n{result.stderr.strip()}")
    return result.stdout.splitlines()


def changed_entries(root: Path, since: str) -> set[Path]:
    """The registry folders that differ from where this branch left `since`.

    Uncommitted and untracked files count, so it answers the same before and after a commit.
    """
    base = _git(root, "merge-base", since, "HEAD")[0]
    files = _git(root, "diff", "--name-only", "--relative", base)
    files += _git(root, "ls-files", "--others", "--exclude-standard")
    changed = set()
    for file in files:
        parts = Path(file).parts
        if len(parts) > 3 and parts[0] == RECIPES_DIR:
            changed.add(root / RECIPES_DIR / parts[1] / parts[2])
    return changed


def _recipe_dirs(graph: Graph) -> set[Path]:
    """The folder of every recipe a graph uses, the ones its tools use included."""
    found = set()
    for node in graph.nodes.values():
        found.add(node.package.recipe_dir.resolve())
        for tool in node.tools:
            found |= _recipe_dirs(tool)
    return found


def affected_entries(root: Path, changed: set[Path] | None, profile: Profile) -> list[Path]:
    """The registry folders whose build uses a changed recipe, with default options.

    `changed` left out means every folder. A recipe whose validate() refuses the profile,
    such as a Linux library on Windows, is left out.
    """
    root = root.resolve()
    lookup = RecipeLookup.load(root)
    if not lookup.registries:
        lookup.registries.append(Registry(root.name, path=root))

    affected = []
    for entry in registry_entries(root):
        name, version = entry.parent.name, entry.name
        recipe_dir = lookup.find(name, version, "silo affected")
        try:
            graph = resolve(recipe_dir, BuildMode.Release, profile=profile, lookup=lookup)
            validate(graph)
        except InvalidConfiguration:
            continue
        if changed is None or (_recipe_dirs(graph) | {entry}) & changed:
            affected.append(entry)
    return affected
