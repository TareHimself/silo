import json
import os
import subprocess
from pathlib import Path

from silo.enums import Architecture

VCVARS_ARCH = {
    Architecture.X86_64: "x64",
    Architecture.X86: "x86",
    Architecture.ARM64: "arm64",
}

# The only variables vcvarsall.bat is given, so the captured environment owes nothing to the shell
BOOTSTRAP_VARS = (
    "SystemRoot",
    "SystemDrive",
    "windir",
    "ComSpec",
    "PATHEXT",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramData",
    "CommonProgramFiles",
    "CommonProgramFiles(x86)",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "TEMP",
    "TMP",
    "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS",
)


def bootstrap_env() -> dict[str, str]:
    env = {name: os.environ[name] for name in BOOTSTRAP_VARS if name in os.environ}
    system_root = env["SystemRoot"]
    system_paths = [
        rf"{system_root}\System32",
        system_root,
        rf"{system_root}\System32\Wbem",
        rf"{system_root}\System32\WindowsPowerShell\v1.0",
    ]
    env["PATH"] = os.pathsep.join(system_paths)
    env["VSCMD_SKIP_SENDTELEMETRY"] = "1"
    return env


def find_visual_studio() -> Path:
    installer_dir = Path(os.environ["PROGRAMFILES(X86)"]) / "Microsoft Visual Studio" / "Installer"
    vswhere = installer_dir / "vswhere.exe"
    if not vswhere.exists():
        raise RuntimeError(f"vswhere not found at {vswhere}. Is Visual Studio installed?")

    query = [
        str(vswhere),
        "-latest",
        "-products",
        "*",
        "-requires",
        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
        "-format",
        "json",
        "-utf8",
    ]
    output = subprocess.run(query, capture_output=True, check=True, encoding="utf-8").stdout
    installations = json.loads(output)
    if not installations:
        raise RuntimeError("No Visual Studio installation with the C++ toolset was found")
    return Path(installations[0]["installationPath"])


def _parse_set_output(output: str) -> dict[str, str]:
    """Parse the NAME=value lines printed by cmd's `set`."""
    env = {}
    for line in output.splitlines():
        name, separator, value = line.partition("=")
        if separator and name:
            env[name] = value
    # cmd reports the search path as "Path"; the rest of silo expects "PATH"
    if "Path" in env:
        env["PATH"] = env.pop("Path")
    return env


def capture_vcvars(install_path: Path, arch: Architecture) -> dict[str, str]:
    """Run vcvarsall.bat in a bare environment and return the environment it sets up."""
    vcvarsall = install_path / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
    if not vcvarsall.exists():
        raise RuntimeError(f"vcvarsall.bat not found at {vcvarsall}")

    env = bootstrap_env()
    # cmd /s /c strips the outer quotes, which keeps the quoted script path intact
    command = f'"{env["ComSpec"]}" /d /s /c ""{vcvarsall}" {VCVARS_ARCH[arch]} >nul && set"'
    result = subprocess.run(
        command,
        env=env,
        capture_output=True,
        encoding="oem",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"vcvarsall.bat failed:\n{result.stdout}\n{result.stderr}")

    captured = _parse_set_output(result.stdout)
    if "VCToolsVersion" not in captured:
        raise RuntimeError("vcvarsall.bat ran but did not set up a C++ toolset")
    return captured
