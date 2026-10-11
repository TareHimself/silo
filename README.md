# silo

A C++ package manager: builds dependencies from source in an isolated environment and keeps them in a local store.

## Use

```
uv run --package silo silo profile detect             # writes <SILO_HOME>/profiles/default.toml
uv run --package silo silo build ../silo-recipes/recipes/zlib/1.3.1  # builds into <SILO_HOME>/store
uv run --package silo silo build examples/zapp        # a local project: zapp -> freetype -> zlib
uv run --package silo silo build examples/zapp --debug  # root in debug, dependencies stay release
uv run --package silo silo sync examples/zapp         # build the dependencies, write examples/zapp/.silo
uv run --package silo silo sync examples/zapp --debug-all  # debug preset with debug dependencies
uv run --package silo silo graph examples/zapp        # resolve and print the graph, build nothing
uv run --package silo silo build examples/sdf --report out   # report.json and a log per package
uv run --package silo silo run -C examples/zapp -- cmake --version  # any command, in the build environment
uv run --package silo silo cache list                 # sizes of the caches under <SILO_HOME>/cache
uv run --package silo silo cache clear builds git     # delete some caches, or all with no names
```

`SILO_HOME` defaults to `~/.silo`. It holds `store` (built packages), `profiles`, and `cache`. Everything under `cache` can be deleted at any time: `builds`, `downloads`, `git`, `snapshots`, `conan` and `registries`. A build folder is deleted once its package is in the store, except for local sources (kept so rebuilds are incremental) and failed builds (kept for inspection). Each build folder is locked, so a second silo building the same package waits and then reuses the result. Pass options with `-o key=value` for the root package or `-o zlib:key=value` for a dependency. `--source zlib=../zlib` builds that package from a local folder for one run.

## Registries

Recipes live outside this repository, in registries. A registry is a folder or a git repository laid out as `recipes/<name>/<version>/silopkg.py`. The recipes silo is developed against are in `silo-recipes`.

A project lists its registries in `silo.config.toml`, next to its recipe or in any folder above it:

```toml
[[registry]]
name = "silo-recipes"
git = "https://github.com/TareHimself/silo-recipes"
rev = "main"              # optional

[[registry]]
name = "mine"
path = "../my-recipes"    # relative to this file
```

and depends on packages by name and exact version: `self.dep("zlib@1.3.1")`, `self.tool("wayland@1.22.0")`. A path still works for a recipe that is not in a registry: `self.dep("../greetgen")`.

| `rev` | silo does |
|---|---|
| left out, a branch or a tag | Asks the remote where it is once per run (`git ls-remote`, no download) and fetches only a commit it does not have. Offline, it uses the last copy and says so |
| a full commit hash | Stays on that commit. No network once it is fetched |

### A library that keeps its own recipe

A library such as webmdx has its `silopkg.py` in its own repository, saying `src.local(".")`: build the folder I am in. That recipe is never rewritten to be published. A git registry lists it with a pointer file in place of a recipe:

```
recipes/zlib/1.3.1/silopkg.py        # a third-party library: the recipe is here
recipes/webmdx/1.0.0/silopkg.toml    # a library with its own recipe: where that is
```

```toml
git = "https://github.com/TareHimself/webmdx"
commit = "c741ae6ec0e22f48926c7ba473c718be22b0556d"
subdir = "."              # optional
```

silo fetches that commit, uses the recipe in it and builds that commit's files. Whoever depends on `webmdx@1.0.0` sees no difference.

- The commit is a full hash, and the recipe there has to carry the name and version of the folder the pointer is in.
- A folder holds a recipe or a pointer, not both.
- The entry lasts as long as that commit can be fetched. A tag on it keeps a force-push from orphaning it.

### A package that is not in a registry

Registries are the normal way to get a package. For one that is not in a registry yet, or that is being worked on alongside the project, there are two ways to say where its recipe is.

The project's config, which has the last word:

