# silo

A C++ package manager: builds dependencies from source in an isolated environment and keeps them in a local store. Design notes live on relay, in the `silo` project.

## Use

```
uv run --package silo silo profile detect             # writes <SILO_HOME>/profiles/default.toml
uv run --package silo silo build recipes/zlib         # builds into <SILO_HOME>/store
uv run --package silo silo build examples/zapp        # a local project: zapp -> freetype -> zlib
uv run --package silo silo build examples/zapp --debug  # root in debug, dependencies stay release
uv run --package silo silo sync examples/zapp         # build the dependencies, write examples/zapp/.silo
uv run --package silo silo sync examples/zapp --debug-all  # debug preset with debug dependencies
uv run --package silo silo graph examples/zapp        # resolve and print the graph, build nothing
uv run --package silo silo build examples/webm --report out  # report.json and a log per package
uv run --package silo silo run -C examples/zapp -- cmake --version  # any command, in the build environment
uv run --package silo silo cache list                 # sizes of the caches under <SILO_HOME>/cache
uv run --package silo silo cache clear builds git     # delete some caches, or all with no names
```

`SILO_HOME` defaults to `~/.silo`. It holds `store` (built packages), `profiles`, and `cache`. Everything under `cache` can be deleted at any time: `builds`, `downloads`, `git`, `snapshots` and `conan`. A build folder is deleted once its package is in the store, except for local sources (kept so rebuilds are incremental) and failed builds (kept for inspection). Each build folder is locked, so a second silo building the same package waits and then reuses the result. Pass options with `-o key=value` for the root package or `-o zlib:key=value` for a dependency. `--source zlib=../zlib` builds that package from a local folder for one run.

## Develop

```
uv sync --all-packages
uv run --package silo pytest client/tests
uvx ruff format . && uvx ruff check .
```

## Using silo only for dependencies

`silo sync` builds a project's dependencies into the store and runs the recipe's `generate()` once for debug and once for release, without building the project:

```
.silo/
  CMakePresets.json     includes the two below
  debug/                CMakePresets.json, silo-toolchain.cmake, cmake/ (dependency configs)
  release/              the same for release
```

| Command | Writes | Dependencies |
|---|---|---|
| `silo sync` | both folders | release |
| `silo sync --debug` or `--release` | that folder only | release |
| `silo sync --debug-all` | `debug` only | debug |

`silo build` and `silo graph` take `--debug` (this package only) and `--debug-all` (this package and everything it links; tools stay release).

