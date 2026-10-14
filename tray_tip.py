# 系統匣圖示說明：Windows 11 預設把新程式的系統匣圖示收進工作列右下角的「^」裡，使用者找不到膠囊以外的入口。
# 首次引導最後一頁、設定框都放同一張說明卡（圖示＋兩行字＋「打開工作列設定」按鈕）。
# 按鈕打開 Windows 設定的工作列頁（ms-settings:taskbar，Microsoft Learn「Launch the Windows Settings app」的 URI 表）。
import os

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

工作列設定網址 = "ms-settings:taskbar"
標題 = "讓系統匣圖示一直顯示"
說明 = "Windows 可能把本程式的圖示收進右下角的「^」裡。\n到工作列設定的「其他系統匣圖示」，把「直播摘要」打開。"
按鈕字 = "打開工作列設定"
打不開字 = "打不開設定，請手動到「設定 → 個人化 → 工作列」。"


def 打開工作列設定():
    """打開 Windows 設定的工作列頁；成功回傳 True。"""
    try:
        os.startfile(工作列設定網址)        # noqa: S606  固定的 Windows 設定 URI
        return True
    except OSError:
        return False


class 系統匣圖示(QWidget):
    """程式畫的線條圖示：工作列一角＋「^」，和首次引導的線條圖示同風格。"""

    def __init__(self, 大小=36, 顏色="#8b6cff"):
        super().__init__()
        self.顏色 = QColor(顏色)
        self.setFixedSize(大小, 大小)

    def paintEvent(self, e):
        s = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self.顏色, max(1.6, s / 24), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.1 * s, 0.56 * s, 0.8 * s, 0.26 * s), 0.05 * s, 0.05 * s)     # 工作列
        路 = QPainterPath(QPointF(0.62 * s, 0.75 * s))                                        # 工作列上的「^」
        路.lineTo(0.68 * s, 0.66 * s)
        路.lineTo(0.74 * s, 0.75 * s)
        p.drawPath(路)
        p.drawRoundedRect(QRectF(0.52 * s, 0.14 * s, 0.32 * s, 0.3 * s), 0.05 * s, 0.05 * s)     # 收在裡面的圖示
        p.drawEllipse(QPointF(0.68 * s, 0.29 * s), 0.06 * s, 0.06 * s)


class 系統匣說明卡(QFrame):
    """圖示＋標題＋兩行說明＋「打開工作列設定」按鈕。打不開時在卡片裡寫出手動路徑。"""
    開了 = Signal(bool)

    def __init__(self, 小標題=True):
        super().__init__()
        self.setObjectName("卡片")
        橫 = QHBoxLayout(self)
        橫.setContentsMargins(14, 12, 14, 12)
        橫.setSpacing(12)
        橫.addWidget(系統匣圖示(), 0, Qt.AlignTop)
        直 = QVBoxLayout()
        直.setSpacing(6)
        if 小標題:
            t = QLabel(標題)
            t.setStyleSheet("font-weight: 700; font-size: 13px;")
            直.addWidget(t)
        self.說明字 = QLabel(說明)
        self.說明字.setWordWrap(True)
        self.說明字.setStyleSheet("color: #8a91a5; font-size: 12px;")
        直.addWidget(self.說明字)
        self.按鈕 = QPushButton(按鈕字)
        self.按鈕.setCursor(Qt.PointingHandCursor)
        self.按鈕.clicked.connect(self.打開)
        直.addWidget(self.按鈕, 0, Qt.AlignLeft)
        橫.addLayout(直, 1)

    def 打開(self):
        好 = 打開工作列設定()
        if not 好:
            self.說明字.setText(說明 + "\n" + 打不開字)
        self.開了.emit(好)
        return 好
