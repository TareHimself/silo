import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Generic, TypeVar, get_args, get_origin

from silo.build_context import BuildContext
from silo.build_profile import Profile
from silo.dependency import Dependency, OptionValue, Override, ResolvedDependency
from silo.enums import BuildMode, Platform
from silo.errors import CommandFailed, SiloError
from silo.options import Options

if TYPE_CHECKING:
    from silo.package import Package
    from silo.source import SourceSpec, SourceTree


T = TypeVar("T", bound=Options, default=Options)


class SiloPackage(Generic[T]):
    name: str
    version: str
    languages: tuple[str, ...] = ("c", "cxx")
    header_only: bool = False
    ignore_settings: tuple[str, ...] = ()
    # The oldest C++ standard the package compiles with, in its sources or its headers.
    # A profile below it is refused: one standard is used for every package of a graph.
    min_cppstd: int | None = None
    # The platforms the recipe builds on. Empty means every one.
    platforms: tuple[Platform, ...] = ()
    # True once the recipe acts on self.options.shared. Asking for shared is an error otherwise.
    supports_shared: bool = False
    _options_class: type[Options] = Options

    def __init_subclass__(cls, **kwargs) -> None:
        # class Zlib(SiloPackage[ZlibOptions]) picks ZlibOptions up from the type argument
        super().__init_subclass__(**kwargs)
        for base in getattr(cls, "__orig_bases__", ()):
            type_arguments = get_args(base)
            if get_origin(base) is SiloPackage and isinstance(type_arguments[0], type):
                cls._options_class = type_arguments[0]

    def __init__(self, path: Path, options: T) -> None:
        self._declared_deps: list[Dependency] = []
        self._declared_tools: list[Dependency] = []
        self._overrides: dict[str, Override] = {}
        self._resolved_deps: dict[str, ResolvedDependency] | None = None
        self._context: BuildContext | None = None
        self._profile: Profile | None = None
        self._path = path
        self.options: T = options

    @property
    def is_c_only(self) -> bool:
        return set(self.languages) == {"c"}

    @property
    def recipe_dir(self) -> Path:
        return self._path.parent

    # Declarations, called from deps()

    def dep(
        self,
        spec: str,
        options: dict[str, OptionValue] | None = None,
        *,
        git: str | None = None,
        commit: str | None = None,
        subdir: str = ".",
    ):
        """Link another package: "zlib@1.3.1" from a registry, or a path such as "../zlib".

        `git` and `commit` say where the recipe is for a package no registry has yet.
        `subdir` is the folder in that repository holding silopkg.py.
        """
        self._declared_deps.append(Dependency.from_str(spec, options, git, commit, subdir))

    def tool(
        self,
        spec: str,
        options: dict[str, OptionValue] | None = None,
        *,
        git: str | None = None,
        commit: str | None = None,
        subdir: str = ".",
        transitive: bool = False,
    ):
        """Use a program during the build.

        "cmake@4.3" is fetched ready-made. Anything else is another recipe, found the way
        self.dep() finds one and built first. Its executables land on the build's PATH and
        become CMake targets.

        `transitive` is for a program this package runs when it is itself used as a tool:
        whoever declares this package as a tool gets that program on PATH too.
        """
        self._declared_tools.append(
            Dependency.from_str(spec, options, git, commit, subdir, transitive)
        )

    def override(
        self,
        name: str,
        *,
        options: dict[str, OptionValue] | None = None,
        version: str | None = None,
        build_type: BuildMode | str | None = None,
        source: str | None = None,
    ):
        """Decide something about any package in the graph. Only the root's overrides apply."""
        decision = Override(
            options=options or {},
            version=version,
            build_type=BuildMode(build_type) if build_type else None,
            source=source,
        )
        earlier = self._overrides.get(name, Override())
        self._overrides[name] = earlier.merged_with(decision)

    # Available in every hook

    @property
    def profile(self) -> Profile:
        if self._profile is not None:
            return self._profile
        return self.context.profile

    # Available from validate() onward

    @property
    def dependencies(self) -> dict[str, ResolvedDependency]:
        if self._resolved_deps is None:
            raise RuntimeError("Dependencies are only resolved from validate() onward")
        return self._resolved_deps

    # Available in patch(), generate(), build() and package()

    @property
    def context(self) -> BuildContext:
        if self._context is None:
            raise RuntimeError("Build details are only available from patch() onward")
        return self._context

    @property
    def build_type(self) -> BuildMode:
        return self.context.build_type

    @property
    def is_debug(self) -> bool:
        return self.context.build_type is BuildMode.Debug

    @property
    def env(self) -> dict[str, str]:
        return self.context.env

    @property
    def source_dir(self) -> Path:
        return self.context.source_dir

    @property
    def build_dir(self) -> Path:
        return self.context.build_dir

    @property
    def install_dir(self) -> Path:
        return self.context.install_dir

    @property
    def local_source(self) -> bool:
        return self.context.local_source

    def run(
        self,
        args: list[str | Path],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        full_env = self.env | (env or {})
        # Windows would look the program up on silo's own PATH, not the build's
        program = shutil.which(str(args[0]), path=full_env["PATH"])
        if program is None:
            raise SiloError(f"'{args[0]}' is not a declared tool, so it is not on the build PATH")
        command = [program, *map(str, args[1:])]
        command_line = subprocess.list2cmdline(command)
        log = self.context.log
        if log is None:
            result = subprocess.run(command, cwd=cwd, env=full_env, check=False)
            output = "above"
        else:
            with log.open("ab") as log_file:
                log_file.write(f"$ {command_line}\n".encode())
                log_file.flush()
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    env=full_env,
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
            output = f"in {log}"
        if result.returncode != 0:
            raise CommandFailed(
                f"{self.name}: the command failed with exit code {result.returncode}. "
                f"Its output is {output}.\n  {command_line}",
                command_line,
                result.returncode,
            )

    # Hooks a recipe implements

    def source(self, src: "SourceSpec"):
        pass

    def patch(self, src: "SourceTree"):
        pass

    def deps(self):
        pass

    def validate(self):
        pass

    def generate(self):
        """Write the files a build system needs, such as a CMake toolchain file.

        Runs before build(). `silo sync` runs it on its own, once per build type, and the
        files land in the project's .silo/debug and .silo/release folders.
        """

    def build(self):
        pass

    def package(self) -> "Package | None":
        return None
