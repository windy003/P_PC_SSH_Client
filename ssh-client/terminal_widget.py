"""基于 QTextEdit 的终端模拟器组件，支持 ANSI 颜色和键盘输入。"""

import re
from PyQt6.QtWidgets import QTextEdit, QApplication
from PyQt6.QtGui import (
    QTextCursor, QTextCharFormat, QColor, QFont, QKeyEvent, QPalette,
)
from PyQt6.QtCore import Qt, pyqtSignal

# 基本 ANSI 16 色 —— 白色背景，全部使用黑色文字
ANSI_COLORS = {
    0: "#000000", 1: "#000000", 2: "#000000", 3: "#000000",
    4: "#000000", 5: "#000000", 6: "#000000", 7: "#000000",
    8: "#000000", 9: "#000000", 10: "#000000", 11: "#000000",
    12: "#000000", 13: "#000000", 14: "#000000", 15: "#000000",
}

# CSI 序列正则 —— 匹配 ESC[ ... 终结字符（包括 DEC Private Mode 如 ?25h）
_CSI_RE = re.compile(r"\x1b\[([?]?)([0-9;]*)([A-Za-z@`])")
# OSC 序列 (窗口标题等)
_OSC_RE = re.compile(r"\x1b\][^\x07]*\x07|\x1b\][^\x1b]*\x1b\\")
# 其它单字符转义
_ESC_OTHER = re.compile(r"\x1b[()][0-9A-Za-z]|\x1b[>=<7-9cDEHMNOZ]")


