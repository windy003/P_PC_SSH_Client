"""SSH 连接管理 —— 在后台线程中运行 paramiko 会话。"""

import threading
import time
import paramiko
from PyQt6.QtCore import QObject, pyqtSignal


class SSHSession(QObject):
    """封装一个 SSH 连接和交互式 shell 通道。"""

    # 收到远程输出
    data_received = pyqtSignal(bytes)
    # 连接成功
    connected = pyqtSignal()
    # 连接断开
    disconnected = pyqtSignal(str)  # reason
    # 连接失败
    error_occurred = pyqtSignal(str)

    def __init__(self, host: str, port: int, username: str,
                 password: str = "", key_file: str = "", passphrase: str = ""):
        super().__init__()
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_file = key_file
        self.passphrase = passphrase

        self._client: paramiko.SSHClient | None = None
        self._channel: paramiko.Channel | None = None
        self._reader_thread: threading.Thread | None = None
        self._running = False

    # ── 连接 ──────────────────────────────────────────────

    def connect(self):
        """在后台线程中建立连接。"""
        t = threading.Thread(target=self._do_connect, daemon=True)
        t.start()

    def _do_connect(self):
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs: dict = {
                "hostname": self.host,
                "port": self.port,
                "username": self.username,
                "timeout": 10,
                "allow_agent": False,
                "look_for_keys": False,
            }

            if self.key_file:
                pkey = paramiko.RSAKey.from_private_key_file(
                    self.key_file,
                    password=self.passphrase or None,
                )
                connect_kwargs["pkey"] = pkey
            else:
                connect_kwargs["password"] = self.password

            client.connect(**connect_kwargs)

            channel = client.invoke_shell(term="xterm-256color", width=120, height=40)
            channel.settimeout(0.1)

            self._client = client
            self._channel = channel
            self._running = True
            self.connected.emit()

            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

        except Exception as e:
            self.error_occurred.emit(str(e))

    # ── 读取循环 ──────────────────────────────────────────

    def _read_loop(self):
        while self._running and self._channel and not self._channel.closed:
            try:
                data = self._channel.recv(4096)
                if data:
                    self.data_received.emit(data)
                else:
                    break
            except TimeoutError:
                continue
            except OSError:
                break

        self._running = False
        self.disconnected.emit("连接已关闭")

    # ── 发送数据 ──────────────────────────────────────────

    def send(self, data: bytes):
        if self._channel and not self._channel.closed:
            self._channel.sendall(data)

    # ── 调整终端大小 ──────────────────────────────────────

    def resize(self, cols: int, rows: int):
        if self._channel and not self._channel.closed:
            self._channel.resize_pty(width=cols, height=rows)

    # ── 断开连接 ──────────────────────────────────────────

    def close(self):
        self._running = False
        if self._channel:
            try:
                self._channel.close()
            except Exception:
                pass
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass

    # ── SFTP ──────────────────────────────────────────────

    def open_sftp(self) -> paramiko.SFTPClient | None:
        if self._client:
            return self._client.open_sftp()
        return None

    @property
    def is_connected(self) -> bool:
        return self._running and self._channel is not None and not self._channel.closed
