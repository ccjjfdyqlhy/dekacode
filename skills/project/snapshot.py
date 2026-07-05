"""
项目快照模块
- key_files: 关键文件识别
- module_map: 依赖关系图
"""

import os
import ast
import re
from typing import List, Dict, Set, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict, Counter
import json


@dataclass
class KeyFile:
    """关键文件"""
    file_path: str
    importance_score: float
    reasons: List[str]
    metrics: Dict[str, Any]


@dataclass
class ModuleInfo:
    """模块信息"""
    name: str
    file_path: str
    imports: Set[str]
    imported_by: Set[str]
    exports: Set[str]


@dataclass
class DependencyEdge:
    """依赖边"""
    from_module: str
    to_module: str
    edge_type: str  # 'import', 'inheritance', 'composition'


def key_files(
    project_root: str = ".",
    max_files: int = 20
) -> List[KeyFile]:
    """
    关键文件识别

    Args:
        project_root: 项目根目录
        max_files: 返回的最大文件数

    Returns:
        关键文件列表(按重要性排序)
    """
    file_scores = {}

    # 扫描所有Python文件
    for root, dirs, files in os.walk(project_root):
        # 跳过隐藏目录
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']

        for filename in files:
            if filename.endswith('.py'):
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, project_root)

                score, reasons, metrics = _calculate_file_importance(
                    file_path, rel_path, project_root
                )

                file_scores[file_path] = {
                    'score': score,
                    'reasons': reasons,
                    'metrics': metrics,
                    'rel_path': rel_path
                }

    # 排序
    sorted_files = sorted(
        file_scores.items(),
        key=lambda x: x[1]['score'],
        reverse=True
    )

    # 构建结果
    results = []
    for file_path, info in sorted_files[:max_files]:
        results.append(KeyFile(
            file_path=info['rel_path'],
            importance_score=info['score'],
            reasons=info['reasons'],
            metrics=info['metrics']
        ))

    return results


def _calculate_file_importance(
    file_path: str,
    rel_path: str,
    project_root: str
) -> Tuple[float, List[str], Dict[str, Any]]:
    """计算文件重要性"""
    score = 0.0
    reasons = []
    metrics = {}

    # 1. 文件名模式
    name = os.path.basename(file_path).lower()

    # 主入口文件
    if name in ['main.py', '__init__.py', 'app.py', 'run.py']:
        score += 10
        reasons.append(f"入口文件: {name}")

    # 核心文件
    if 'core' in rel_path or 'lib' in rel_path:
        score += 5
        reasons.append("位于核心目录")

    # 配置文件
    if 'config' in name or 'setting' in name:
        score += 3
        reasons.append("配置文件")

    # 工具文件
    if 'util' in name or 'helper' in name or 'tool' in name:
        score += 4
        reasons.append("工具文件")

    # 2. 文件大小
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        line_count = len(lines)
        metrics['line_count'] = line_count

        # 大文件
        if line_count > 500:
            score += 5
            reasons.append(f"大文件({line_count}行)")
        elif line_count > 200:
            score += 2
            reasons.append(f"中等大小文件({line_count}行)")

    except:
        line_count = 0
        metrics['line_count'] = 0

    # 3. 代码结构
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        tree = ast.parse(content)

        function_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        class_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))

        metrics['function_count'] = function_count
        metrics['class_count'] = class_count

        # 类多的文件
        if class_count >= 5:
            score += 6
            reasons.append(f"定义{class_count}个类")

        # 函数多的文件
        if function_count >= 10:
            score += 4
            reasons.append(f"定义{function_count}个函数")

        # 数据类
        if '@dataclass' in content:
            score += 2
            reasons.append("使用dataclass")

    except:
        metrics['function_count'] = 0
        metrics['class_count'] = 0

    # 4. 导入/被导入情况
    try:
        # 统计本文件的导出
        exports = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                exports.add(node.name)

        metrics['exports'] = len(exports)

        if len(exports) >= 5:
            score += 3
            reasons.append(f"导出{len(exports)}个符号")

    except:
        metrics['exports'] = 0

    # 5. 文档和注释
    try:
        docstring_count = sum(
            1 for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Module))
            and ast.get_docstring(n)
        )

        metrics['docstring_count'] = docstring_count

        if docstring_count > 5:
            score += 2
            reasons.append(f"包含{docstring_count}个文档字符串")

    except:
        metrics['docstring_count'] = 0

    # 6. 测试文件
    if 'test' in name or 'spec' in name:
        score += 1
        reasons.append("测试文件")

    return score, reasons, metrics


