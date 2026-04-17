"""SFTP 文件管理器组件 —— 浏览远程文件，支持上传/下载。"""

import os
import stat
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLineEdit, QFileDialog, QMessageBox, QProgressBar,
    QHeaderView, QMenu, QStackedWidget, QScrollArea, QSizePolicy, QLabel,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QEvent
from PyQt6.QtGui import QAction, QKeyEvent, QMouseEvent
import paramiko


class TransferThread(QThread):
    """后台文件传输线程。"""
    progress = pyqtSignal(int)       # 百分比
    finished = pyqtSignal(str)       # 空字符串=成功，否则=错误信息
    status = pyqtSignal(str)         # 状态文字

    def __init__(self, sftp: paramiko.SFTPClient, mode: str,
                 remote_path: str, local_path: str):
        super().__init__()
        self.sftp = sftp
        self.mode = mode  # "upload" 或 "download"
        self.remote_path = remote_path
        self.local_path = local_path

    def run(self):
        try:
            if self.mode == "download":
                self.status.emit(f"正在下载: {self.remote_path}")
                file_stat = self.sftp.stat(self.remote_path)
                total = file_stat.st_size or 1

                def callback(transferred, _total):
                    self.progress.emit(int(transferred / total * 100))

                self.sftp.get(self.remote_path, self.local_path, callback=callback)
            else:
                self.status.emit(f"正在上传: {self.local_path}")
                total = os.path.getsize(self.local_path) or 1

                def callback(transferred, _total):
                    self.progress.emit(int(transferred / total * 100))

                self.sftp.put(self.local_path, self.remote_path, callback=callback)

            self.finished.emit("")
        except Exception as e:
            self.finished.emit(str(e))


