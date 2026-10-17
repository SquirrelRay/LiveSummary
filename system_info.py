# 系統版本（Windows、Python）：當機紀錄與回報問題的診斷資訊共用這一份。
# 只用標準函式庫；只回傳版本字串，不含電腦名稱、使用者名稱或任何路徑。
import platform


def 平台字():
    """作業系統與版本，例如 Windows-11-10.0.26200-SP0。"""
    return platform.platform()


def Python版本():
    """例如 3.13.1。"""
    return platform.python_version()
