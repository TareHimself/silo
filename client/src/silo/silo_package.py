import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Generic, TypeVar, get_args, get_origin

from silo.build_context import BuildContext
from silo.build_profile import Profile
from silo.dependency import Dependency, OptionValue, Override, ResolvedDependency
from silo.enums import BuildMode
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
        aliases: dict[str, str] | None = None,
    ):
        """Depend on another recipe.

        `aliases` gives its targets extra names in this recipe's build only, for upstream
        build files that expect them: aliases={"ZLIB::ZLIB": "zlib::zlib"}.
        """
        self._declared_deps.append(Dependency.from_str(spec, options, aliases))

    def tool(self, spec: str, options: dict[str, OptionValue] | None = None):
        self._declared_tools.append(Dependency.from_str(spec, options))

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

    # Available from validate() onward

    @property
    def dependencies(self) -> dict[str, ResolvedDependency]:
        if self._resolved_deps is None:
            raise RuntimeError("Dependencies are only resolved from validate() onward")
        return self._resolved_deps

    # Available in patch(), build() and package()

    @property
    def context(self) -> BuildContext:
        if self._context is None:
            raise RuntimeError("Build details are only available in patch(), build() and package()")
        return self._context

    @property
    def profile(self) -> Profile:
        return self.context.profile

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
            raise RuntimeError(
                f"'{args[0]}' is not a declared tool, so it is not on the build PATH"
            )
        subprocess.run([program, *map(str, args[1:])], cwd=cwd, env=full_env, check=True)

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
        pass

    def build(self):
        pass

    def package(self) -> "Package | None":
        return None