```toml
[package.webmdx]
git = "https://github.com/TareHimself/webmdx"
rev = "ee5da08a378b0e8818c520c6fa883ebed44b7a2f"
subdir = "."              # optional: where silopkg.py is in that repository

[package.rwin]
path = "../rwin"          # a folder, while working on both
```

Recipes still say `self.dep("webmdx@1.0.0")`. They state what they need, and the root project decides where it comes from, so moving a package between a pinned commit and a local checkout is a config edit.

A recipe, for a dependency of its own that no registry has:

```python
self.dep("ebml@1.4.5", git="https://github.com/Matroska-Org/libebml", commit="4f2a91c0...", subdir=".")
```

Everyone who depends on that recipe then gets ebml without repeating the location. `self.tool` takes the same arguments.

- Order: the project's `[package.<name>]` entry, then the location the asking recipe gave, then the registries.
- In a recipe the commit has to be a full hash. Following a branch or tag is only for the project's own config, so a dependency cannot make a build change from one day to the next.
- Two recipes that point one package at different places stop the build. A `[package.<name>]` entry in the project's config chooses.
- `rev` works as it does for a registry: a full commit hash stays put, a branch or tag is followed.
- The version in `self.dep` is optional for such a package. When given, it has to match the recipe's.
- A recipe taken from a commit usually says `src.local(".")`, meaning the folder it sits in. silo then builds that commit's files, and the build id names the commit.

### Rules

- Registries are checked in order, and the first one that has the package name at all decides. A later registry cannot shadow an earlier one, and the answer never depends on which recipe asks.
- Only the root project's `silo.config.toml` counts. A dependency's own file is ignored.
- Each fetched commit is its own folder under `<SILO_HOME>/cache/registries` and is never changed.
- Publishing a recipe is a `git push` to the registry. A new version is a new folder.
- A recipe's hash is the bytes of the files in its folder, so it is the same in a working copy, a fetched registry or an unpacked archive. A recipe file with Windows line endings (CRLF) is refused. A `.gitattributes` with `* text=auto eol=lf` keeps a registry on LF for everyone.
- For a project's own recipe, which builds the folder it sits in, only `silopkg.py` is hashed. The source snapshot covers the rest.

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

A program has to ship the shared libraries it links. silo's toolchain file sets `SILO_RUNTIME_LIBRARIES` to those files, for every dependency, and one line installs them beside the program on any system (see `examples/decor/CMakeLists.txt`):

```cmake
install(TARGETS app RUNTIME DESTINATION bin)
install(FILES ${SILO_RUNTIME_LIBRARIES} DESTINATION bin)
```

The stored package then runs by itself. Windows looks beside the program anyway. On Linux silo builds everything with a run path of `$ORIGIN` and `$ORIGIN/../lib`, which means "the folder this file is in", and the list includes the versioned names (`libz.so.1`) a program asks for.

A recipe without a `package()` hook keeps everything its build installed into `bin` when it holds a program. Static dependencies add nothing to the list, since they are already inside the binary.

Some libraries must match the machine they run on, not the one they were built on: a graphics loader matches the driver, libwayland the compositor. Their recipes return `Package(..., system_runtime=True)`. They are built and linked as usual, but left out of the list, so the program uses the machine's copy when it starts. `wayland` in silo-recipes and `vulkan-loader` in silo-recipes do this.

## Tools

A recipe declares the programs its build runs in `deps()`:

```python
self.tool("cmake@4.3")  # a recipe from a registry, built first
self.tool("../greetgen")  # or a recipe given by path
```

Every tool is a recipe. cmake, ninja, meson, pkgconf and conan are too: their recipes in silo-recipes take the finished program from PyPI with `PyPIInstall`, which is why silo needs `uv` on the machine and nothing else.

A tool's version is the newest one that begins the way it is written, because a tool is run and not linked:

| Written | Means |
|---|---|
| `cmake@4.3.4` | exactly 4.3.4 |
| `cmake@4.3` | the highest 4.3.x the registry has |
| `cmake@4` | the highest 4.x |
| `cmake` | the highest there is |

