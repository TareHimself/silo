import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from filelock import FileLock

from silo import paths
from silo.build_id import make_build_id
from silo.builder import (
    NodeInputs,
    WorkDirs,
    build_environment,
    build_node,
    run_command,
    sync_graph,
    work_lock,
)
from silo.dependency_graph import resolve
from silo.enums import BuildMode
from silo.errors import SiloError
from silo.report import BuildReport

RECIPE = """\
from silo import Component, Package, SiloPackage


class Demo(SiloPackage):
    name = "demo"
    version = "1.0"
    header_only = True

    def source(self, src):
        src.{source}

    def generate(self):
        self.context.generated_dir.mkdir(parents=True, exist_ok=True)
        (self.context.generated_dir / "generated.txt").write_text("from generate")

    def build(self):
        assert (self.context.generated_dir / "generated.txt").is_file()
        if (self.source_dir / "broken").exists():
            raise RuntimeError("compiler said no")
        header = self.install_dir / "include" / "demo.h"
        header.parent.mkdir(parents=True)
        header.write_text((self.source_dir / "demo.h").read_text())

    def package(self):
        return Package(components=[Component("demo", headers=["include"])])
"""


class FakeBackend:
    runtime_library_variable = "PATH"

    def build_env(self, profile, tool_dirs, tmp):
        FakeBackend.tool_dirs = tool_dirs
        return dict(os.environ) | {"TEMP": str(tmp)}


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch):
    monkeypatch.setattr("silo.builder.backend_for", lambda _os: FakeBackend())


