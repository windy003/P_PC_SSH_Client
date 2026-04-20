"""PySSH Client —— 桌面版 SSH 客户端主窗口。"""

import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QSplitter, QTabWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QMessageBox, QLabel, QStatusBar, QToolBar, QMenu, QSystemTrayIcon,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QFont, QIcon

from config import load_connections, add_connection, delete_connection, update_connection, load_settings, save_setting
from connection_dialog import ConnectionDialog
from ssh_manager import SSHSession
from terminal_widget import TerminalWidget
from sftp_widget import SFTPWidget


# ─── 样式表 ──────────────────────────────────────────────

STYLESHEET = """
QMainWindow {
    background-color: #ffffff;
}
QSplitter::handle {
    background-color: #e0e0e0;
    width: 2px;
}
QTabWidget::pane {
    border: none;
    background-color: #ffffff;
}
QTabBar::tab {
    background-color: #f0f0f0;
    color: #333333;
    padding: 6px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    min-width: 100px;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    color: #1a73e8;
}
QTabBar::tab:hover {
    background-color: #e4e4e4;
}
QListWidget {
    background-color: #ffffff;
    color: #333333;
    border: none;
    font-size: 13px;
    padding: 4px;
}
QListWidget::item {
    padding: 8px 12px;
    border-radius: 6px;
    margin: 2px 4px;
}
QListWidget::item:selected {
    background-color: #e3f2fd;
    color: #1a73e8;
}
QListWidget::item:hover {
    background-color: #f5f5f5;
}
QPushButton {
    background-color: #f0f0f0;
    color: #333333;
    border: 1px solid #d0d0d0;
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #e4e4e4;
}
QPushButton:pressed {
    background-color: #d0d0d0;
}
QLabel {
    color: #333333;
}
QStatusBar {
    background-color: #f5f5f5;
    color: #666666;
    font-size: 12px;
}
QToolBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e0e0e0;
    spacing: 4px;
    padding: 2px;
}
QLineEdit {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 4px 8px;
}
QSpinBox, QComboBox {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 4px 8px;
}
QTreeWidget {
    background-color: #ffffff;
    color: #333333;
    border: none;
    font-size: 13px;
}
QTreeWidget::item:selected {
    background-color: #e3f2fd;
}
QHeaderView::section {
    background-color: #f5f5f5;
    color: #666666;
    padding: 4px 8px;
    border: none;
    border-right: 1px solid #e0e0e0;
}
QProgressBar {
    background-color: #f0f0f0;
    border-radius: 4px;
    text-align: center;
    color: #333333;
}
QProgressBar::chunk {
    background-color: #1a73e8;
    border-radius: 4px;
}
QMenu {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #e0e0e0;
}
QMenu::item:selected {
    background-color: #e3f2fd;
}
QDialog {
    background-color: #ffffff;
    color: #333333;
}
QMessageBox {
    background-color: #ffffff;
    color: #333333;
}
"""


