# silo

A C++ package manager: builds dependencies from source in an isolated environment and keeps them in a local store. Design notes live on relay, in the `silo` project.

## Use

```
uv run --package silo silo profile detect             # writes <SILO_HOME>/profiles/default.toml
uv run --package silo silo build recipes/zlib         # builds into <SILO_HOME>/store
uv run --package silo silo build examples/zapp        # a local project that depends on zlib
uv run --package silo silo build examples/zapp --debug  # root in debug, dependencies stay release
uv run --package silo silo sync examples/zapp         # resolve and print the graph, build nothing
```

`SILO_HOME` defaults to `~/.silo`. Pass options with `-o key=value` for the root package or `-o zlib:key=value` for a dependency.

## Develop

```
uv sync --all-packages
uv run --package silo pytest client/tests
uvx ruff format . && uvx ruff check .
```

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
         tool_resolver.resolve_tool    cmake and ninja from PyPI, through uv
         platform backend .build_env   a clean environment, nothing inherited from the shell
         builder.prepare_source        fetched: download, check sha256, unpack
                                       local: check out a git snapshot of the folder as it is now
                                       then the recipe's patch()
         recipe.build()                usually tools/cmake CMakeBuild, which also writes a
                                       <name>Config.cmake for each dependency (cmake_deps)
         package.write_package         copy what package() lists, write silo/package.json
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
| `client/src/silo/tool_resolver.py` | Build tools installed through uv |
| `client/src/silo/errors.py` | Errors the CLI prints without a traceback |
| `client/src/silo/platform/` | Everything OS specific, behind `PlatformBackend` |
| `client/src/silo/tools/cmake/` | `CMakeBuild` for recipes, and the dependency config generator |
| `recipes/` | Recipes (`silopkg.py`) for third-party libraries |
| `examples/zapp/` | A local project: `src.local(".")`, a path dependency and a `validate` hook |
| `client/tests/` | Unit tests |

To add a platform, implement `PlatformBackend` (`platform/base.py`) in its own folder and return it from `backend_for` in `platform/__init__.py`. Nothing outside `platform/` should check the operating system.

## Not built yet

- Dependencies by name (`zlib@1.3`). They need a registry, so only paths work: `self.dep("../zlib")`.
- `src.git`, version pins, and `--source` on the command line.
- Submodules in a local source.
- Shared libraries and executables in the generated CMake configs.
- The lockfile, publishing prebuilts, and Linux and macOS builds.