The version that was picked is part of the build id. A library named with `self.dep` is always the exact version written.

A tool recipe's executables are put on the build's `PATH` and become CMake targets named `<package>::<program>`, so `find_package(greetgen)` gives `greetgen::greetgen` (see `examples/zapp/CMakeLists.txt`). Folders holding the shared libraries of dependencies and tools are on the search path too, so tests and tools start. `silo run -- <command>` runs anything in that same environment.

### A tool that runs another tool

A build that runs CMake also runs Ninja, because CMake starts it. Whatever a tool runs comes with the tool, so the recipe names only the tool it calls itself.

A tool's recipe says so with `transitive=True`:

```python
class Bison(SiloPackage):
    def deps(self):
        self.tool("m4@1.4.19", transitive=True)  # bison starts m4 every time it runs
        self.tool("gperf@3.1")                   # only needed to build bison
```

A recipe with `self.tool("bison@3.8.2")` then has `bison` and `m4` on its `PATH`. The cmake and meson recipes pass on ninja the same way, so `self.tool("cmake@4.3")` is enough to build with CMake. This follows chains of any length, and `silo graph` marks such a tool with "and passes it on". Only the tool the recipe named becomes a CMake target.

Each tool recipe is a graph of its own, separate from what its user links:

| | What a package links | A tool |
|---|---|---|
| Copies of one package | One in the whole graph | One per tool. Two recipes may use different versions or options of a tool |
| Build type | The root's choice, `--debug-all` | Always release |
| Options | Requests, the root's overrides, the command line | The `options=` of the `self.tool()` call, else defaults |
| Seen by packages that depend on the user | Yes | No |

Nothing is shared between these graphs by rule. The store does it: two tools that need the same build of a package get the same store entry. `silo graph` prints each tool's graph indented under the package that runs it.

## Writing recipes

A recipe is a `silopkg.py` holding a class that extends `SiloPackage`. `tinyxml2` in silo-recipes is the smallest CMake one and `msdfgen` in silo-recipes uses most features.

| Hook | Does | Can read |
|---|---|---|
| `source(src)` | `src.fetch(url, sha256=)`, `src.git(url, commit=)`, `src.local(".")` or `src.empty()` | `self.options` |
| `patch(src)` | `src.apply("fix.patch")`, `src.replace(file, old, new)` | the build context |
| `deps()` | `self.dep("zlib@1.3.1")`, `self.tool("cmake@4.3")` | `self.options`, `self.profile` |
| `validate()` | Raises `InvalidConfiguration` for a graph it cannot work with | also `self.dependencies` |
| `generate()` | Writes build system files, usually `CMakeDeps` and `CMakeGenerator` | everything |
| `build()` | Usually `CMakeBuild`: configure, build, install | everything |
| `package()` | Returns a `Package` of `Component`s: headers, libraries, programs and what they require | everything |

- `self.profile` is known in every hook, so `deps()` can pick dependencies by target system (`self.profile.settings.os`).
- A recipe that can build a shared library sets `supports_shared = True` and acts on `self.options.shared`. Its options class can change the default.
- Upstream build files often expect other target names. `CMakeDeps(self).alias("ZLIB::ZLIB", "zlib::zlib")` adds the name for this build only and makes `find_package(ZLIB)` work. An alias for a package or component that is not there fails in `generate()`.
- The toolchain file stops CMake from finding packages installed on the machine. A recipe that needs one calls `CMakeGenerator(self).allow_system_packages()`.
- silo builds everything against the release DLL runtime on Windows (`/MD`), in debug builds too. An upstream build file that picks another one has to be told not to (see `libwebm` in silo-recipes and `msdfgen` in silo-recipes).

### Meson and pkg-config

`wayland` in silo-recipes shows all of it. A Meson recipe mirrors a CMake one:

```python
def deps(self):
    self.dep("libffi@3.4.6")
    self.tool("meson@1")
    self.tool("pkgconf@3")

def generate(self):
    PkgConfigDeps(self).generate()
    meson = MesonGenerator(self)
    meson.set_option("tests", False)                  # the project's own options
    meson.set_builtin("default_library", "shared")    # Meson's options
    meson.generate()

def build(self):
    meson = MesonBuild(self)
    meson.configure()
    meson.build()
    meson.install()
```

