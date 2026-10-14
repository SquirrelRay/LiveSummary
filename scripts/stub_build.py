# 編譯 LiveSummary.exe 啟動器（stub\Stub.cs）：用 Windows 內建的 .NET Framework csc.exe，不需要安裝任何東西。
# 為什麼有這支啟動器、做什麼，見 stub\Stub.cs 開頭與 docs\打包調查.md「第5步之一」。
# build_exe.py 用 編譯()；tests/test_啟動器.py（慢測試）也用它編出一支來真的跑。
import glob
import os
import sys

專案 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 專案)

import app_paths
import external
import version

原始碼 = os.path.join(專案, "stub", "Stub.cs")
主程式檔名 = "LiveSummaryApp.exe"         # 啟動器要找的真正主程式（LiveSummary.spec 的 EXE 名稱要和它一致）


def 找csc():
    """Windows 內建的 .NET Framework 4 C# 編譯器（Windows 10／11 都有）。找不到回傳 None。"""
    根 = os.environ.get("WINDIR", r"C:\Windows")
    for 資料夾 in ("Framework64", "Framework"):
        路徑們 = sorted(glob.glob(os.path.join(根, "Microsoft.NET", 資料夾, "v4.*", "csc.exe")))
        if 路徑們:
            return 路徑們[-1]
    return None


def _組件資訊():
    """版本資訊（右鍵 → 內容 → 詳細資料）：從 version.py 來。"""
    資 = version.檔案資訊("LiveSummary.exe")
    四段 = ".".join(str(x) for x in version.版本們())
    跳 = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')     
    return "\n".join([
        "using System.Reflection;",
        f'[assembly: AssemblyTitle("{跳(資["FileDescription"])}")]',
        f'[assembly: AssemblyProduct("{跳(資["ProductName"])}")]',
        f'[assembly: AssemblyCompany("{跳(資["CompanyName"])}")]',
        f'[assembly: AssemblyCopyright("{跳(資["LegalCopyright"])}")]',
        f'[assembly: AssemblyVersion("{四段}")]',
        f'[assembly: AssemblyFileVersion("{跳(資["FileVersion"])}")]',     # 詳細資料頁顯示的就是這串字（不補成四段）
        f'[assembly: AssemblyInformationalVersion("{跳(資["ProductVersion"])}")]',
        "",
    ])


def 編譯(輸出exe, 暫存資料夾, 圖示=None):
    """編出啟動器到 輸出exe。assets/icon.ico 存在就當作 exe 圖示。失敗丟 RuntimeError（訊息是白話）。"""
    csc = 找csc()
    if not csc:
        raise RuntimeError("找不到 Windows 內建的 C# 編譯器（%WINDIR% 底下的 Microsoft.NET/Framework64/v4.*/csc.exe）")
    os.makedirs(暫存資料夾, exist_ok=True)
    資訊檔 = os.path.join(暫存資料夾, "AssemblyInfo.cs")
    with open(資訊檔, "w", encoding="utf-8-sig") as f:
        f.write(_組件資訊())
    指令 = [csc, "/nologo", "/target:winexe", "/optimize+", "/codepage:65001", f"/out:{輸出exe}",
          "/reference:System.Windows.Forms.dll", "/reference:System.dll"]
    圖示 = 圖示 or os.path.join(專案, app_paths.圖示相對位置)
    if os.path.isfile(圖示):
        指令.append(f"/win32icon:{圖示}")
    指令 += [原始碼, 資訊檔]
    結果 = external.執行(指令, timeout=120, capture_output=True)
    if 結果.returncode != 0 or not os.path.isfile(輸出exe):
        輸出 = ((結果.stdout or b"") + (結果.stderr or b"")).decode("utf-8", "replace")
        raise RuntimeError("啟動器編譯失敗：\n" + 輸出[-1500:])
    return 輸出exe
