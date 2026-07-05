"""
快速定位模块
- find_definition: 查找定义位置(仅行号)
- find_references: 查找引用位置
- locate_symbol: 定位符号
"""

import ast
import os
import re
from typing import List, Dict, Set, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SymbolLocation:
    """符号位置"""
    file_path: str
    line: int
    column: int
    symbol_type: str  # 'function', 'class', 'variable', 'parameter'


@dataclass
class DefinitionInfo:
    """定义信息"""
    name: str
    file_path: str
    line: int
    column: int
    symbol_type: str
    docstring: Optional[str] = None
    parameters: Optional[List[str]] = None
    parent_class: Optional[str] = None


@dataclass
class ReferenceInfo:
    """引用信息"""
    file_path: str
    line: int
    column: int
    context: str
    ref_type: str  # 'call', 'import', 'assignment', 'usage'


class SymbolIndex:
    """符号索引"""

    def __init__(self):
        self.definitions: Dict[str, List[DefinitionInfo]] = {}
        self.references: Dict[str, List[ReferenceInfo]] = {}
        self.imports: Dict[str, List[str]] = {}  # file -> imported symbols
        self.class_hierarchy: Dict[str, List[str]] = {}  # class -> methods

    def add_definition(self, info: DefinitionInfo):
        """添加定义"""
        key = info.name
        if key not in self.definitions:
            self.definitions[key] = []
        self.definitions[key].append(info)

    def add_reference(self, name: str, info: ReferenceInfo):
        """添加引用"""
        if name not in self.references:
            self.references[name] = []
        self.references[name].append(info)

    def get_definitions(self, name: str) -> List[DefinitionInfo]:
        """获取定义"""
        return self.definitions.get(name, [])

    def get_references(self, name: str) -> List[ReferenceInfo]:
        """获取引用"""
        return self.references.get(name, [])


class DefinitionVisitor(ast.NodeVisitor):
    """AST访问器,收集定义"""

    def __init__(self, file_path: str, index: SymbolIndex):
        self.file_path = file_path
        self.index = index
        self.current_class = None
        self.imports = []

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append(alias.name)
            if alias.asname:
                self.imports.append(alias.asname)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module or ''
        for alias in node.names:
            full_name = f"{module}.{alias.name}" if module else alias.name
            self.imports.append(alias.name)
            self.imports.append(full_name)
            if alias.asname:
                self.imports.append(alias.asname)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        info = DefinitionInfo(
            name=node.name,
            file_path=self.file_path,
            line=node.lineno,
            column=node.col_offset,
            symbol_type='class',
            docstring=ast.get_docstring(node),
            parent_class=self.current_class
        )
        self.index.add_definition(info)

        # 记录类层次结构
        self.index.class_hierarchy[node.name] = []

        old_class = self.current_class
        self.current_class = node.name

        self.generic_visit(node)

        self.current_class = old_class

    def visit_FunctionDef(self, node):
        parameters = [arg.arg for arg in node.args.args]

        info = DefinitionInfo(
            name=node.name,
            file_path=self.file_path,
            line=node.lineno,
            column=node.col_offset,
            symbol_type='function',
            docstring=ast.get_docstring(node),
            parameters=parameters,
            parent_class=self.current_class
        )
        self.index.add_definition(info)

        # 如果是类方法,添加到类层次结构
        if self.current_class:
            self.index.class_hierarchy.setdefault(self.current_class, []).append(node.name)

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                info = DefinitionInfo(
                    name=target.id,
                    file_path=self.file_path,
                    line=node.lineno,
                    column=node.col_offset,
                    symbol_type='variable',
                    parent_class=self.current_class
                )
                self.index.add_definition(info)
        self.generic_visit(node)

    def visit_Name(self, node):
        # 记录引用
        if isinstance(node.ctx, ast.Load):
            info = ReferenceInfo(
                file_path=self.file_path,
                line=node.lineno,
                column=node.col_offset,
                context='',
                ref_type='usage'
            )
            self.index.add_reference(node.id, info)
        self.generic_visit(node)


def build_symbol_index(file_path: str) -> SymbolIndex:
    """构建单个文件的符号索引"""
    index = SymbolIndex()

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            source = f.read()

        tree = ast.parse(source)
        visitor = DefinitionVisitor(file_path, index)
        visitor.visit(tree)

        # 记录imports
        index.imports[file_path] = visitor.imports

    except:
        pass

    return index


def find_definition(symbol: str, project_root: str = ".") -> List[SymbolLocation]:
    """
    查找符号定义位置(仅行号)

    Args:
        symbol: 符号名
        project_root: 项目根目录

    Returns:
        定义位置列表
    """
    locations = []

    for root, _, files in os.walk(project_root):
        # 跳过常见忽略目录
        if any(skip in root for skip in ['.git', '__pycache__', 'node_modules', '.venv']):
            continue

        for filename in files:
            if filename.endswith('.py'):
                file_path = os.path.join(root, filename)
                index = build_symbol_index(file_path)

                definitions = index.get_definitions(symbol)
                for def_info in definitions:
                    locations.append(SymbolLocation(
                        file_path=def_info.file_path,
                        line=def_info.line,
                        column=def_info.column,
                        symbol_type=def_info.symbol_type
                    ))

    return locations


