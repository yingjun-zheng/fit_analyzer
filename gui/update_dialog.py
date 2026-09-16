"""更新弹窗与下载进度窗口。

UpdateDialog：发现新版本时展示版本信息 + 更新日志，用户选择
  「立即更新 / 稍后 / 忽略此版本」。
DownloadProgressDialog：后台线程下载更新包，进度实时刷新；
  完成校验后由调用方执行应用替换。
"""
import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from core import updater

log = logging.getLogger("fit.updatedlg")


def changelog_to_html(changelog, highlight_version=None):
    """changelog 列表 → 可读 HTML（最新版高亮为“本版更新”）。"""
    if not changelog:
        return "<p style='color:#8b98a5'>暂无更新日志</p>"
    blocks = []
    for i, item in enumerate(changelog):
        ver = item.get("version") or "?"
        date = item.get("date") or ""
        notes = item.get("notes") or []
        title = f"v{ver}  <span style='color:#8b98a5;font-weight:400'>{date}</span>"
        if i == 0 and highlight_version and ver == highlight_version:
            title = f"✨ {title} <span style='color:#4da3ff'>(本版更新)</span>"
        items = "".join(f"<li>{n}</li>" for n in notes) or "<li>—</li>"
        blocks.append(f"<p style='margin:6px 0 2px'><b>{title}</b></p><ul>{items}</ul>")
    return "".join(blocks)


class UpdateDialog(QDialog):
    """发现新版本弹窗：展示更新日志，用户选择是否更新。"""

    def __init__(self, current_version, plan, parent=None):
        super().__init__(parent)
        self.plan = plan
        manifest = plan.get("manifest") or {}
        new_ver = manifest.get("version") or "?"
        self.setWindowTitle("发现新版本")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)

        head = QLabel(f"<h3 style='margin:0'>发现新版本 <span style='color:#4da3ff'>v{new_ver}</span></h3>"
                      f"<p style='color:#8b98a5;margin:4px 0 0'>当前版本 v{current_version}"
                      f" · 更新包 {plan.get('size', 0) / 1024 / 1024:.1f} MB"
                      f"（{'完整包' if plan.get('full') else '增量包'}）</p>")
        lay.addWidget(head)

        log_view = QTextBrowser()
        log_view.setOpenExternalLinks(True)
        log_view.setHtml(changelog_to_html(manifest.get("changelog"), highlight_version=new_ver))
        log_view.setMinimumHeight(260)
        lay.addWidget(log_view, 1)

        btns = QHBoxLayout()
        btn_later = QPushButton("稍后")
        btn_later.clicked.connect(self.reject)
        btn_ignore = QPushButton("忽略此版本")
        btn_ignore.clicked.connect(self._ignore)
        btn_go = QPushButton("🚀 立即更新")
        btn_go.setObjectName("primary")
        btn_go.clicked.connect(self.accept)
        btns.addWidget(btn_later)
        btns.addWidget(btn_ignore)
        btns.addStretch(1)
        btns.addWidget(btn_go)
        lay.addLayout(btns)
        self._ignored = False

    def _ignore(self):
        self._ignored = True
        self.accept()

    def choice(self):
        """用户选择：'update' | 'later' | 'ignore'。"""
        if self._ignored:
            return "ignore"
        return "update" if self.result() == QDialog.Accepted else "later"


class DownloadWorker(QThread):
    """后台下载更新包；progress(done, total) / finished_ok(path, sha256) / failed(msg)。"""

    progress = Signal(int, int)      # done_bytes, total_bytes(None→-1)
    done = Signal(str, str)          # zip 路径, 期望 sha256
    failed = Signal(str)

    def __init__(self, url, dest, sha256, parent=None):
        super().__init__(parent)
        self.url = url
        self.dest = dest
        self.sha256 = sha256

    def run(self):
        try:
            def on_progress(done, total):
                self.progress.emit(done, total if total else -1)
            updater.download_file(self.url, self.dest, on_progress=on_progress)
            actual = updater.sha256_file(self.dest)
            if self.sha256 and actual.lower() != self.sha256.lower():
                raise updater.UpdaterError(
                    f"下载文件校验失败（期望 {self.sha256[:12]}…，实际 {actual[:12]}…）")
            self.done.emit(str(self.dest), self.sha256)
        except Exception as e:  # noqa: BLE001
            log.exception("更新包下载失败")
            self.failed.emit(str(e))


class DownloadProgressDialog(QDialog):
    """下载进度窗口（自动关闭：成功/失败都会关闭）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("正在下载更新")
        self.setMinimumWidth(380)
        self.setModal(True)
        lay = QVBoxLayout(self)
        self.label = QLabel("准备下载…")
        lay.addWidget(self.label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        lay.addWidget(self.bar)
        self._worker = None

    def start_download(self, url, dest, sha256):
        self._worker = DownloadWorker(url, dest, sha256, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, done, total):
        if total and total > 0:
            self.bar.setValue(int(done * 100 / total))
            self.label.setText(f"下载中 {done / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB")
        else:
            self.label.setText(f"下载中… {done / 1024 / 1024:.1f} MB")

    def _on_done(self, path, sha256):
        self.label.setText("下载完成，校验通过 ✅")
        self.bar.setValue(100)
        self._result = ("ok", path)
        self.accept()

    def _on_failed(self, msg):
        self.label.setText(f"下载失败：{msg}")
        self._result = ("fail", msg)
        # 稍作停留让用户看到原因
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, self.accept)

    def result_info(self):
        return getattr(self, "_result", ("fail", "未知错误"))