def module_map(
    project_root: str = ".",
    output_format: str = "dict"
) -> Any:
    """
    依赖关系图

    Args:
        project_root: 项目根目录
        output_format: 输出格式 ('dict', 'json', 'graphviz')

    Returns:
        依赖关系图
    """
    modules = {}
    edges = []

    # 扫描所有Python文件
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']

        for filename in files:
            if filename.endswith('.py'):
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, project_root)

                # 生成模块名
                module_name = _path_to_module(rel_path)

                # 解析imports
                imports = _extract_imports(file_path)

                modules[module_name] = ModuleInfo(
                    name=module_name,
                    file_path=rel_path,
                    imports=imports,
                    imported_by=set(),
                    exports=set()
                )

                # 添加边
                for imp in imports:
                    edges.append(DependencyEdge(
                        from_module=module_name,
                        to_module=imp,
                        edge_type='import'
                    ))

    # 构建反向引用
    for edge in edges:
        if edge.to_module in modules:
            modules[edge.to_module].imported_by.add(edge.from_module)

    # 提取exports(函数和类)
    for module_name, module_info in modules.items():
        file_path = os.path.join(project_root, module_info.file_path)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        module_info.exports.add(node.name)

            except:
                pass

    # 计算度量
    metrics = _calculate_module_metrics(modules, edges)

    # 构建结果
    result = {
        'modules': {
            name: {
                'file_path': info.file_path,
                'imports': list(info.imports),
                'imported_by': list(info.imported_by),
                'exports': list(info.exports),
                'metrics': metrics.get(name, {})
            }
            for name, info in modules.items()
        },
        'edges': [
            {
                'from': e.from_module,
                'to': e.to_module,
                'type': e.edge_type
            }
            for e in edges
        ],
        'metrics': {
            'total_modules': len(modules),
            'total_edges': len(edges),
            'most_imported': metrics.get('most_imported', []),
            'most_importing': metrics.get('most_importing', [])
        }
    }

    # 格式化输出
    if output_format == 'json':
        return json.dumps(result, indent=2, ensure_ascii=False)
    elif output_format == 'graphviz':
        return _generate_graphviz(result)
    else:
        return result


def _path_to_module(path: str) -> str:
    """路径转模块名"""
    # 移除.py后缀
    if path.endswith('.py'):
        path = path[:-3]

    # 转换路径分隔符
    path = path.replace(os.sep, '.')

    # 移除__init__
    if path.endswith('.__init__'):
        path = path[:-9]

    return path


def _extract_imports(file_path: str) -> Set[str]:
    """提取import"""
    imports = set()

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        tree = ast.parse(content)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if module:
                    imports.add(module)

    except:
        pass

    return imports


def _calculate_module_metrics(
    modules: Dict[str, ModuleInfo],
    edges: List[DependencyEdge]
) -> Dict[str, Any]:
    """计算模块度量"""
    metrics = {}

    # 每个模块的度量
    for name, info in modules.items():
        metrics[name] = {
            'import_count': len(info.imports),
            'imported_by_count': len(info.imported_by),
            'export_count': len(info.exports),
            'coupling': len(info.imports) + len(info.imported_by)
        }

    # 全局度量
    imported_by_counter = Counter(
        edge.to_module for edge in edges
        if edge.to_module in modules
    )

    importing_counter = Counter(
        edge.from_module for edge in edges
        if edge.from_module in modules
    )

    metrics['most_imported'] = [
        {'module': m, 'count': c}
        for m, c in imported_by_counter.most_common(10)
    ]

    metrics['most_importing'] = [
        {'module': m, 'count': c}
        for m, c in importing_counter.most_common(10)
    ]

    return metrics


def _generate_graphviz(graph: Dict[str, Any]) -> str:
    """生成Graphviz格式"""
    lines = ['digraph module_dependencies {']
    lines.append('  rankdir=LR;')
    lines.append('  node [shape=box];')

    # 添加节点
    for name, info in graph['modules'].items():
        label = name
        if info['metrics'].get('export_count', 0) > 5:
            label += f"\\n({info['metrics']['export_count']} exports)"
        lines.append(f'  "{name}" [label="{label}"];')

    # 添加边
    for edge in graph['edges']:
        lines.append(f'  "{edge["from"]}" -> "{edge["to"]}";')

    lines.append('}')

    return '\n'.join(lines)


def find_orphan_modules(
    project_root: str = "."
) -> List[str]:
    """
    查找孤立模块(不被任何模块导入)

    Args:
        project_root: 项目根目录

    Returns:
        孤立模块列表
    """
    graph = module_map(project_root, output_format='dict')

    orphans = []
    for name, info in graph['modules'].items():
        metrics = info.get('metrics', {})
        imported_by_count = metrics.get('imported_by_count', 0)
        if imported_by_count == 0:
            # 排除主入口
            if not any(keyword in name for keyword in ['main', '__init__', 'app', 'run']):
                orphans.append(name)

    return orphans


def find_circular_dependencies(
    project_root: str = "."
) -> List[List[str]]:
    """
    查找循环依赖

    Args:
        project_root: 项目根目录

    Returns:
        循环依赖列表
    """
    graph = module_map(project_root, output_format='dict')

    # 构建邻接表
    adj = {}
    for edge in graph['edges']:
        from_node = edge['from']
        to_node = edge['to']
        if from_node not in adj:
            adj[from_node] = []
        adj[from_node].append(to_node)

    # DFS检测环
    cycles = []
    visited = set()
    rec_stack = set()
    path = []

    def dfs(node):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        if node in adj:
            for neighbor in adj[node]:
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    # 找到环
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)
                    return True

        path.pop()
        rec_stack.remove(node)
        return False

    for node in adj:
        if node not in visited:
            dfs(node)

    return cycles


def create_project_snapshot(
    project_root: str = ".",
    output_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    创建项目快照

    Args:
        project_root: 项目根目录
        output_path: 输出文件路径(可选)

    Returns:
        项目快照
    """
    snapshot = {
        'key_files': [
            {
                'path': f.file_path,
                'score': f.importance_score,
                'reasons': f.reasons,
                'metrics': f.metrics
            }
            for f in key_files(project_root)
        ],
        'module_graph': module_map(project_root, output_format='dict'),
        'orphans': find_orphan_modules(project_root),
        'circular_dependencies': find_circular_dependencies(project_root)
    }

    # 保存到文件
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)

    return snapshot