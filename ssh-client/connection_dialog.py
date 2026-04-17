"""新建/编辑 SSH 连接的对话框。"""

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout,
    QVBoxLayout, QSpinBox, QFileDialog, QComboBox, QLabel,
)
from PyQt6.QtCore import Qt


class ConnectionDialog(QDialog):
    """SSH 连接配置对话框。"""

    def __init__(self, parent=None, data: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("编辑连接" if data else "新建连接")
        self.setMinimumWidth(420)
        self._build_ui()
        if data:
            self._fill(data)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("My Server")
        form.addRow("名称:", self.name_edit)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.1.100")
        form.addRow("主机:", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        form.addRow("端口:", self.port_spin)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("root")
        form.addRow("用户名:", self.user_edit)

        self.auth_combo = QComboBox()
        self.auth_combo.addItems(["密码", "密钥文件"])
        self.auth_combo.currentIndexChanged.connect(self._on_auth_changed)
        form.addRow("认证方式:", self.auth_combo)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("密码:", self.password_edit)

        # 密钥文件行
        key_row = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("~/.ssh/id_rsa")
        key_row.addWidget(self.key_edit)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_key)
        key_row.addWidget(browse_btn)
        form.addRow("密钥文件:", key_row)

        self.passphrase_edit = QLineEdit()
        self.passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.passphrase_edit.setPlaceholderText("(可选)")
        form.addRow("密钥密码:", self.passphrase_edit)

        layout.addLayout(form)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        ok_btn = QPushButton("确定")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        # 初始状态
        self._on_auth_changed(0)

    def _on_auth_changed(self, index: int):
        is_key = index == 1
        self.password_edit.setVisible(not is_key)
        self.key_edit.setVisible(is_key)
        self.passphrase_edit.setVisible(is_key)
        # 找到对应的 label 并同步显示/隐藏
        form = self.layout().itemAt(0).layout()
        if form:
            form.labelForField(self.password_edit).setVisible(not is_key)
            # key_edit 的 label 其实是 key_row 的
            for i in range(form.rowCount()):
                item = form.itemAt(i, QFormLayout.ItemRole.FieldRole)
                if item and item.layout():
                    # 这是 key_row
                    label = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
                    if label and label.widget():
                        label.widget().setVisible(is_key)
            form.labelForField(self.passphrase_edit).setVisible(is_key)

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择密钥文件", "", "所有文件 (*)"
        )
        if path:
            self.key_edit.setText(path)

    def _fill(self, data: dict):
        self.name_edit.setText(data.get("name", ""))
        self.host_edit.setText(data.get("host", ""))
        self.port_spin.setValue(data.get("port", 22))
        self.user_edit.setText(data.get("username", ""))
        if data.get("key_file"):
            self.auth_combo.setCurrentIndex(1)
            self.key_edit.setText(data.get("key_file", ""))
            self.passphrase_edit.setText(data.get("passphrase", ""))
        else:
            self.auth_combo.setCurrentIndex(0)
            self.password_edit.setText(data.get("password", ""))

    def get_data(self) -> dict:
        data = {
            "name": self.name_edit.text().strip() or self.host_edit.text().strip(),
            "host": self.host_edit.text().strip(),
            "port": self.port_spin.value(),
            "username": self.user_edit.text().strip(),
        }
        if self.auth_combo.currentIndex() == 1:
            data["key_file"] = self.key_edit.text().strip()
            data["passphrase"] = self.passphrase_edit.text()
            data["password"] = ""
        else:
            data["password"] = self.password_edit.text()
            data["key_file"] = ""
            data["passphrase"] = ""
        return data