class SessionTab(QWidget):
    """一个 SSH 会话标签页，包含终端和可选的 SFTP 面板。"""

    def __init__(self, session: SSHSession, conn_info: dict, parent=None):
        super().__init__(parent)
        self.session = session
        self.conn_info = conn_info
        self.sftp_widget: SFTPWidget | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Orientation.Vertical)

        # 终端
        self.terminal = TerminalWidget()
        self.terminal.input_sent.connect(self.session.send)
        self.session.data_received.connect(self.terminal.append_data)
        self.splitter.addWidget(self.terminal)

        self.splitter.setStretchFactor(0, 3)
        layout.addWidget(self.splitter)

    def toggle_sftp(self):
        """切换 SFTP 面板的显示。"""
        if self.sftp_widget:
            self.sftp_widget.setVisible(not self.sftp_widget.isVisible())
            return

        sftp = self.session.open_sftp()
        if not sftp:
            QMessageBox.warning(self, "错误", "无法打开 SFTP 会话")
            return

        self.sftp_widget = SFTPWidget(sftp)
        self.splitter.addWidget(self.sftp_widget)

        # 恢复上次保存的高度，否则使用默认 1:3
        saved = load_settings().get("sftp_splitter_sizes")
        if saved and len(saved) == 2:
            self.splitter.setSizes(saved)
        else:
            total = self.splitter.height()
            self.splitter.setSizes([total // 4, total * 3 // 4])

        # 拖动分隔条时保存高度
        self.splitter.splitterMoved.connect(self._save_splitter_sizes)

    def _save_splitter_sizes(self):
        save_setting("sftp_splitter_sizes", self.splitter.sizes())

    def close_session(self):
        self.session.close()


class MainWindow(QMainWindow):
    """主窗口。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PySSH Client")
        self.resize(1100, 700)

        self._sessions: dict[int, SessionTab] = {}  # tab_index -> SessionTab

        import os
        icon_path = os.path.join(os.path.dirname(__file__), "256x256.ico")
        self._app_icon = QIcon(icon_path)
        self.setWindowIcon(self._app_icon)

        self._build_ui()
        self._build_tray()
        self._load_connections()

    def _build_ui(self):
        # 工具栏
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setMovable(False)

        new_action = QAction("新建连接", self)
        new_action.triggered.connect(self._new_connection)
        toolbar.addAction(new_action)

        connect_action = QAction("连接", self)
        connect_action.triggered.connect(self._connect_selected)
        toolbar.addAction(connect_action)

        sftp_action = QAction("SFTP", self)
        sftp_action.triggered.connect(self._toggle_sftp)
        toolbar.addAction(sftp_action)

        toolbar.addSeparator()

        edit_action = QAction("编辑", self)
        edit_action.triggered.connect(self._edit_connection)
        toolbar.addAction(edit_action)

        delete_action = QAction("删除", self)
        delete_action.triggered.connect(self._delete_connection)
        toolbar.addAction(delete_action)

        toolbar.addSeparator()

        self.toggle_action = QAction("折叠面板", self)
        self.toggle_action.triggered.connect(self._toggle_panel)
        toolbar.addAction(self.toggle_action)

        self.addToolBar(toolbar)

        # 主体 = 侧边栏 + 标签页
        self.splitter = QSplitter()

        # 左侧：连接列表
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)

        title_label = QLabel("连接列表")
        title_label.setFont(QFont("", 13, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(title_label)

        self.conn_list = QListWidget()
        self.conn_list.itemDoubleClicked.connect(self._connect_selected)
        self.conn_list.itemActivated.connect(self._connect_selected)
        left_layout.addWidget(self.conn_list)

        # 快捷按钮
        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ 新建")
        add_btn.clicked.connect(self._new_connection)
        btn_row.addWidget(add_btn)

        quick_btn = QPushButton("快速连接")
        quick_btn.clicked.connect(self._quick_connect)
        btn_row.addWidget(quick_btn)
        left_layout.addLayout(btn_row)

        self.splitter.addWidget(self.left_panel)

        # 右侧：标签页
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.splitter.addWidget(self.tab_widget)

        self.splitter.setSizes([220, 880])
        self.setCentralWidget(self.splitter)

        self._panel_visible = True

        # 状态栏
        self.statusBar().showMessage("就绪")

    def _load_connections(self):
        self.conn_list.clear()
        for conn in load_connections():
            display = f"{conn.get('name', '')}  ({conn['username']}@{conn['host']}:{conn['port']})"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, conn)
            self.conn_list.addItem(item)

    # ── 面板折叠/展开 ──────────────────────────────────────

    def _toggle_panel(self):
        self._panel_visible = not self._panel_visible
        self.left_panel.setVisible(self._panel_visible)
        self.toggle_action.setText("折叠面板" if self._panel_visible else "展开面板")

    # ── 连接管理 ──────────────────────────────────────────

    def _new_connection(self):
        dlg = ConnectionDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            add_connection(data)
            self._load_connections()

    def _edit_connection(self):
        item = self.conn_list.currentItem()
        if not item:
            return
        conn = item.data(Qt.ItemDataRole.UserRole)
        dlg = ConnectionDialog(self, data=conn)
        if dlg.exec():
            data = dlg.get_data()
            update_connection(conn["id"], data)
            self._load_connections()

    def _delete_connection(self):
        item = self.conn_list.currentItem()
        if not item:
            return
        conn = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除连接 \"{conn['name']}\" 吗？",
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_connection(conn["id"])
            self._load_connections()

    # ── 连接操作 ──────────────────────────────────────────

    def _connect_selected(self):
        item = self.conn_list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择一个连接")
            return
        conn = item.data(Qt.ItemDataRole.UserRole)
        self._open_session(conn)

    def _quick_connect(self):
        dlg = ConnectionDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            self._open_session(data)

    def _open_session(self, conn: dict):
        session = SSHSession(
            host=conn["host"],
            port=conn["port"],
            username=conn["username"],
            password=conn.get("password", ""),
            key_file=conn.get("key_file", ""),
            passphrase=conn.get("passphrase", ""),
        )

        tab = SessionTab(session, conn)
        tab_name = conn.get("name") or f"{conn['username']}@{conn['host']}"
        index = self.tab_widget.addTab(tab, tab_name)
        self.tab_widget.setCurrentIndex(index)
        self._sessions[index] = tab

        session.connected.connect(
            lambda: self.statusBar().showMessage(f"已连接: {conn['host']}")
        )
        session.disconnected.connect(
            lambda reason: self._on_disconnected(index, reason)
        )
        session.error_occurred.connect(
            lambda err: self._on_error(index, err)
        )

        self.statusBar().showMessage(f"正在连接 {conn['host']}:{conn['port']}...")
        session.connect()

    def _on_disconnected(self, index: int, reason: str):
        self.statusBar().showMessage(f"断开连接: {reason}")
        tab = self._sessions.get(index)
        if tab:
            tab.terminal.append_data(f"\r\n\033[31m--- {reason} ---\033[0m\r\n".encode())

    def _on_error(self, index: int, error: str):
        self.statusBar().showMessage(f"连接失败: {error}")
        tab = self._sessions.get(index)
        if tab:
            tab.terminal.append_data(
                f"\r\n\033[31m连接失败: {error}\033[0m\r\n".encode()
            )

    def _toggle_sftp(self):
        tab = self._current_tab()
        if tab and tab.session.is_connected:
            tab.toggle_sftp()

    def _close_tab(self, index: int):
        tab = self._sessions.pop(index, None)
        if tab:
            tab.close_session()
        self.tab_widget.removeTab(index)
        # 重建 index 映射
        new_sessions = {}
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, SessionTab):
                new_sessions[i] = widget
        self._sessions = new_sessions

    def _current_tab(self) -> SessionTab | None:
        w = self.tab_widget.currentWidget()
        return w if isinstance(w, SessionTab) else None

    # ── 系统托盘 ──────────────────────────────────────────

    def _build_tray(self):
        self.tray_icon = QSystemTrayIcon(self._app_icon, self)
        self.tray_icon.setToolTip("PySSH Client")

        tray_menu = QMenu()
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self._show_from_tray)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        quit_action = QAction("退出(&X)", self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _show_from_tray(self):
        self.showMaximized()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _quit_app(self):
        """真正退出：关闭所有会话并退出程序。"""
        for tab in self._sessions.values():
            tab.close_session()
        self.tray_icon.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        """拦截关闭事件，最小化到系统托盘而非退出。"""
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "PySSH Client",
            "程序已最小化到系统托盘，双击图标恢复窗口。",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )


def main():
    # Windows 下设置 AppUserModelID，让任务栏显示自定义图标而非 Python 图标
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PySSH.Client")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
