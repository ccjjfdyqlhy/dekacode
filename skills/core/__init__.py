"""
Core工具模块初始化
"""

from .batch import (
    batch_bash,
    batch_symbol_search,
    batch_process,
)

from .cache import (
    cached_file,
    cached_result,
    FileCache,
    ResultCache,
    clear_file_cache,
    clear_result_cache,
    get_cache_stats,
)

from .chunk import (
    smart_read_file,
    stream_file,
    smart_grep,
)

from .locator import (
    find_definition,
    find_references,
    locate_symbol,
    find_all_symbols,
    SymbolLocation,
    DefinitionInfo,
    ReferenceInfo
)

from .diagnose import (
    diagnose_error,
    fix_imports,
    check_syntax,
)

__all__ = [
    # batch
    'batch_bash',
    'batch_symbol_search',
    'batch_process',

    # cache
    'cached_file',
    'cached_result',
    'FileCache',
    'ResultCache',
    'clear_file_cache',
    'clear_result_cache',
    'get_cache_stats',

    # chunk
    'smart_read_file',
    'stream_file',
    'smart_grep',

    # locator
    'find_definition',
    'find_references',
    'locate_symbol',
    'find_all_symbols',
    'SymbolLocation',
    'DefinitionInfo',
    'ReferenceInfo',

    # diagnose
    'diagnose_error',
    'fix_imports',
    'check_syntax',
]