`silo build --report <folder>` is for scripts, CI and AI agents. The terminal shows one status line per package, and the folder gets `report.json` (whether it worked, the root's store path, and per package its status `built`, `cached` or `failed`, store path, error, failed command and exit code) plus `logs/<package>.log` with the output of that package's commands.

Each folder's presets file has a hidden preset, `silo-debug` or `silo-release`, with the toolchain file, the generator, silo's CMake and the compiler's environment, so it works from any shell or editor. A recipe adds its own presets on top with `CMakePresets` (see `examples/zapp/silopkg.py`), or a project writes presets by hand that inherit the hidden one. Either way the project's own `CMakePresets.json` includes `.silo/CMakePresets.json`:

```
cmake --preset zapp-debug
cmake --build --preset zapp-debug
```

The `.silo` folder ignores itself in git.

## Shared libraries at run time

A shared dependency is a `SHARED IMPORTED` target, so `$<TARGET_RUNTIME_DLLS:app>` lists its DLLs. A project installs them beside its program, and the stored package then runs by itself (see `examples/webm/CMakeLists.txt`):

```cmake
install(TARGETS app RUNTIME DESTINATION bin)
install(FILES $<TARGET_RUNTIME_DLLS:app> DESTINATION bin)
```

A recipe without a `package()` hook keeps everything its build installed into `bin` when it holds a program. Static dependencies add nothing to the list, since they are already inside the binary.

## Tools

A recipe declares the programs its build runs in `deps()`:

```python
self.tool("cmake@4.3")  # fetched ready-made from PyPI (cmake, ninja and conan so far)
self.tool("../greetgen")  # another recipe, built first
```

A tool recipe's executables are put on the build's `PATH` and become CMake targets named `<package>::<program>`, so `find_package(greetgen)` gives `greetgen::greetgen` (see `examples/zapp/CMakeLists.txt`). Folders holding the shared libraries of dependencies and tools are on the search path too, so tests and tools start. `silo run -- <command>` runs anything in that same environment.

Each tool recipe is a graph of its own, separate from what its user links:

| | What a package links | A tool |
|---|---|---|
| Copies of one package | One in the whole graph | One per tool. Two recipes may use different versions or options of a tool |
| Build type | The root's choice, `--debug-all` | Always release |
| Options | Requests, the root's overrides, the command line | The `options=` of the `self.tool()` call, else defaults |
| Seen by packages that depend on the user | Yes | No |

Nothing is shared between these graphs by rule. The store does it: two tools that need the same build of a package get the same store entry. `silo graph` prints each tool's graph indented under the package that runs it.

## Writing recipes

A recipe is a `silopkg.py` holding a class that extends `SiloPackage`. `recipes/tinyxml2` is the smallest CMake one and `recipes/msdfgen` uses most features.

| Hook | Does | Can read |
|---|---|---|
| `source(src)` | `src.fetch(url, sha256=)`, `src.git(url, commit=)`, `src.local(".")` or `src.empty()` | `self.options` |
| `patch(src)` | `src.apply("fix.patch")`, `src.replace(file, old, new)` | the build context |
| `deps()` | `self.dep("../zlib")`, `self.tool("cmake@4.3")` | `self.options`, `self.profile` |
| `validate()` | Raises `InvalidConfiguration` for a graph it cannot work with | also `self.dependencies` |
| `generate()` | Writes build system files, usually `CMakeDeps` and `CMakeGenerator` | everything |
| `build()` | Usually `CMakeBuild`: configure, build, install | everything |
| `package()` | Returns a `Package` of `Component`s: headers, libraries, programs and what they require | everything |

- `self.profile` is known in every hook, so `deps()` can pick dependencies by target system (`self.profile.settings.os`).
- A recipe that can build a shared library sets `supports_shared = True` and acts on `self.options.shared`. Its options class can change the default.
- Upstream build files often expect other target names. `CMakeDeps(self).alias("ZLIB::ZLIB", "zlib::zlib")` adds the name for this build only and makes `find_package(ZLIB)` work. An alias for a package or component that is not there fails in `generate()`.
- The toolchain file stops CMake from finding packages installed on the machine. A recipe that needs one calls `CMakeGenerator(self).allow_system_packages()`.
- silo builds everything against the release DLL runtime on Windows (`/MD`), in debug builds too. An upstream build file that picks another one has to be told not to (see `recipes/libwebm` and `recipes/msdfgen`).

### Libraries silo cannot build yet

`ConanInstall` gets a finished package from Conan Center for a library whose own build silo cannot drive (Meson, autotools). silo fetches Conan, writes its profile from silo's own on every build and keeps Conan's files in `<SILO_HOME>/cache/conan`, so there is nothing to set up:

```python
def source(self, src):
    src.empty()

def deps(self):
    self.tool("conan@2")

def build(self):
    ConanInstall(self).install("dav1d/1.4.3#5e2459e132c77183bd16d23d12fd8f4a")
```

It only describes MSVC to Conan so far, and it suits packages without dependencies of their own. `settings=` replaces entries of the profile for a package that refuses the real ones (see `recipes/libvpx`).

## How a build flows

```
cli.build
  -> builder.build_graph
       dependency_graph.resolve        load the root recipe and its dependencies, apply the
                                       root's overrides and option requests, repeat until stable
       dependency_graph.validate       every recipe's validate() can reject the graph
       for each package, dependencies first (builder.build_node):
         build_id.make_build_id        recipe files + source + profile + build type + options
                                       + the build ids of its dependencies
         store hit?  -> next package
         tool_resolver.resolve_tool    cmake, ninja and conan from PyPI, through uv
         platform backend .build_env   a clean environment, nothing inherited from the shell
         builder.prepare_source        fetched: download, check sha256, unpack
                                       local: check out a git snapshot of the folder as it is now
                                       then the recipe's patch()
         recipe.generate()             usually CMakeDeps (a config file per dependency) and
                                       CMakeGenerator (the toolchain file)
         recipe.build()                usually CMakeBuild, which configures with that toolchain
         package.write_package         copy what package() lists, reject it if the install
                                       prefix is compiled in (verifier), write silo/package.json
```

## Where things are

| Path | Holds |
|---|---|
| `client/src/silo/silo_package.py` | `SiloPackage`, the base class every recipe extends |
| `client/src/silo/dependency.py` | What recipes declare (`Dependency`, `Override`) and see (`ResolvedDependency`) |
| `client/src/silo/dependency_graph.py` | Graph resolution, overrides, option precedence, `validate` |
| `client/src/silo/builder.py` | The build pipeline above |
| `client/src/silo/build_context.py` | What silo hands a recipe during a build (dirs, env, profile) |
| `client/src/silo/build_id.py` | The cache key |
| `client/src/silo/build_profile.py` | The profile file: what this machine can build with |
| `client/src/silo/package.py` | `Package` and `Component`, and the `package.json` writer |
| `client/src/silo/source.py` | Source declaration, download and patch helpers |
| `client/src/silo/git_snapshot.py` | Hash and copy a local folder through git, without touching its repo |
| `client/src/silo/verifier.py` | Rejects a package that has its install prefix compiled in |
| `client/src/silo/tool_resolver.py` | Build tools installed through uv |
| `client/src/silo/errors.py` | Errors the CLI prints without a traceback |
| `client/src/silo/report.py` | What `silo build --report` writes |
| `client/src/silo/platform/` | Everything OS specific, behind `PlatformBackend` |
| `client/src/silo/tools/cmake/` | For recipes: `CMakeGenerator` (toolchain file), `CMakeDeps` (dependency configs), `CMakePresets`, `CMakeBuild` |
| `client/src/silo/tools/conan/` | For recipes: `ConanInstall`, which gets a finished package from Conan when silo cannot drive its build. See `recipes/libvpx` |
| `client/src/silo/cache.py` | The caches under `<SILO_HOME>/cache` and how to clear them |
| `recipes/` | Recipes (`silopkg.py`) for third-party libraries: zlib, freetype, libpng, tinyxml2, msdfgen, opus, libyuv, libwebm, miniaudio, the Vulkan headers and loader, vk-bootstrap, and (through Conan) libvpx and dav1d. Also rwin and webmdx |
| `examples/sdf/` | A local project that links msdfgen and its whole dependency chain |
| `examples/vpx/` | A local project that links libvpx, which silo gets from Conan |
| `examples/webm/` | A local project that links webmdx and, through it, five codec and container libraries |
| `examples/zapp/` | A local project: `src.local(".")`, a path dependency with an alias, a tool, presets and a `validate` hook |
| `examples/greetgen/` | A code generator that zapp uses as a tool |
| `client/tests/` | Unit tests |

To add a platform, implement `PlatformBackend` (`platform/base.py`) in its own folder and return it from `backend_for` in `platform/__init__.py`. Nothing outside `platform/` should check the operating system.

## Not built yet

- Dependencies by name (`zlib@1.3`). They need a registry, so only paths work: `self.dep("../zlib")`.
- `src.git(url, tag=...)` and version pins, which wait for the lockfile. `src.git(url, commit=..., submodules=...)` works.
- Submodules in a local source.
- The lockfile, publishing prebuilts, and Linux and macOS builds. `recipes/rwin` is Windows only until its Wayland dependencies have recipes.
- `ConanInstall` for compilers other than MSVC, and for packages with dependencies of their own.
- A check that every library in a link uses the same C runtime. A mismatch shows up only when a consumer links.