def find_references(
    symbol: str,
    project_root: str = ".",
    include_definition: bool = False
) -> List[ReferenceInfo]:
    """
    查找符号引用位置

    Args:
        symbol: 符号名
        project_root: 项目根目录
        include_definition: 是否包含定义位置

    Returns:
        引用位置列表
    """
    all_references = []

    for root, _, files in os.walk(project_root):
        if any(skip in root for skip in ['.git', '__pycache__', 'node_modules', '.venv']):
            continue

        for filename in files:
            if filename.endswith('.py'):
                file_path = os.path.join(root, filename)

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()

                    index = build_symbol_index(file_path)

                    # 获取引用
                    refs = index.get_references(symbol)
                    for ref in refs:
                        # 添加上下文
                        if ref.line - 1 < len(lines):
                            context = lines[ref.line - 1].strip()
                            ref.context = context

                            # 判断引用类型
                            if re.search(rf'\b{re.escape(symbol)}\s*\(', context):
                                ref.ref_type = 'call'
                            elif re.search(rf'\bimport\b.*{re.escape(symbol)}', context):
                                ref.ref_type = 'import'
                            elif re.search(rf'\b{re.escape(symbol)}\s*=', context):
                                ref.ref_type = 'assignment'

                        all_references.append(ref)

                except:
                    pass

    return all_references


def locate_symbol(
    symbol: str,
    project_root: str = ".",
    find_type: str = "both"
) -> Dict[str, Any]:
    """
    定位符号(定义和引用)

    Args:
        symbol: 符号名
        project_root: 项目根目录
        find_type: 查找类型 ('definition', 'reference', 'both')

    Returns:
        定位结果
    """
    result = {
        'symbol': symbol,
        'definitions': [],
        'references': [],
        'total_occurrences': 0
    }

    if find_type in ['definition', 'both']:
        definitions = find_definition(symbol, project_root)
        result['definitions'] = [
            {
                'file': loc.file_path,
                'line': loc.line,
                'column': loc.column,
                'type': loc.symbol_type
            }
            for loc in definitions
        ]

    if find_type in ['reference', 'both']:
        references = find_references(symbol, project_root)
        result['references'] = [
            {
                'file': ref.file_path,
                'line': ref.line,
                'column': ref.column,
                'context': ref.context,
                'type': ref.ref_type
            }
            for ref in references
        ]

    result['total_occurrences'] = len(result['definitions']) + len(result['references'])

    return result


def find_class_methods(class_name: str, project_root: str = ".") -> List[Dict[str, Any]]:
    """
    查找类的所有方法

    Args:
        class_name: 类名
        project_root: 项目根目录

    Returns:
        方法列表
    """
    methods = []

    for root, _, files in os.walk(project_root):
        if any(skip in root for skip in ['.git', '__pycache__', 'node_modules', '.venv']):
            continue

        for filename in files:
            if filename.endswith('.py'):
                file_path = os.path.join(root, filename)
                index = build_symbol_index(file_path)

                if class_name in index.class_hierarchy:
                    for method_name in index.class_hierarchy[class_name]:
                        method_defs = index.get_definitions(method_name)
                        for method_def in method_defs:
                            if method_def.parent_class == class_name:
                                methods.append({
                                    'name': method_name,
                                    'file': method_def.file_path,
                                    'line': method_def.line,
                                    'docstring': method_def.docstring,
                                    'parameters': method_def.parameters
                                })

    return methods


def find_all_symbols(project_root: str = ".") -> Dict[str, List[Dict[str, Any]]]:
    """
    查找项目中所有符号

    Args:
        project_root: 项目根目录

    Returns:
        符号字典
    """
    all_symbols = {
        'functions': [],
        'classes': [],
        'variables': []
    }

    for root, _, files in os.walk(project_root):
        if any(skip in root for skip in ['.git', '__pycache__', 'node_modules', '.venv']):
            continue

        for filename in files:
            if filename.endswith('.py'):
                file_path = os.path.join(root, filename)
                index = build_symbol_index(file_path)

                for name, definitions in index.definitions.items():
                    for def_info in definitions:
                        symbol_info = {
                            'name': name,
                            'file': def_info.file_path,
                            'line': def_info.line,
                            'type': def_info.symbol_type
                        }

                        if def_info.symbol_type == 'function':
                            all_symbols['functions'].append(symbol_info)
                        elif def_info.symbol_type == 'class':
                            all_symbols['classes'].append(symbol_info)
                        elif def_info.symbol_type == 'variable':
                            all_symbols['variables'].append(symbol_info)

    return all_symbols