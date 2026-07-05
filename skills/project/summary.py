"""
智能摘要模块
- summarize_file: 文件功能摘要
- summarize_session: 会话摘要
- diff_summary: diff摘要
"""

import re
import ast
import os
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from collections import Counter


@dataclass
class FunctionSummary:
    """函数摘要"""
    name: str
    line: int
    parameters: List[str]
    docstring: Optional[str]
    complexity: int


@dataclass
class ClassSummary:
    """类摘要"""
    name: str
    line: int
    methods: List[str]
    docstring: Optional[str]
    parent_classes: List[str]


@dataclass
class FileSummary:
    """文件摘要"""
    file_path: str
    total_lines: int
    functions: List[FunctionSummary]
    classes: List[ClassSummary]
    imports: List[str]
    key_features: List[str]
    complexity_score: int


def summarize_file(file_path: str) -> FileSummary:
    """
    文件功能摘要

    Args:
        file_path: 文件路径

    Returns:
        文件摘要
    """
    if not os.path.exists(file_path):
        return FileSummary(
            file_path=file_path,
            total_lines=0,
            functions=[],
            classes=[],
            imports=[],
            key_features=[],
            complexity_score=0
        )

    # 读取文件
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        lines = content.split('\n')

    # 解析AST
    try:
        tree = ast.parse(content)
    except:
        # 解析失败,返回基本摘要
        return FileSummary(
            file_path=file_path,
            total_lines=len(lines),
            functions=[],
            classes=[],
            imports=[],
            key_features=[],
            complexity_score=0
        )

    # 提取信息
    functions = []
    classes = []
    imports = []
    key_features = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            params = [arg.arg for arg in node.args.args]
            complexity = _calculate_complexity(node)
            functions.append(FunctionSummary(
                name=node.name,
                line=node.lineno,
                parameters=params,
                docstring=ast.get_docstring(node),
                complexity=complexity
            ))
        elif isinstance(node, ast.AsyncFunctionDef):
            params = [arg.arg for arg in node.args.args]
            complexity = _calculate_complexity(node)
            functions.append(FunctionSummary(
                name=node.name,
                line=node.lineno,
                parameters=params,
                docstring=ast.get_docstring(node),
                complexity=complexity
            ))

        elif isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            parents = [ast.unparse(base) for base in node.bases]
            classes.append(ClassSummary(
                name=node.name,
                line=node.lineno,
                methods=methods,
                docstring=ast.get_docstring(node),
                parent_classes=parents
            ))

    # 提取imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            for alias in node.names:
                if module:
                    imports.append(f"{module}.{alias.name}")
                else:
                    imports.append(alias.name)

    # 提取关键特征
    key_features = _extract_key_features(content, functions, classes)

    # 计算复杂度
    complexity_score = sum(f.complexity for f in functions)

    return FileSummary(
        file_path=file_path,
        total_lines=len(lines),
        functions=functions,
        classes=classes,
        imports=imports,
        key_features=key_features,
        complexity_score=complexity_score
    )


def _calculate_complexity(node: ast.AST) -> int:
    """计算圈复杂度"""
    complexity = 1

    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1

    return complexity


def _extract_key_features(
    content: str,
    functions: List[FunctionSummary],
    classes: List[ClassSummary]
) -> List[str]:
    """提取关键特征"""
    features = []

    # 检测装饰器
    decorators = re.findall(r'@(\w+)', content)
    unique_decorators = set(decorators)
    if unique_decorators:
        features.append(f"装饰器: {', '.join(unique_decorators)}")

    # 检测异步函数
    async_funcs = [f.name for f in functions if 'async' in str(f).lower()]
    if async_funcs:
        features.append(f"异步函数: {', '.join(async_funcs[:3])}")

    # 检测类继承
    inherited = [c.name for c in classes if c.parent_classes]
    if inherited:
        features.append(f"继承类: {', '.join(inherited)}")

    # 检测数据类
    if '@dataclass' in content:
        features.append("使用dataclass")

    # 检测类型注解
    if re.search(r':\s*(str|int|float|bool|List|Dict|Optional)', content):
        features.append("使用类型注解")

    # 检测异常处理
    if 'try:' in content or 'except' in content:
        features.append("包含异常处理")

    # 检测日志
    if 'logging' in content or 'logger' in content:
        features.append("包含日志")

    # 检测数据库操作
    db_keywords = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'sql', 'query']
    if any(kw.lower() in content.lower() for kw in db_keywords):
        features.append("包含数据库操作")

    # 检测网络请求
    if 'requests' in content or 'http' in content.lower():
        features.append("包含网络请求")

    return features