- `MesonGenerator` writes a native file with the compilers, the build type and the prefix. Downloading missing dependencies (wraps) is turned off.
- `PkgConfigDeps` writes one `.pc` file per component of every dependency and tool, and the build sees only those, never the machine's own.
- A component's `.pc` file is named after the component. `Component(pkg_config="freetype2", pkg_config_version="26.2.20", pkg_config_variables={...})` changes the name, the version and adds variables, for what upstream's users expect.
- A build that would compile its install folder into a library is rejected. The recipe points such folders at the machine instead (`/etc`, `/usr/share`), as `glib` in silo-recipes and `fontconfig` in silo-recipes do.

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

It only describes MSVC to Conan so far, and it suits packages without dependencies of their own. `settings=` replaces entries of the profile for a package that refuses the real ones (see `libvpx` in silo-recipes).

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
         its tools, built the same way  each a graph of its own, cmake and ninja included
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
| `client/src/silo/registry.py` | `silo.config.toml`: registries, packages taken from a folder or a commit, and the lookup |
| `client/src/silo/errors.py` | Errors the CLI prints without a traceback |
| `client/src/silo/report.py` | What `silo build --report` writes |
| `client/src/silo/platform/` | Everything OS specific, behind `PlatformBackend` |
| `client/src/silo/tools/cmake/` | For recipes: `CMakeGenerator` (toolchain file), `CMakeDeps` (dependency configs), `CMakePresets`, `CMakeBuild` |
| `client/src/silo/tools/pypi/` | For recipes: `PyPIInstall`, which takes a finished program from PyPI. See `cmake` in silo-recipes |
| `client/src/silo/tools/meson/` | For recipes: `MesonGenerator` (native file) and `MesonBuild` |
| `client/src/silo/tools/pkgconfig/` | For recipes: `PkgConfigDeps`, a `.pc` file per dependency component |
| `client/src/silo/tools/conan/` | For recipes: `ConanInstall`, which gets a finished package from Conan when silo cannot drive its build. See `libvpx` in silo-recipes |
| `client/src/silo/cache.py` | The caches under `<SILO_HOME>/cache` and how to clear them |
| `examples/sdf/` | A local project that links msdfgen and its whole dependency chain |
| `examples/vpx/` | A local project that links libvpx, which silo gets from Conan |
| `examples/decor/` | Linux only: links libdecor and opens a Wayland connection |
| `examples/zapp/` | A local project: `src.local(".")`, a path dependency with an alias, a tool, presets and a `validate` hook |
| `examples/greetgen/` | A code generator that zapp uses as a tool |
| `client/tests/` | Unit tests |

To add a platform, implement `PlatformBackend` (`platform/base.py`) in its own folder and return it from `backend_for` in `platform/__init__.py`. Nothing outside `platform/` should check the operating system.

## Not built yet

- Version ranges, a lockfile and prebuilt packages. A dependency is an exact version, and everything is built from source.
- `src.git(url, tag=...)` and version pins, which wait for the lockfile. `src.git(url, commit=..., submodules=...)` works.
- Submodules in a local source.
- macOS builds. Linux builds with gcc or clang, and has been run on Ubuntu with gcc only. Most recipes written on Windows have not been built there.
- On Linux the system's `/usr/bin` is on the build's `PATH`, since the compiler needs it. A tool installed there (make, python3) can be used without being declared.
- libdecor finds its plugins only through `LIBDECOR_PLUGIN_DIR`, which the program sets to the package's `lib/libdecor/plugins-1`.
- A Python of the recipe's choosing. Meson and build scripts run on silo's own interpreter.
- `ConanInstall` for compilers other than MSVC, and for packages with dependencies of their own.
- A check that every library in a link uses the same C runtime. A mismatch shows up only when a consumer links.
