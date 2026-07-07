from config import Settings


class MemoryStore:
    def __init__(self, settings: Settings, debug_print=None):
        self._enabled = settings.mnemosyne_enabled
        self._bank = settings.mnemosyne_bank or "dekacode"
        self._embedding_model = settings.mnemosyne_embedding_model
        self._data_dir = settings.mnemosyne_data_dir
        self._mnemosyne = None
        self._can_remember = None
        self._can_recall = None
        self._init_error = ""
        if self._enabled:
            self._init(debug_print)

    def _init(self, debug_print=None):
        try:
            import os
            if self._data_dir:
                os.environ["MNEMOSYNE_DATA_DIR"] = self._data_dir
            if self._embedding_model:
                os.environ["MNEMOSYNE_EMBEDDING_MODEL"] = self._embedding_model

            from mnemosyne import Mnemosyne, remember, recall
            self._mnemosyne = Mnemosyne(bank=self._bank)
            self._can_remember = remember
            self._can_recall = recall
        except ImportError:
            self._enabled = False
            self._init_error = "mnemosyne-memory package not installed (pip install mnemosyne-memory)"
            if debug_print:
                debug_print(f"  [yellow]⚠ {self._init_error}[/]")
        except Exception as e:
            self._enabled = False
            self._init_error = f"mnemosyne init failed: {e}"
            if debug_print:
                debug_print(f"  [yellow]⚠ {self._init_error}[/]")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def bank(self) -> str:
        return self._bank

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    def remember(self, text: str, importance: float = 0.5, **kwargs):
        if not self._enabled or self._can_remember is None:
            return False
        try:
            self._can_remember(text, importance=importance, **kwargs)
            return True
        except Exception:
            return False

    def recall(self, query: str, top_k: int = 5) -> list[str]:
        if not self._enabled or self._can_recall is None:
            return []
        try:
            results = self._can_recall(query, top_k=top_k)
            if isinstance(results, list):
                texts = []
                for r in results:
                    if isinstance(r, dict):
                        texts.append(r.get("text", str(r)))
                    else:
                        texts.append(str(r))
                return texts
        except Exception:
            pass
        return []

    def recall_and_format(self, query: str, max_items: int = 5) -> tuple[list[str], str]:
        if not self._enabled or not query:
            return [], ""
        memories = self.recall(query, top_k=max_items)
        if not memories:
            return [], ""
        lines = "\n".join(f"  - {m}" for m in memories)
        return memories, f"# Memory\n{lines}"
