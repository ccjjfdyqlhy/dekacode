import os
import time


class FileWatcher:
    def __init__(self, project_root: str, interval: float = 2.0):
        self.project_root = os.path.abspath(project_root)
        self.interval = interval
        self._mtimes: dict[str, float] = {}
        self._scan()

    def _scan(self) -> None:
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".dekacode")]
            for f in files:
                if f.endswith(".py"):
                    fpath = os.path.join(root, f)
                    try:
                        self._mtimes[fpath] = os.path.getmtime(fpath)
                    except OSError:
                        pass

    def get_changed_files(self) -> list[str]:
        changed = []
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".dekacode")]
            for f in files:
                if not f.endswith(".py"):
                    continue
                fpath = os.path.join(root, f)
                try:
                    mtime = os.path.getmtime(fpath)
                    old = self._mtimes.get(fpath)
                    if old is None or abs(mtime - old) > 0.1:
                        changed.append(fpath)
                        self._mtimes[fpath] = mtime
                except OSError:
                    pass
        return changed
