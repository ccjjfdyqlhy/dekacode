import ast
import os
import sys


class SymbolSignature:
    def __init__(self, name: str, kind: str, signature: str, file_path: str, line: int):
        self.name = name
        self.kind = kind
        self.signature = signature
        self.file_path = file_path
        self.line = line

    def __str__(self) -> str:
        return self.signature

    def to_prompt_block(self) -> str:
        return f"  {self.signature}  # {self.file_path}:{self.line}"


class ImportResolver:
    def __init__(self, project_root: str | None = None):
        self.project_root = os.path.abspath(project_root or os.getcwd())
        self._signature_cache: dict[str, list[SymbolSignature]] = {}

    MAX_SIGS_PER_FILE = 15

    def resolve(self, file_path: str) -> list[SymbolSignature]:
        abspath = os.path.abspath(file_path)
        if abspath in self._signature_cache:
            return self._signature_cache[abspath]

        try:
            with open(abspath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=abspath)
        except (SyntaxError, FileNotFoundError, UnicodeDecodeError):
            self._signature_cache[abspath] = []
            return []

        imports: list[tuple[str, str | None]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append((alias.name, alias.asname))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.append((module, None))

        seen = set()
        result: list[SymbolSignature] = []
        for module_name, alias in imports:
            resolved_path = self._resolve_module_path(module_name, abspath)
            if resolved_path and resolved_path not in seen:
                seen.add(resolved_path)
                if not self._is_project_file(resolved_path):
                    continue
                sigs = self._extract_signatures(resolved_path)
                result.extend(sigs[:self.MAX_SIGS_PER_FILE])

        self._signature_cache[abspath] = result
        return result

    def _is_project_file(self, file_path: str) -> bool:
        try:
            return os.path.commonpath([os.path.abspath(file_path), self.project_root]) == self.project_root
        except ValueError:
            return False

    def _resolve_module_path(self, module_name: str, from_file: str) -> str | None:
        parts = module_name.split(".")
        from_dir = os.path.dirname(os.path.abspath(from_file))

        candidates: list[str] = []

        relative_package = ".".join(parts[:-1])
        relative_name = parts[-1] if parts else ""
        if relative_package:
            pkg_dir = os.path.join(from_dir, *relative_package.split("."))
            candidates.append(os.path.join(pkg_dir, f"{relative_name}.py"))
            candidates.append(os.path.join(pkg_dir, "__init__.py"))

        candidates.append(os.path.join(from_dir, f"{module_name.replace('.', '/')}.py"))

        root_relative = os.path.join(self.project_root, module_name.replace(".", "/"))
        candidates.append(f"{root_relative}.py")
        candidates.append(os.path.join(root_relative, "__init__.py"))

        for entry in sys.path:
            ep = os.path.join(entry, module_name.replace(".", "/"))
            candidates.append(f"{ep}.py")
            candidates.append(os.path.join(ep, "__init__.py"))

        for candidate in candidates:
            normalized = os.path.normpath(candidate)
            if os.path.isfile(normalized) and normalized != os.path.abspath(from_file):
                return normalized

        return None

    def _extract_signatures(self, file_path: str) -> list[SymbolSignature]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=file_path)
        except (SyntaxError, FileNotFoundError, UnicodeDecodeError):
            return []

        sigs: list[SymbolSignature] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(self._format_attr(base))
                bases_str = f"({', '.join(bases)})" if bases else ""
                sigs.append(SymbolSignature(
                    name=node.name,
                    kind="class",
                    signature=f"class {node.name}{bases_str}:",
                    file_path=file_path,
                    line=node.lineno,
                ))
                for item in ast.iter_child_nodes(node):
                    if isinstance(item, ast.FunctionDef):
                        sigs.append(self._make_method_sig(item, node.name, file_path))
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                sigs.append(SymbolSignature(
                                    name=target.id,
                                    kind="attr",
                                    signature=f"    {target.id}: {self._format_expr(item.value) if isinstance(item.value, ast.Constant) else '(defined)'}",
                                    file_path=file_path,
                                    line=item.lineno,
                                ))

            elif isinstance(node, ast.FunctionDef):
                sigs.append(self._make_func_sig(node, file_path))

        return sigs

    def _make_func_sig(self, node: ast.FunctionDef, file_path: str) -> SymbolSignature:
        args = self._format_args(node.args)
        returns = ""
        if node.returns:
            returns = f" -> {self._format_expr(node.returns)}"
        sig = f"def {node.name}({args}){returns}:"
        return SymbolSignature(name=node.name, kind="function", signature=sig, file_path=file_path, line=node.lineno)

    def _make_method_sig(self, node: ast.FunctionDef, class_name: str, file_path: str) -> SymbolSignature:
        args = self._format_args(node.args)
        returns = ""
        if node.returns:
            returns = f" -> {self._format_expr(node.returns)}"
        sig = f"    def {node.name}({args}){returns}:"
        return SymbolSignature(name=f"{class_name}.{node.name}", kind="method", signature=sig, file_path=file_path, line=node.lineno)

    def _format_args(self, args: ast.arguments) -> str:
        parts: list[str] = []
        for i, arg in enumerate(args.args):
            if i == 0 and arg.arg == "self":
                parts.append("self")
                continue
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {self._format_expr(arg.annotation)}"
            parts.append(arg_str)
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
            if args.vararg.annotation:
                parts[-1] += f": {self._format_expr(args.vararg.annotation)}"
        if args.kwonlyargs:
            if not args.vararg:
                parts.append("*")
            for ka in args.kwonlyargs:
                ka_str = ka.arg
                if ka.annotation:
                    ka_str += f": {self._format_expr(ka.annotation)}"
                parts.append(ka_str)
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
            if args.kwarg.annotation:
                parts[-1] += f": {self._format_expr(args.kwarg.annotation)}"
        return ", ".join(parts)

    def _format_expr(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._format_expr(node.value)}.{node.attr}"
        elif isinstance(node, ast.Subscript):
            return f"{self._format_expr(node.value)}[{self._format_expr(node.slice)}]"
        elif isinstance(node, ast.Constant):
            return repr(node.value)
        elif isinstance(node, ast.List):
            return f"list[{', '.join(self._format_expr(e) for e in node.elts)}]" if node.elts else "list"
        elif isinstance(node, ast.Tuple):
            return f"tuple[{', '.join(self._format_expr(e) for e in node.elts)}]" if node.elts else "tuple"
        elif isinstance(node, ast.BinOp):
            return f"{self._format_expr(node.left)} {self._format_op(node.op)} {self._format_expr(node.right)}"
        elif isinstance(node, ast.Call):
            return f"{self._format_expr(node.func)}(...)"
        else:
            return "..."

    def _format_attr(self, node: ast.Attribute) -> str:
        return f"{self._format_expr(node.value)}.{node.attr}"

    def _format_op(self, op: ast.operator) -> str:
        mapping = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
        return mapping.get(type(op), "?")
