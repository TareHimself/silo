import typer
from pathlib import Path
from silo.utils import load_package_cls, get_package_file_path
from silo.silo_package import SiloPackage
from silo.enums import BuildMode
from silo.lock import ensure_lock
app = typer.Typer()


def get_hash(package: SiloPackage):
    pass

def get_depencencies(package: SiloPackage):
    package.deps()
@app.callback()
def main():
    """
    SILO package manager
    """
    pass

@app.command()
def sync(options: list[str] = typer.Option([],"-o"),mode: BuildMode = typer.Option(BuildMode.Release,"-m")):
    cwd = Path.cwd()
    package_file_path = get_package_file_path(cwd)
    package_cls = load_package_cls(cwd)

    package = package_cls(package_file_path,package_cls.build_options(options))

    print("Dependencies",[(x.name,x.version) for x in package._dependencies])
    print("Tools",[(x.name,x.version) for x in package._tools])
    
    
## 

# def run():
#     app()
