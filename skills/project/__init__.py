"""
Project工具模块初始化
"""

from .incremental import (
    git_diff_lines,
    file_delta,
    incremental_graph,
    get_changed_files,
    get_file_change_summary,
)

from .summary import (
    summarize_file,
    summarize_project,
    summarize_session,
    diff_summary,
)

from .snapshot import (
    key_files,
    module_map,
    create_project_snapshot,
    find_orphan_modules,
    find_circular_dependencies,
)

__all__ = [
    # incremental
    'git_diff_lines',
    'file_delta',
    'incremental_graph',
    'get_changed_files',
    'get_file_change_summary',

    # summary
    'summarize_file',
    'summarize_project',
    'summarize_session',
    'diff_summary',

    # snapshot
    'key_files',
    'module_map',
    'create_project_snapshot',
    'find_orphan_modules',
    'find_circular_dependencies',
]