class SFTPWidget(QWidget):
    """SFTP 文件浏览器。"""

    def __init__(self, sftp: paramiko.SFTPClient, parent=None):
        super().__init__(parent)
        self.sftp = sftp
        self.current_path = "/"
        self._transfer_thread: TransferThread | None = None
        self._build_ui()
        self._navigate("/")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 路径栏：面包屑导航 + 手动输入（双击切换）
        path_layout = QHBoxLayout()

        self.path_stack = QStackedWidget()
        self.path_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.path_stack.setFixedHeight(32)

        # 页面 0：面包屑导航
        self._breadcrumb_container = QWidget()
        self._breadcrumb_container.mouseDoubleClickEvent = self._switch_to_edit
        breadcrumb_outer = QHBoxLayout(self._breadcrumb_container)
        breadcrumb_outer.setContentsMargins(4, 0, 0, 0)
        breadcrumb_outer.setSpacing(0)
        self._breadcrumb_layout = QHBoxLayout()
        self._breadcrumb_layout.setContentsMargins(0, 0, 0, 0)
        self._breadcrumb_layout.setSpacing(0)
        breadcrumb_outer.addLayout(self._breadcrumb_layout)
        breadcrumb_outer.addStretch()
        self._breadcrumb_container.setStyleSheet(
            "QWidget { background: #ffffff; border: 1px solid #d0d0d0; border-radius: 4px; }"
        )
        self.path_stack.addWidget(self._breadcrumb_container)

        # 页面 1：手动输入框
        self.path_edit = QLineEdit("/")
        self.path_edit.returnPressed.connect(self._on_path_enter)
        self.path_stack.addWidget(self.path_edit)

        self.path_stack.setCurrentIndex(0)
        path_layout.addWidget(self.path_stack)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(lambda: self._navigate(self.current_path))
        path_layout.addWidget(refresh_btn)

        layout.addLayout(path_layout)

        # 文件树
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "大小", "权限", "修改时间"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 100)
        self.tree.setColumnWidth(3, 160)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.setStyleSheet(
            "QTreeWidget::item:selected { color: #000000; }"
        )
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.installEventFilter(self)
        layout.addWidget(self.tree)

        # 操作按钮
        btn_layout = QHBoxLayout()
        upload_btn = QPushButton("上传文件")
        upload_btn.clicked.connect(self._upload)
        btn_layout.addWidget(upload_btn)

        download_btn = QPushButton("下载文件")
        download_btn.clicked.connect(self._download)
        btn_layout.addWidget(download_btn)

        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(self._delete)
        btn_layout.addWidget(delete_btn)

        mkdir_btn = QPushButton("新建文件夹")
        mkdir_btn.clicked.connect(self._mkdir)
        btn_layout.addWidget(mkdir_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLineEdit()
        self.status_label.setReadOnly(True)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

    def eventFilter(self, obj, event):
        if obj is self.tree and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            modifiers = event.modifiers()
            # Enter 进入文件夹
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not modifiers:
                item = self.tree.currentItem()
                if item:
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if data and data["is_dir"]:
                        new_path = self.current_path.rstrip("/") + "/" + data["filename"]
                        self._navigate(new_path)
                        return True
            # Alt+Up 返回上级目录
            if key == Qt.Key.Key_Up and modifiers == Qt.KeyboardModifier.AltModifier:
                self._go_up()
                return True
        return super().eventFilter(obj, event)

    def _navigate(self, path: str):
        try:
            entries = self.sftp.listdir_attr(path)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开目录: {e}")
            return

        self.current_path = path
        self.path_edit.setText(path)
        self._update_breadcrumb(path)
        self.path_stack.setCurrentIndex(0)
        self.tree.clear()

        # 按目录优先、名称排序
        dirs = []
        files = []
        for entry in entries:
            if stat.S_ISDIR(entry.st_mode or 0):
                dirs.append(entry)
            else:
                files.append(entry)
        dirs.sort(key=lambda e: e.filename.lower())
        files.sort(key=lambda e: e.filename.lower())

        for entry in dirs + files:
            is_dir = stat.S_ISDIR(entry.st_mode or 0)
            size_str = "" if is_dir else self._format_size(entry.st_size or 0)
            perm_str = self._format_permissions(entry.st_mode or 0)
            mtime_str = datetime.fromtimestamp(entry.st_mtime or 0).strftime("%Y-%m-%d %H:%M:%S")

            item = QTreeWidgetItem([
                ("📁 " if is_dir else "📄 ") + entry.filename,
                size_str,
                perm_str,
                mtime_str,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "filename": entry.filename,
                "is_dir": is_dir,
                "size": entry.st_size or 0,
            })
            self.tree.addTopLevelItem(item)

    def _update_breadcrumb(self, path: str):
        """根据路径刷新面包屑按钮。"""
        # 清空旧的面包屑
        while self._breadcrumb_layout.count():
            item = self._breadcrumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        parts = [p for p in path.split("/") if p]
        # 根目录按钮
        root_btn = QPushButton("/")
        root_btn.setFlat(True)
        root_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        root_btn.setStyleSheet(
            "QPushButton { color: #1a73e8; font-size: 13px; padding: 2px 4px; border: none; background: transparent; }"
            "QPushButton:hover { text-decoration: underline; color: #1558b0; }"
        )
        root_btn.clicked.connect(lambda: self._navigate("/"))
        self._breadcrumb_layout.addWidget(root_btn)

        for i, part in enumerate(parts):
            # 分隔符
            sep = QLabel(">")
            sep.setStyleSheet("QLabel { color: #999999; font-size: 13px; padding: 0 2px; background: transparent; border: none; }")
            self._breadcrumb_layout.addWidget(sep)

            # 路径按钮
            target_path = "/" + "/".join(parts[:i + 1])
            btn = QPushButton(part)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            is_last = (i == len(parts) - 1)
            if is_last:
                btn.setStyleSheet(
                    "QPushButton { color: #333333; font-size: 13px; font-weight: bold; padding: 2px 4px; border: none; background: transparent; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { color: #1a73e8; font-size: 13px; padding: 2px 4px; border: none; background: transparent; }"
                    "QPushButton:hover { text-decoration: underline; color: #1558b0; }"
                )
            btn.clicked.connect(lambda checked, p=target_path: self._navigate(p))
            self._breadcrumb_layout.addWidget(btn)

    def _switch_to_edit(self, event):
        """双击面包屑栏切换到手动输入模式。"""
        self.path_edit.setText(self.current_path)
        self.path_stack.setCurrentIndex(1)
        self.path_edit.setFocus()
        self.path_edit.selectAll()

    def _on_path_enter(self):
        self._navigate(self.path_edit.text().strip())

    def _go_up(self):
        parent = os.path.dirname(self.current_path.rstrip("/"))
        self._navigate(parent or "/")

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data["is_dir"]:
            new_path = self.current_path.rstrip("/") + "/" + data["filename"]
            self._navigate(new_path)

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        data = item.data(0, Qt.ItemDataRole.UserRole)

        if not data["is_dir"]:
            dl_action = QAction("下载", self)
            dl_action.triggered.connect(self._download)
            menu.addAction(dl_action)

        del_action = QAction("删除", self)
        del_action.triggered.connect(self._delete)
        menu.addAction(del_action)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _upload(self):
        local_path, _ = QFileDialog.getOpenFileName(self, "选择要上传的文件")
        if not local_path:
            return
        filename = os.path.basename(local_path)
        remote_path = self.current_path.rstrip("/") + "/" + filename
        self._start_transfer("upload", remote_path, local_path)

    def _download(self):
        item = self.tree.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data["is_dir"]:
            QMessageBox.information(self, "提示", "暂不支持下载整个文件夹")
            return
        remote_path = self.current_path.rstrip("/") + "/" + data["filename"]
        local_path, _ = QFileDialog.getSaveFileName(
            self, "保存到本地", data["filename"]
        )
        if not local_path:
            return
        self._start_transfer("download", remote_path, local_path)

    def _start_transfer(self, mode: str, remote_path: str, local_path: str):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setVisible(True)

        self._transfer_thread = TransferThread(self.sftp, mode, remote_path, local_path)
        self._transfer_thread.progress.connect(self.progress_bar.setValue)
        self._transfer_thread.status.connect(self.status_label.setText)
        self._transfer_thread.finished.connect(self._on_transfer_finished)
        self._transfer_thread.start()

    def _on_transfer_finished(self, error: str):
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)
        if error:
            QMessageBox.warning(self, "传输失败", error)
        else:
            QMessageBox.information(self, "完成", "文件传输完成")
            self._navigate(self.current_path)

    def _delete(self):
        item = self.tree.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        path = self.current_path.rstrip("/") + "/" + data["filename"]

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除 {'目录' if data['is_dir'] else '文件'} \"{data['filename']}\" 吗？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            if data["is_dir"]:
                self.sftp.rmdir(path)
            else:
                self.sftp.remove(path)
            self._navigate(self.current_path)
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))

    def _mkdir(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "新建文件夹", "文件夹名称:")
        if ok and name.strip():
            try:
                self.sftp.mkdir(self.current_path.rstrip("/") + "/" + name.strip())
                self._navigate(self.current_path)
            except Exception as e:
                QMessageBox.warning(self, "创建失败", str(e))

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
            size /= 1024
        return f"{size:.1f} PB"

    @staticmethod
    def _format_permissions(mode: int) -> str:
        chars = ""
        for who in (6, 3, 0):  # owner, group, other
            r = "r" if mode & (4 << who) else "-"
            w = "w" if mode & (2 << who) else "-"
            x = "x" if mode & (1 << who) else "-"
            chars += r + w + x
        return chars
