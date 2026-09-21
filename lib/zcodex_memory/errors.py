"""插件内部异常类型。"""


class ZCodexMemoryError(Exception):
    """插件可预期错误的基类。"""


class ConfigError(ZCodexMemoryError):
    """配置无效。"""


class ValidationError(ZCodexMemoryError):
    """输入或记忆文件格式无效。"""


class ConflictError(ZCodexMemoryError):
    """文件在读取后被其他进程修改。"""


class LockError(ZCodexMemoryError):
    """无法取得项目锁。"""


class BackendError(ZCodexMemoryError):
    """存储后端不可用。"""


class ExtractionError(ZCodexMemoryError):
    """后台记忆提取失败。"""
