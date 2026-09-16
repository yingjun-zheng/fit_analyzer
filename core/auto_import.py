"""文件夹监控自动导入（P3）：扫描监控目录里的新 FIT 文件。

策略：GUI 侧 QTimer 轮询（不引 watchdog 依赖，稳且零成本）；
用 (大小, mtime_ns) 指纹识别「新/变化」文件，已见过的不再重复解析；
DB 层 file_hash 去重兜底（重复导入 upsert 为更新，无害）。
"""
from pathlib import Path


def scan_new_files(folder, seen, exts=(".fit",)):
    """扫描 folder，返回 (新文件路径列表[str], 更新后的 seen)。

    seen: {str(路径): (size, mtime_ns)}——指纹变化视为新文件。
    目录不存在返回 ([], seen)；目录中已消失的文件会从 seen 中清除（防无限增长）。
    """
    folder = Path(folder)
    if not folder.is_dir():
        return [], dict(seen)
    seen = dict(seen)
    new = []
    current = set()
    for p in sorted(folder.iterdir()):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        current.add(str(p))
        try:
            st = p.stat()
        except OSError:
            continue
        fp = (st.st_size, st.st_mtime_ns)
        if seen.get(str(p)) != fp:
            new.append(str(p))
            seen[str(p)] = fp
    for gone in set(seen) - current:
        seen.pop(gone, None)
    return new, seen