def write(path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def git(repo, *args: str) -> str:
    identity = ["-c", "user.name=test", "-c", "user.email=test@example.com"]
    result = subprocess.run(
        ["git", *identity, *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def upstream(tmp_path):
    def make(files: dict[str, str]) -> str:
        repo = tmp_path / "upstream"
        repo.mkdir()
        git(repo, "init", "--quiet")
        for name, text in files.items():
            write(repo / name, text)
        git(repo, "add", "--all")
        git(repo, "commit", "--quiet", "-m", "first")
        commit = git(repo, "rev-parse", "HEAD")
        return f'git("{repo.as_uri()}", commit="{commit}")'

    return make


def build(recipe_dir, profile):
    node = resolve(recipe_dir, BuildMode.Release).nodes["demo"]
    build_id = make_build_id(node.package, node.source, profile, node.build_type)
    return build_node(node, build_id, profile, NodeInputs())


def build_folders() -> list[str]:
    return sorted(path.name for path in paths.builds_dir().iterdir() if path.is_dir())


def test_a_fetched_package_leaves_no_build_folder(upstream, tmp_path, windows_profile):
    write(tmp_path / "recipe" / "silopkg.py", RECIPE.format(source=upstream({"demo.h": "// h\n"})))

    store_path = build(tmp_path / "recipe", windows_profile)

    assert (store_path / "include" / "demo.h").is_file()
    assert build_folders() == []


def test_a_failed_build_keeps_its_folder(upstream, tmp_path, windows_profile):
    source = upstream({"demo.h": "// h\n", "broken": ""})
    write(tmp_path / "recipe" / "silopkg.py", RECIPE.format(source=source))

    with pytest.raises(RuntimeError, match="compiler said no"):
        build(tmp_path / "recipe", windows_profile)

    assert len(build_folders()) == 1


def test_a_local_package_keeps_its_build_folder(git_repo, windows_profile):
    write(git_repo / "silopkg.py", RECIPE.format(source='local(".")'))
    write(git_repo / "demo.h", "// h\n")

    build(git_repo, windows_profile)

    assert len(build_folders()) == 1


def test_work_lock_waits_for_whoever_holds_it(tmp_path, capsys):
    dirs = WorkDirs(tmp_path / "builds" / "demo-abc")
    entered = threading.Event()

    def second_build():
        with work_lock(dirs, "demo"):
            entered.set()

    dirs.lock_file.parent.mkdir(parents=True)
    holder = FileLock(dirs.lock_file)
    holder.acquire()
    thread = threading.Thread(target=second_build)
    thread.start()
    assert not entered.wait(0.5)
    holder.release()
    thread.join(10)

    assert entered.is_set()
    assert "waiting for another silo process" in capsys.readouterr().out


def test_work_lock_is_released_when_the_build_fails(tmp_path):
    dirs = WorkDirs(tmp_path / "builds" / "demo-abc")

    with pytest.raises(SiloError), work_lock(dirs, "demo"):
        raise SiloError("build failed")

    FileLock(dirs.lock_file).acquire(timeout=0)


BOTH = [BuildMode.Debug, BuildMode.Release]

APP_RECIPE = """\
from silo import SiloPackage


class App(SiloPackage):
    name = "app"
    version = "1.0"

    def source(self, src):
        src.local(".")

    def deps(self):
        self.dep("../demo")

    def generate(self):
        names = sorted(self.context.dependency_packages)
        text = ",".join(names) + " " + self.build_type.value
        (self.context.generated_dir / "deps.txt").write_text(text)

    def build(self):
        raise RuntimeError("sync must not build the root")
"""


@pytest.fixture
def app_with_demo(git_repo):
    write(git_repo / "demo" / "silopkg.py", RECIPE.format(source='local(".")'))
    write(git_repo / "demo" / "demo.h", "// h\n")
    write(git_repo / "app" / "silopkg.py", APP_RECIPE)
    return git_repo / "app"


def test_sync_builds_dependencies_and_generates_into_the_project(app_with_demo, windows_profile):
    generated = sync_graph(app_with_demo, windows_profile, BOTH)

    assert generated == app_with_demo / ".silo"
    assert (generated / "debug" / "deps.txt").read_text() == "demo debug"
    assert (generated / "release" / "deps.txt").read_text() == "demo release"
    stored = [path.name.split("-")[0] for path in paths.store_dir().iterdir()]
    assert stored == ["demo"]


def test_the_generated_folder_does_not_change_the_projects_snapshot(app_with_demo, windows_profile):
    before = resolve(app_with_demo, BuildMode.Release).nodes["app"].source.id

    sync_graph(app_with_demo, windows_profile, BOTH)

    assert resolve(app_with_demo, BuildMode.Release).nodes["app"].source.id == before


def stored_build_types() -> list[str]:
    manifests = sorted(paths.store_dir().glob("demo-*/silo/package.json"))
    return [path.parent.parent.name for path in manifests]


def test_sync_of_one_build_type_leaves_the_other_folder_alone(app_with_demo, windows_profile):
    generated = sync_graph(app_with_demo, windows_profile, BOTH)
    marker = generated / "release" / "marker.txt"
    marker.write_text("still here")

    sync_graph(app_with_demo, windows_profile, [BuildMode.Debug])

    assert marker.read_text() == "still here"
    assert (generated / "debug" / "deps.txt").is_file()


def test_both_build_types_share_release_dependencies(app_with_demo, windows_profile):
    sync_graph(app_with_demo, windows_profile, BOTH)

    assert len(stored_build_types()) == 1


def test_debug_all_builds_the_dependencies_in_debug_too(app_with_demo, windows_profile):
    # A header-only package is the same in debug and release, so make demo a compiled one
    demo_recipe = app_with_demo.parent / "demo" / "silopkg.py"
    write(demo_recipe, demo_recipe.read_text().replace("header_only = True", "pass"))

    sync_graph(app_with_demo, windows_profile, [BuildMode.Release])
    sync_graph(app_with_demo, windows_profile, [BuildMode.Debug], debug_all=True)

    assert len(stored_build_types()) == 2


def test_debug_all_beats_a_recipes_build_type_override(app_with_demo):
    recipe = app_with_demo / "silopkg.py"
    text = recipe.read_text().replace(
        'self.dep("../demo")',
        'self.dep("../demo")\n        self.override("demo", build_type="release")',
    )
    write(recipe, text)

    graph = resolve(app_with_demo, BuildMode.Debug, debug_all=True)

    assert {node.build_type for node in graph.nodes.values()} == {BuildMode.Debug}


def stored_package(name: str, artifacts: list[dict]) -> Path:
    package_dir = paths.store_dir() / f"{name}-1.0-abc"
    component = {"artifacts": artifacts, "requires": [], "defines": [], "system_libs": []}
    manifest = {"name": name, "version": "1.0", "components": {name: component}}
    write(package_dir / "silo" / "package.json", json.dumps(manifest))
    return package_dir


def test_the_environment_finds_tool_programs_and_shared_libraries(
    load_demo_recipe, windows_profile, tmp_path, monkeypatch
):
    monkeypatch.setenv("PATH", "/system")
    protoc = stored_package("protoc", [{"type": "executable", "path": "bin/protoc.exe"}])
    zlib = stored_package("zlib", [{"type": "shared_lib", "path": "bin/zlib.dll"}])
    abseil = stored_package("abseil", [{"type": "shared_lib", "path": "lib/abseil.dll"}])
    inputs = NodeInputs(
        dependencies={"zlib": zlib}, tools={"protoc": protoc}, tool_runtime=(protoc, abseil)
    )

    env = build_environment(load_demo_recipe(""), windows_profile, inputs, tmp_path)

    searched = env["PATH"].split(os.pathsep)
    assert searched == [str(zlib / "bin"), str(abseil / "lib"), "/system"]
    assert FakeBackend.tool_dirs == [protoc / "bin"]


def test_run_command_runs_in_the_environment_and_returns_the_exit_code(
    app_with_demo, windows_profile, capfd
):
    script = "import os, sys; print(os.environ['TEMP'] != ''); sys.exit(3)"

    exit_code = run_command(app_with_demo, windows_profile, [sys.executable, "-c", script])

    assert exit_code == 3
    output = capfd.readouterr()
    assert output.out.strip() == "True"
    assert "demo-1.0" in output.err
    assert not any(path.name.startswith("app-") for path in paths.store_dir().iterdir())


def test_run_command_reports_a_program_that_is_not_there(app_with_demo, windows_profile):
    with pytest.raises(SiloError, match="'nosuchtool' is not on the build PATH of app"):
        run_command(app_with_demo, windows_profile, ["nosuchtool"])


def build_with_report(recipe_dir, profile, report):
    node = resolve(recipe_dir, BuildMode.Release).nodes["demo"]
    build_id = make_build_id(node.package, node.source, profile, node.build_type)
    return build_node(node, build_id, profile, NodeInputs(), report)


def test_the_report_says_what_was_built_and_what_was_already_there(
    upstream, tmp_path, windows_profile
):
    write(tmp_path / "recipe" / "silopkg.py", RECIPE.format(source=upstream({"demo.h": "// h\n"})))

    first = BuildReport(tmp_path / "first")
    store_path = build_with_report(tmp_path / "recipe", windows_profile, first)
    second = BuildReport(tmp_path / "second")
    build_with_report(tmp_path / "recipe", windows_profile, second)

    report = json.loads(first.write(store_path).read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["store_path"] == store_path.as_posix()
    assert [package["status"] for package in report["packages"]] == ["built"]
    assert report["packages"][0]["store_path"] == store_path.as_posix()
    assert [package["status"] for package in second.packages.values()] == ["cached"]


def test_the_report_names_the_package_that_failed(upstream, tmp_path, windows_profile):
    source = upstream({"demo.h": "// h\n", "broken": ""})
    write(tmp_path / "recipe" / "silopkg.py", RECIPE.format(source=source))
    report = BuildReport(tmp_path / "out")

    with pytest.raises(RuntimeError) as failure:
        build_with_report(tmp_path / "recipe", windows_profile, report)

    written = json.loads(report.write(error=failure.value).read_text(encoding="utf-8"))
    assert written["ok"] is False
    assert written["packages"][0]["status"] == "failed"
    assert written["packages"][0]["error"] == "compiler said no"


def test_a_new_report_replaces_the_logs_of_the_last_one(tmp_path):
    stale = tmp_path / "out" / "logs" / "old.log"
    write(stale, "old")

    BuildReport(tmp_path / "out")

    assert not stale.exists()