class TerminalWidget(QTextEdit):
    """终端模拟器组件。"""

    input_sent = pyqtSignal(bytes)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 外观
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setStyleSheet(
            "QTextEdit { background-color: #ffffff; color: #333333; "
            "border: none; padding: 4px; }"
        )
        self.setAcceptRichText(False)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        # 光标样式
        self.setCursorWidth(8)

        # 终端光标位置（文档中的绝对位置）
        self._cursor_pos = 0

        # 屏幕区域：追踪当前"屏幕"起始行号（block number）
        self._screen_top_block = 0
        self._term_rows = 40   # 和 SSH channel 的 pty height 一致
        self._term_cols = 120

        # 当前格式状态
        self._fg: str | None = None
        self._bg: str | None = None
        self._bold = False
        self._italic = False
        self._underline = False

        # 标题
        self._title = ""

    # ── 公共接口 ──────────────────────────────────────────

    def append_data(self, data: bytes):
        """接收远程输出并渲染到终端。"""
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = data.decode("latin-1", errors="replace")
        # 确保光标位置不超出文档长度（防止鼠标点击等导致偏移）
        doc_len = self.document().characterCount() - 1
        if self._cursor_pos > doc_len:
            self._cursor_pos = max(doc_len, 0)
        self._process_text(text)

    # ── ANSI 解析与渲染 ──────────────────────────────────

    def _process_text(self, text: str):
        # 移除 OSC 和其它不处理的转义
        text = _OSC_RE.sub("", text)
        text = _ESC_OTHER.sub("", text)

        cursor = self.textCursor()
        cursor.setPosition(self._cursor_pos)

        # 动态更新屏幕起始行：屏幕始终对应文档最后 _term_rows 行
        total_blocks = self.document().blockCount()
        self._screen_top_block = max(0, total_blocks - self._term_rows)

        pos = 0
        for m in _CSI_RE.finditer(text):
            # 先输出 CSI 之前的普通文本
            start = m.start()
            if start > pos:
                segment = text[pos:start]
                self._write_plain(cursor, segment)
            pos = m.end()

            private = m.group(1)   # "?" 或 ""
            params_str = m.group(2)
            cmd = m.group(3)
            params = [int(p) if p else 0 for p in params_str.split(";")] if params_str else [0]

            # DEC Private Mode 序列 (?25h, ?25l, ?1049h 等) —— 直接忽略
            if private == "?":
                continue

            if cmd == "m":
                self._apply_sgr(params)
            elif cmd == "H" or cmd == "f":
                # 光标定位 ESC[row;colH —— 相对于屏幕顶部
                row = params[0] if len(params) >= 1 else 1
                col = params[1] if len(params) >= 2 else 1
                self._ensure_screen_lines(cursor)
                target_block = self._screen_top_block + row - 1
                # 确保目标行存在
                doc = self.document()
                while doc.blockCount() <= target_block:
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    cursor.insertText("\n")
                # 跳转到目标行
                block = doc.findBlockByNumber(target_block)
                if block.isValid():
                    cursor.setPosition(block.position())
                    # 移动到指定列
                    for _ in range(col - 1):
                        if not cursor.atBlockEnd():
                            cursor.movePosition(QTextCursor.MoveOperation.Right)
                        else:
                            cursor.insertText(" ")
            elif cmd == "A":
                # 光标上移
                n = params[0] or 1
                for _ in range(n):
                    cursor.movePosition(QTextCursor.MoveOperation.Up)
            elif cmd == "B":
                # 光标下移
                n = params[0] or 1
                for _ in range(n):
                    cursor.movePosition(QTextCursor.MoveOperation.Down)
            elif cmd == "C":
                # 光标右移
                n = params[0] or 1
                for _ in range(n):
                    cursor.movePosition(QTextCursor.MoveOperation.Right)
            elif cmd == "D":
                # 光标左移
                n = params[0] or 1
                for _ in range(n):
                    cursor.movePosition(QTextCursor.MoveOperation.Left)
            elif cmd == "G":
                # 光标水平绝对定位 ESC[nG —— 移到当前行第 n 列
                col = params[0] or 1
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                for _ in range(col - 1):
                    if not cursor.atBlockEnd():
                        cursor.movePosition(QTextCursor.MoveOperation.Right)
            elif cmd == "d":
                # 光标垂直绝对定位 ESC[nd —— 移到第 n 行（相对屏幕）
                row = params[0] or 1
                target_block = self._screen_top_block + row - 1
                doc = self.document()
                block = doc.findBlockByNumber(target_block)
                if block.isValid():
                    col_offset = cursor.positionInBlock()
                    cursor.setPosition(block.position())
                    for _ in range(col_offset):
                        if not cursor.atBlockEnd():
                            cursor.movePosition(QTextCursor.MoveOperation.Right)
            elif cmd == "E":
                # 光标下移 n 行并移到行首
                n = params[0] or 1
                for _ in range(n):
                    cursor.movePosition(QTextCursor.MoveOperation.Down)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            elif cmd == "F":
                # 光标上移 n 行并移到行首
                n = params[0] or 1
                for _ in range(n):
                    cursor.movePosition(QTextCursor.MoveOperation.Up)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            elif cmd == "J":
                if params[0] == 0:
                    # 清除光标到屏幕末尾
                    cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                elif params[0] == 1:
                    # 清除屏幕顶部到光标
                    save_pos = cursor.position()
                    self._move_to_screen_top(cursor)
                    cursor.setPosition(save_pos, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                elif params[0] == 2:
                    # 清除整个屏幕区域 —— 更新屏幕起始行而非清空文档
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    self._screen_top_block = cursor.blockNumber() + 1
            elif cmd == "K":
                if params[0] == 0:
                    # 清除光标到行尾
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                elif params[0] == 1:
                    # 清除行首到光标
                    pos_save = cursor.position()
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                elif params[0] == 2:
                    # 清除整行
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
            elif cmd == "P":
                # 删除光标处的 n 个字符
                n = params[0] or 1
                for _ in range(n):
                    if not cursor.atBlockEnd():
                        cursor.movePosition(
                            QTextCursor.MoveOperation.Right,
                            QTextCursor.MoveMode.KeepAnchor,
                        )
                cursor.removeSelectedText()
            elif cmd == "X":
                # 擦除光标处的 n 个字符（替换为空格）
                n = params[0] or 1
                save_pos = cursor.position()
                for _ in range(n):
                    if not cursor.atBlockEnd():
                        cursor.movePosition(
                            QTextCursor.MoveOperation.Right,
                            QTextCursor.MoveMode.KeepAnchor,
                        )
                cursor.insertText(" " * n, self._current_format())
                cursor.setPosition(save_pos)
            elif cmd == "@":
                # 在光标处插入 n 个空格
                n = params[0] or 1
                cursor.insertText(" " * n, self._current_format())
                cursor.movePosition(QTextCursor.MoveOperation.Left, n=n)

        # 剩余文本
        if pos < len(text):
            self._write_plain(cursor, text[pos:])

        # 保存终端光标位置
        self._cursor_pos = cursor.position()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _write_plain(self, cursor: QTextCursor, text: str):
        """写入纯文本，处理特殊字符。"""
        fmt = self._current_format()

        for ch in text:
            if ch == "\r":
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            elif ch == "\n":
                if cursor.atBlockEnd():
                    cursor.insertText("\n", fmt)
                else:
                    if not cursor.movePosition(QTextCursor.MoveOperation.Down):
                        # 在最后一行且不在行尾时，需要创建新行
                        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                        cursor.insertText("\n", fmt)
                    else:
                        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                # 如果超出屏幕底部，滚动屏幕
                current_block = cursor.blockNumber()
                if current_block >= self._screen_top_block + self._term_rows:
                    self._screen_top_block = current_block - self._term_rows + 1
            elif ch == "\x08":  # backspace
                cursor.movePosition(QTextCursor.MoveOperation.Left)
            elif ch == "\x7f":  # DEL
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                cursor.removeSelectedText()
            elif ch == "\x07":  # bell
                QApplication.beep()
            elif ch == "\t":
                cursor.insertText("    ", fmt)
            elif ord(ch) >= 32 or ch in ("\n", "\r"):
                # 覆写模式：如果不在行末则覆盖字符
                if not cursor.atBlockEnd():
                    cursor.movePosition(
                        QTextCursor.MoveOperation.Right,
                        QTextCursor.MoveMode.KeepAnchor,
                    )
                cursor.insertText(ch, fmt)

    def _ensure_screen_lines(self, cursor: QTextCursor):
        """确保屏幕区域有足够的行。"""
        doc = self.document()
        needed = self._screen_top_block + self._term_rows
        while doc.blockCount() < needed:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText("\n")

    def _move_to_screen_top(self, cursor: QTextCursor):
        """将光标移到屏幕顶部。"""
        doc = self.document()
        block = doc.findBlockByNumber(self._screen_top_block)
        if block.isValid():
            cursor.setPosition(block.position())

    def _current_format(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self._fg or "#333333"))
        if self._bg:
            fmt.setBackground(QColor(self._bg))
        if self._bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if self._italic:
            fmt.setFontItalic(True)
        if self._underline:
            fmt.setFontUnderline(True)
        return fmt

    def _apply_sgr(self, params: list[int]):
        """应用 SGR (Select Graphic Rendition) 参数。"""
        i = 0
        while i < len(params):
            p = params[i]
            if p == 0:
                self._fg = None
                self._bg = None
                self._bold = False
                self._italic = False
                self._underline = False
            elif p == 1:
                self._bold = True
            elif p == 3:
                self._italic = True
            elif p == 4:
                self._underline = True
            elif p == 22:
                self._bold = False
            elif p == 23:
                self._italic = False
            elif p == 24:
                self._underline = False
            elif 30 <= p <= 37:
                self._fg = ANSI_COLORS[p - 30]
            elif p == 38:
                # 扩展前景色
                if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                    self._fg = self._color_256(params[i + 2])
                    i += 2
                elif i + 1 < len(params) and params[i + 1] == 2 and i + 4 < len(params):
                    r, g, b = params[i + 2], params[i + 3], params[i + 4]
                    self._fg = f"#{r:02x}{g:02x}{b:02x}"
                    i += 4
            elif p == 39:
                self._fg = None
            elif 40 <= p <= 47:
                self._bg = ANSI_COLORS[p - 40]
            elif p == 48:
                if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                    self._bg = self._color_256(params[i + 2])
                    i += 2
                elif i + 1 < len(params) and params[i + 1] == 2 and i + 4 < len(params):
                    r, g, b = params[i + 2], params[i + 3], params[i + 4]
                    self._bg = f"#{r:02x}{g:02x}{b:02x}"
                    i += 4
            elif p == 49:
                self._bg = None
            elif 90 <= p <= 97:
                self._fg = ANSI_COLORS[p - 90 + 8]
            elif 100 <= p <= 107:
                self._bg = ANSI_COLORS[p - 100 + 8]
            i += 1

    @staticmethod
    def _color_256(n: int) -> str:
        """将 256 色索引转换为 hex 颜色。"""
        if n < 16:
            return ANSI_COLORS.get(n, "#333333")
        if n < 232:
            n -= 16
            r = (n // 36) * 51
            g = ((n % 36) // 6) * 51
            b = (n % 6) * 51
            return f"#{r:02x}{g:02x}{b:02x}"
        # 灰度
        gray = 8 + (n - 232) * 10
        return f"#{gray:02x}{gray:02x}{gray:02x}"

    # ── 键盘输入 ──────────────────────────────────────────

    def keyPressEvent(self, e: QKeyEvent):
        key = e.key()
        modifiers = e.modifiers()

        # Ctrl+C / Ctrl+V 等
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_C:
                if self.textCursor().hasSelection():
                    self.copy()
                    return
                # 光标跳到文档底部，新建一行
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText("\n")
                self._cursor_pos = cursor.position()
                self._screen_top_block = max(cursor.blockNumber() - self._term_rows + 1, 0)
                self.setTextCursor(cursor)
                self.ensureCursorVisible()
                self.input_sent.emit(b"\x03")
                return
            elif key == Qt.Key.Key_V:
                clipboard = QApplication.clipboard()
                if clipboard:
                    text = clipboard.text()
                    if text:
                        self.input_sent.emit(text.encode("utf-8"))
                return
            elif key == Qt.Key.Key_A:
                self.input_sent.emit(b"\x01")
                return
            elif key == Qt.Key.Key_E:
                self.input_sent.emit(b"\x05")
                return
            elif key == Qt.Key.Key_D:
                self.input_sent.emit(b"\x04")
                return
            elif key == Qt.Key.Key_L:
                self.input_sent.emit(b"\x0c")
                return
            elif key == Qt.Key.Key_Z:
                self.input_sent.emit(b"\x1a")
                return

        # 特殊键映射
        key_map = {
            Qt.Key.Key_Return: b"\r",
            Qt.Key.Key_Enter: b"\r",
            Qt.Key.Key_Backspace: b"\x7f",
            Qt.Key.Key_Delete: b"\x1b[3~",
            Qt.Key.Key_Escape: b"\x1b",
            Qt.Key.Key_Tab: b"\t",
            Qt.Key.Key_Up: b"\x1b[A",
            Qt.Key.Key_Down: b"\x1b[B",
            Qt.Key.Key_Right: b"\x1b[C",
            Qt.Key.Key_Left: b"\x1b[D",
            Qt.Key.Key_Home: b"\x1b[H",
            Qt.Key.Key_End: b"\x1b[F",
            Qt.Key.Key_PageUp: b"\x1b[5~",
            Qt.Key.Key_PageDown: b"\x1b[6~",
            Qt.Key.Key_Insert: b"\x1b[2~",
            Qt.Key.Key_F1: b"\x1bOP",
            Qt.Key.Key_F2: b"\x1bOQ",
            Qt.Key.Key_F3: b"\x1bOR",
            Qt.Key.Key_F4: b"\x1bOS",
            Qt.Key.Key_F5: b"\x1b[15~",
            Qt.Key.Key_F6: b"\x1b[17~",
            Qt.Key.Key_F7: b"\x1b[18~",
            Qt.Key.Key_F8: b"\x1b[19~",
            Qt.Key.Key_F9: b"\x1b[20~",
            Qt.Key.Key_F10: b"\x1b[21~",
            Qt.Key.Key_F11: b"\x1b[23~",
            Qt.Key.Key_F12: b"\x1b[24~",
        }

        if key in key_map:
            self.input_sent.emit(key_map[key])
            e.accept()
            return

        # 普通字符
        text = e.text()
        if text:
            self.input_sent.emit(text.encode("utf-8"))

        # 始终接受事件，阻止 QTextEdit 自行编辑
        e.accept()

    # 鼠标操作：允许选择文本，但松开后恢复终端光标位置
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        # 如果没有选中文本，恢复光标到终端位置
        if not self.textCursor().hasSelection():
            cursor = self.textCursor()
            cursor.setPosition(self._cursor_pos)
            self.setTextCursor(cursor)

    def mouseDoubleClickEvent(self, e):
        super().mouseDoubleClickEvent(e)

    def insertFromMimeData(self, source):
        """粘贴时发送到远程。"""
        text = source.text()
        if text:
            self.input_sent.emit(text.encode("utf-8"))
