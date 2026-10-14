"""下載隨附的 ffmpeg（BtbN 的 LGPL shared 版，固定一個版本），檢查 SHA-256 後解開到 vendor\\ffmpeg。

用法（專案資料夾）：.venv\\Scripts\\python.exe scripts\\下載ffmpeg.py

- 版本固定在下面的 網址／SHA256（BtbN 每月最後一天的 autobuild，長期保留）。要換版本：改這三個常數，SHA-256 抄 GitHub 發布頁該檔案的 sha256。
- SHA-256 不符就刪掉下載的檔案、不解開、結束碼 1（不會用到來路不明的 ffmpeg）。
- 壓縮檔留在 vendor\\下載（備份：BtbN 的每日版只留約兩週；只有每月最後一天的版本長期保留，所以釘月底版）。
  vendor\\ 整個在 .gitignore，二進位檔不進 git。
- 同時下載這一版 FFmpeg 的原始碼（LGPL 要提供對應原始碼）到 vendor\\原始碼\\FFmpeg-<提交>.zip，發布時一起上傳到發布頁。
  原始碼是 GitHub 依提交產生的壓縮檔，SHA-256 也釘住（2026-10-14 兩次下載相同）；不符一樣刪掉、結束碼 1。
- 程式找 ffmpeg 的順序（app_paths.ffmpeg位置）：vendor\\ffmpeg\\bin\\ffmpeg.exe（開發）／_internal\\ffmpeg\\bin（打包版）→ 系統上的。
"""
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app_paths
import external

# 2026-09-30 的 BtbN autobuild（每月最後一天的版本長期保留；每日版約兩週就刪）：FFmpeg n9.0.2-17-g2a571b6068（release/9.0 分支）、win64、LGPL、shared
版本 = "n9.0.2-17-g2a571b6068"
檔名 = f"ffmpeg-{版本}-win64-lgpl-shared-9.0.zip"
網址 = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-30-13-08/{檔名}"
SHA256 = "7157177b8a6cb2174c1650ba8c71b363f2c78cba5330f88c4c02cf5b2b880646"
# 這個建置對應的 FFmpeg 原始碼（版本字串 n9.0.2-17-g2a571b6068 的 g 後面就是提交；RELEASE 檔寫 9.0.2）
原始碼提交 = "2a571b606854520cf89804d8030c8b328e621689"
原始碼網址 = f"https://github.com/FFmpeg/FFmpeg/archive/{原始碼提交}.zip"
原始碼檔名 = f"FFmpeg-{原始碼提交}.zip"
原始碼SHA256 = "25c3b714ebbb3d43ffd2a5126d8ce34217dade0d8cd4829c618666e3e19b3858"


class 雜湊不符(Exception):
    pass


def 算雜湊(路徑):
    h = hashlib.sha256()
    with open(路徑, "rb") as f:
        for 塊 in iter(lambda: f.read(1024 * 1024), b""):
            h.update(塊)
    return h.hexdigest()


def 下載(網址, 目的, 開網址=urllib.request.urlopen):
    """下載到 目的（先寫 .part，完成才改名）。"""
    暫存 = 目的 + ".part"
    with 開網址(網址, timeout=60) as r, open(暫存, "wb") as f:      # 固定的 https 網址
        shutil.copyfileobj(r, f, 1024 * 1024)
    os.replace(暫存, 目的)


def 確認雜湊(路徑, 期望):
    """不符就刪掉檔案並丟出 雜湊不符。"""
    實際 = 算雜湊(路徑)
    if 實際.lower() != 期望.lower():
        os.remove(路徑)
        raise 雜湊不符(f"SHA-256 不符，已刪除下載的檔案，不使用。\n  期望：{期望}\n  實際：{實際}")