@dataclass
class MessageSummary:
    """消息摘要"""
    role: str
    key_topics: List[str]
    action: str
    entities: List[str]


@dataclass
class SessionSummary:
    """会话摘要"""
    session_id: str
    total_messages: int
    user_messages: int
    assistant_messages: int
    key_topics: List[str]
    actions: List[str]
    entities: List[str]
    summary: str


def summarize_session(messages: List[Dict[str, Any]]) -> SessionSummary:
    """
    会话摘要

    Args:
        messages: 消息列表,每个消息包含role和content

    Returns:
        会话摘要
    """
    total_messages = len(messages)
    user_messages = sum(1 for m in messages if m.get('role') == 'user')
    assistant_messages = sum(1 for m in messages if m.get('role') == 'assistant')

    # 提取关键主题
    all_topics = []
    all_actions = []
    all_entities = []

    for msg in messages:
        content = msg.get('content', '')
        role = msg.get('role', '')

        # 提取主题(名词短语)
        topics = _extract_topics(content)
        all_topics.extend(topics)

        # 提取动作(动词)
        if role == 'user':
            actions = _extract_actions(content)
            all_actions.extend(actions)

        # 提取实体(代码相关)
        entities = _extract_code_entities(content)
        all_entities.extend(entities)

    # 统计频率
    topic_counter = Counter(all_topics)
    action_counter = Counter(all_actions)
    entity_counter = Counter(all_entities)

    # 生成摘要
    key_topics = [t for t, _ in topic_counter.most_common(5)]
    actions = [a for a, _ in action_counter.most_common(3)]
    entities = [e for e, _ in entity_counter.most_common(5)]

    summary = _generate_session_summary(key_topics, actions)

    return SessionSummary(
        session_id="",
        total_messages=total_messages,
        user_messages=user_messages,
        assistant_messages=assistant_messages,
        key_topics=key_topics,
        actions=actions,
        entities=entities,
        summary=summary
    )


def _extract_topics(content: str) -> List[str]:
    """提取主题"""
    # 简单实现:提取代码标识符
    topics = re.findall(r'\b[A-Z][a-zA-Z]*\b', content)
    return topics[:10]


def _extract_actions(content: str) -> List[str]:
    """提取动作"""
    action_keywords = [
        '创建', '修改', '删除', '添加', '实现', '修复', '优化', '重构',
        'create', 'modify', 'delete', 'add', 'implement', 'fix', 'optimize', 'refactor'
    ]
    actions = []
    for kw in action_keywords:
        if kw.lower() in content.lower():
            actions.append(kw)
    return actions


def _extract_code_entities(content: str) -> List[str]:
    """提取代码实体"""
    # 提取函数名、类名、文件名
    entities = []

    # 文件名
    files = re.findall(r'[\w-]+\.py', content)
    entities.extend(files)

    # 函数调用
    funcs = re.findall(r'(\w+)\s*\(', content)
    entities.extend(funcs)

    return entities


def _generate_session_summary(
    topics: List[str],
    actions: List[str]
) -> str:
    """生成会话摘要"""
    if not topics and not actions:
        return "一般性对话"

    parts = []
    if actions:
        parts.append(f"执行操作: {', '.join(actions)}")
    if topics:
        parts.append(f"涉及主题: {', '.join(topics[:3])}")

    return '; '.join(parts) if parts else "技术对话"


@dataclass
class DiffSummary:
    """Diff摘要"""
    file_path: str
    total_changes: int
    added_lines: int
    removed_lines: int
    changed_functions: List[str]
    changed_classes: List[str]
    impact_level: str  # 'low', 'medium', 'high'
    summary: str


