import json
from dataclasses import dataclass, field
from pathlib import Path

from silo.cache import remove_tree
from silo.dependency_graph import Node
from silo.errors import CommandFailed

REPORT_FILE = "report.json"
LOGS_DIR = "logs"


@dataclass
class BuildReport:
    """What `silo build --report <folder>` leaves behind: report.json and one log per package."""

    folder: Path
    root: str | None = None
    packages: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.folder = self.folder.resolve()
        remove_tree(self.folder / LOGS_DIR)
        (self.folder / LOGS_DIR).mkdir(parents=True)
        (self.folder / REPORT_FILE).unlink(missing_ok=True)

    def log_for(self, label: str) -> Path:
        return self.folder / LOGS_DIR / f"{label}.log"

    def record(
        self,
        node: Node,
        build_id: str,
        status: str,
        store_path: Path | None = None,
        error: Exception | None = None,
    ) -> None:
        label = f"{node.name}-{node.version}-{build_id}"
        # A package two tools share is reached twice and built once
        if label in self.packages:
            return
        entry: dict = {
            "name": node.name,
            "version": node.version,
            "build_id": build_id,
            "build_type": node.build_type.value,
            "status": status,
        }
        if store_path is not None:
            entry["store_path"] = store_path.as_posix()
        if self.log_for(label).is_file():
            entry["log"] = f"{LOGS_DIR}/{label}.log"
        if error is not None:
            entry["error"] = str(error)
        if isinstance(error, CommandFailed):
            entry["failed_command"] = error.command
            entry["exit_code"] = error.exit_code
        self.packages[label] = entry

    def write(self, store_path: Path | None = None, error: Exception | None = None) -> Path:
        report = {
            "ok": error is None,
            "root": self.root,
            "store_path": store_path.as_posix() if store_path else None,
            "error": str(error) if error else None,
            "packages": list(self.packages.values()),
        }
        report_file = self.folder / REPORT_FILE
        report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        return report_file