def 解開(壓縮檔, 目的資料夾):
    """壓縮檔裡唯一的頂層資料夾的內容 → 目的資料夾（整個換掉）。先解到旁邊的暫存資料夾，成功才換。"""
    暫存 = 目的資料夾 + ".解開中"
    shutil.rmtree(暫存, ignore_errors=True)
    with zipfile.ZipFile(壓縮檔) as z:
        for 名 in z.namelist():          # 不准跑出暫存資料夾（../、絕對路徑）
            目標 = os.path.realpath(os.path.join(暫存, 名))
            if not 目標.startswith(os.path.realpath(暫存) + os.sep):
                raise ValueError(f"壓縮檔裡有不安全的路徑：{名}")
        z.extractall(暫存)
    內容們 = os.listdir(暫存)
    來源 = os.path.join(暫存, 內容們[0]) if len(內容們) == 1 and os.path.isdir(os.path.join(暫存, 內容們[0])) else 暫存
    if not os.path.isfile(os.path.join(來源, "bin", "ffmpeg.exe")):
        shutil.rmtree(暫存, ignore_errors=True)
        raise ValueError("壓縮檔裡找不到 bin\\ffmpeg.exe")
    shutil.rmtree(目的資料夾, ignore_errors=True)
    shutil.move(來源, 目的資料夾)
    shutil.rmtree(暫存, ignore_errors=True)


def 準備(網址=網址, 檔名=檔名, 期望=SHA256, 目的資料夾=None, 開網址=urllib.request.urlopen, 進度=print):
    """下載（已有且雜湊對就不重下）→ 檢查 SHA-256 → 解開。回傳 ffmpeg.exe 路徑。"""
    目的資料夾 = 目的資料夾 or app_paths.隨附ffmpeg資料夾()
    下載夾 = os.path.join(os.path.dirname(目的資料夾), "下載")
    os.makedirs(下載夾, exist_ok=True)
    壓縮檔 = os.path.join(下載夾, 檔名)
    if os.path.isfile(壓縮檔) and 算雜湊(壓縮檔).lower() == 期望.lower():
        進度(f"已經下載過：{壓縮檔}")
    else:
        進度(f"下載：{網址}")
        下載(網址, 壓縮檔, 開網址)
    確認雜湊(壓縮檔, 期望)
    進度(f"SHA-256 正確：{期望}")
    解開(壓縮檔, 目的資料夾)
    with open(os.path.join(目的資料夾, "來源.txt"), "w", encoding="utf-8") as f:
        f.write(f"版本：{版本}\n網址：{網址}\nSHA-256：{期望}\n授權：LGPL（見 LICENSE.txt）\n")
    exe = os.path.join(目的資料夾, "bin", "ffmpeg.exe")
    進度(f"完成：{exe}")
    return exe


def 備份原始碼(目的資料夾=None, 開網址=urllib.request.urlopen, 進度=print):
    """FFmpeg 原始碼壓縮檔 → vendor\\原始碼（已有且雜湊對就不重下）。回傳路徑。"""
    目的資料夾 = 目的資料夾 or os.path.join(os.path.dirname(app_paths.隨附ffmpeg資料夾()), "原始碼")
    os.makedirs(目的資料夾, exist_ok=True)
    路徑 = os.path.join(目的資料夾, 原始碼檔名)
    if os.path.isfile(路徑) and 算雜湊(路徑).lower() == 原始碼SHA256:
        進度(f"原始碼已經備份過：{路徑}")
    else:
        進度(f"下載原始碼：{原始碼網址}")
        下載(原始碼網址, 路徑, 開網址)
    確認雜湊(路徑, 原始碼SHA256)
    進度(f"原始碼 SHA-256 正確：{路徑}")
    return 路徑


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    try:
        exe = 準備()
        備份原始碼()
    except 雜湊不符 as e:
        print(f"失敗：{e}", file=sys.stderr)
        return 1
    r = external.執行([exe, "-version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    print((r.stdout or "").splitlines()[0] if r.stdout else f"ffmpeg -version 失敗（結束碼 {r.returncode}）")
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