def diff_summary(
    file_path: str,
    diff_lines: List[Any]  # DiffLine对象列表
) -> DiffSummary:
    """
    Diff摘要

    Args:
        file_path: 文件路径
        diff_lines: diff行列表

    Returns:
        diff摘要
    """
    if not diff_lines:
        return DiffSummary(
            file_path=file_path,
            total_changes=0,
            added_lines=0,
            removed_lines=0,
            changed_functions=[],
            changed_classes=[],
            impact_level='low',
            summary="无变更"
        )

    total_changes = len(diff_lines)
    added_lines = sum(1 for l in diff_lines if hasattr(l, 'change_type') and l.change_type == 'added')
    removed_lines = sum(1 for l in diff_lines if hasattr(l, 'change_type') and l.change_type == 'removed')

    # 读取文件,分析受影响的函数和类
    changed_functions = []
    changed_classes = []

    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        try:
            tree = ast.parse(content)

            # 获取变更行号
            change_line_numbers = {l.line for l in diff_lines}

            # 检查哪些函数受影响
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # 检查函数定义行或函数体行是否在变更中
                    if node.lineno in change_line_numbers:
                        changed_functions.append(node.name)
                    else:
                        # 检查函数体
                        for child in ast.walk(node):
                            if hasattr(child, 'lineno') and child.lineno in change_line_numbers:
                                changed_functions.append(node.name)
                                break

                elif isinstance(node, ast.ClassDef):
                    if node.lineno in change_line_numbers:
                        changed_classes.append(node.name)
                    else:
                        for child in ast.walk(node):
                            if hasattr(child, 'lineno') and child.lineno in change_line_numbers:
                                changed_classes.append(node.name)
                                break

        except:
            pass

    # 去重
    changed_functions = list(set(changed_functions))
    changed_classes = list(set(changed_classes))

    # 评估影响级别
    if total_changes < 10:
        impact_level = 'low'
    elif total_changes < 50:
        impact_level = 'medium'
    else:
        impact_level = 'high'

    # 生成摘要
    summary_parts = []
    summary_parts.append(f"总变更: {total_changes}行")
    summary_parts.append(f"新增: {added_lines}行, 删除: {removed_lines}行")

    if changed_functions:
        summary_parts.append(f"影响函数: {len(changed_functions)}个")
    if changed_classes:
        summary_parts.append(f"影响类: {len(changed_classes)}个")

    summary = ', '.join(summary_parts)

    return DiffSummary(
        file_path=file_path,
        total_changes=total_changes,
        added_lines=added_lines,
        removed_lines=removed_lines,
        changed_functions=changed_functions,
        changed_classes=changed_classes,
        impact_level=impact_level,
        summary=summary
    )


def summarize_project(
    project_root: str = ".",
    max_files: int = 20
) -> Dict[str, Any]:
    """
    项目摘要

    Args:
        project_root: 项目根目录
        max_files: 最大文件数

    Returns:
        项目摘要
    """
    summaries = []

    for root, _, files in os.walk(project_root):
        # 跳过隐藏目录
        if any(skip in root for skip in ['.git', '__pycache__', 'node_modules', '.venv']):
            continue

        for filename in files:
            if filename.endswith('.py'):
                file_path = os.path.join(root, filename)
                summary = summarize_file(file_path)
                summaries.append(summary)

                if len(summaries) >= max_files:
                    break

        if len(summaries) >= max_files:
            break

    # 统计
    total_functions = sum(len(s.functions) for s in summaries)
    total_classes = sum(len(s.classes) for s in summaries)
    total_complexity = sum(s.complexity_score for s in summaries)

    # 聚合关键特征
    all_features = []
    for s in summaries:
        all_features.extend(s.key_features)
    feature_counter = Counter(all_features)

    return {
        'files_analyzed': len(summaries),
        'total_functions': total_functions,
        'total_classes': total_classes,
        'average_complexity': total_complexity / len(summaries) if summaries else 0,
        'common_features': [f for f, _ in feature_counter.most_common(10)],
        'file_summaries': [
            {
                'file': s.file_path,
                'functions': len(s.functions),
                'classes': len(s.classes),
                'complexity': s.complexity_score
            }
            for s in summaries
        ]
    }