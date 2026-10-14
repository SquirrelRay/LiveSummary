# 第三方授權清單：打包時（scripts/build_exe.py）自動產生 dist\LiveSummary\licenses\。
#   licenses\第三方授權清單.txt   總表（名稱／版本／授權類型／全文檔名／說明）
#   licenses\<名稱>-<版本>.txt     每一項的授權全文（套件自己附的檔案原樣收進來）
# 涵蓋的東西怎麼找：
#   - Python 套件：PyInstaller 的建置紀錄（build\LiveSummary\PYZ-*.toc，純 Python 模組）＋ _internal 裡實際的檔案，
#     對回 .venv 裡每個套件的檔案清單（importlib.metadata），對到的才算有帶進去（開發用的 pytest、ruff 等不會出現）。
#   - Python 本身（標準函式庫、python313.dll 等）、PyInstaller 開機程式、隨附 ffmpeg：固定項目。
#   - 對不到任何套件的檔案列在總表最後「來源待確認的檔案」，並在打包時印出來（不猜它是誰的）。
# 這支只負責「收集與列出」，不判斷相容性；相容性與附帶義務的決定記在 docs\打包調查.md。
# 只用標準函式庫＋.venv 已有的套件；不連網。
import os
import re
import sys
from importlib import metadata

專案 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 專案)

總表檔名 = "第三方授權清單.txt"
資料夾名 = "licenses"

# 套件自己沒附授權全文時，用專案裡現成的標準全文（這些授權的全文每一份都一樣，不需要填版權人）
標準全文 = {
    "LGPL-3.0": os.path.join(專案, "vendor", "ffmpeg", "LICENSE.txt"),       # BtbN ffmpeg 附的 LGPL v3 全文
    "GPL-3.0": os.path.join(專案, "LICENSE"),
}
授權檔樣式 = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS|ThirdPartyNotices)", re.IGNORECASE)


def _正規(路徑):
    return os.path.normcase(os.path.normpath(路徑))


def _套件索引():
    """.venv 裡每個檔案 → 所屬套件（distribution）。"""
    索引 = {}
    for 套件 in metadata.distributions():
        for f in 套件.files or []:
            索引[_正規(str(套件.locate_file(f)))] = 套件
    return 索引


def _site():
    return next(p for p in sys.path if p.lower().endswith("site-packages"))


def 帶進去的檔案(輸出, 建置):
    """打包結果實際含有的來源檔（絕對路徑）：PYZ 裡的純 Python 模組＋ _internal 裡的檔案（對應回 site-packages）。"""
    來源 = set()
    樣式 = re.compile(r"'([A-Za-z]:\\\\[^']+)'")
    for 名 in os.listdir(建置):
        if 名.startswith("PYZ-") and 名.endswith(".toc"):
            with open(os.path.join(建置, 名), encoding="utf-8") as f:
                for m in 樣式.finditer(f.read()):
                    來源.add(m.group(1).replace("\\\\", "\\"))
    內部 = os.path.join(輸出, "_internal")
    site = _site()
    磁碟 = []
    for 路, _, 檔們 in os.walk(內部):
        for 檔 in 檔們:
            相對 = os.path.relpath(os.path.join(路, 檔), 內部)
            磁碟.append(相對)
            來源.add(os.path.join(site, 相對))
    return 來源, 磁碟


def _授權類型(套件):
    md = 套件.metadata
    類型 = (md.get("License-Expression") or "").strip()
    if not 類型:
        字 = (md.get("License") or "").strip()
        if 字 and "\n" not in 字 and len(字) <= 60:
            類型 = 字
    分類 = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    if not 類型 and 分類:
        類型 = " / ".join(分類)
    return 類型 or "（套件沒有寫明）"


def _授權全文們(套件):
    全文 = []
    for f in 套件.files or []:
        名 = str(f).replace("\\", "/")
        檔名 = 名.rsplit("/", 1)[-1]
        if not 授權檔樣式.search(檔名) or 名.endswith((".py", ".pyc", ".pyi")) or "/_vendor/" in 名:
            continue
        if ".dist-info/" in 名 or 名.count("/") == 1:        # dist-info 裡的、或套件最上層的（onnxruntime 放在 onnxruntime\LICENSE）
            路徑 = str(套件.locate_file(f))
            if os.path.isfile(路徑):
                with open(路徑, encoding="utf-8", errors="replace") as h:
                    全文.append((名.rsplit("/", 1)[-1], h.read()))
    return 全文


def _讀(路徑):
    with open(路徑, encoding="utf-8", errors="replace") as f:
        return f.read()


def 收集(輸出, 建置):
    """回傳 (項目們, 對不到的檔案們)。項目：dict(名稱, 版本, 授權, 全文們[(標題, 文字)], 說明)。"""
    索引 = _套件索引()
    來源, 磁碟 = 帶進去的檔案(輸出, 建置)
    python根 = _正規(sys.base_prefix)
    用到 = {}
    對到的磁碟檔 = set()
    site = _site()
    for 路徑 in 來源:
        套件 = 索引.get(_正規(路徑))
        if 套件 is not None:
            用到.setdefault(套件.metadata["Name"], 套件)
            if _正規(路徑).startswith(_正規(site)):
                對到的磁碟檔.add(_正規(os.path.relpath(路徑, site)))
    項目們 = []

    # ---- 固定項目 ----
    項目們.append({
        "名稱": "Python", "版本": sys.version.split()[0], "授權": "PSF-2.0（另含 OpenSSL、libffi、SQLite、zlib 等的授權，見全文）",
        "全文們": [("LICENSE.txt", _讀(os.path.join(sys.base_prefix, "LICENSE.txt")))],
        "說明": "Python 直譯器與標準函式庫（python313.dll、*.pyd、libcrypto／libssl、sqlite3.dll、libffi、vcruntime140*.dll）"})
    import PyInstaller
    pyi = metadata.distribution("pyinstaller")
    項目們.append({
        "名稱": "PyInstaller（開機程式與執行期模組）", "版本": PyInstaller.__version__,
        "授權": "GPL-2.0-or-later，附開機程式例外（bootloader exception）",
        "全文們": _授權全文們(pyi), "說明": "LiveSummary.exe、helper.exe 裡的開機程式與 _internal\\base_library.zip 的部分模組"})
    import importlib.util
    spec = importlib.util.spec_from_file_location("下載ffmpeg", os.path.join(專案, "scripts", "下載ffmpeg.py"))
    下載 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(下載)
    項目們.append({
        "名稱": "FFmpeg", "版本": 下載.版本, "授權": "LGPL-3.0-or-later（BtbN 的 LGPL shared 建置）",
        "全文們": [("LICENSE.txt", _讀(os.path.join(專案, "vendor", "ffmpeg", "LICENSE.txt")))],
        "說明": f"_internal\\ffmpeg\\bin（ffmpeg.exe 與 DLL，未修改）。建置來源：{下載.網址}；"
              "原始碼：https://github.com/FFmpeg/FFmpeg/tree/2a571b606854520cf89804d8030c8b328e621689"})
    for 相對 in 磁碟:
        if 相對.lower().startswith("ffmpeg" + os.sep):
            對到的磁碟檔.add(_正規(相對))

    # ---- Python 套件 ----
    用到.pop("pyinstaller", None)            # 執行期模組已列在上面的固定項目
    for 名 in sorted(用到, key=str.lower):
        套件 = 用到[名]
        類型 = _授權類型(套件)
        全文 = _授權全文們(套件)
        說明 = ""
        if not 全文:
            for 鍵, 路徑 in 標準全文.items():
                if 鍵 in 類型 and os.path.isfile(路徑):
                    全文 = [(f"{鍵}（標準全文）", _讀(路徑))]
                    說明 = f"套件沒有附 {鍵} 全文，收錄標準全文。"
                    break
        if 全文 and all("Qt-Commercial" in 標題 for 標題, _ in 全文):        # PySide6／shiboken6 只附商業授權說明
            for 鍵 in ("LGPL-3.0", "GPL-3.0"):
                全文.append((f"{鍵}（標準全文）", _讀(標準全文[鍵])))
            說明 = "套件只附 Qt 商業授權說明；本程式依 LGPL-3.0 使用，收錄 LGPL-3.0 與 GPL-3.0 標準全文。"
        項目們.append({"名稱": 名, "版本": 套件.version, "授權": 類型, "全文們": 全文, "說明": 說明})

    對不到 = sorted(相對 for 相對 in 磁碟
                 if _正規(相對) not in 對到的磁碟檔 and not 是Python本身(相對, python根))
    return 項目們, 對不到


def 是Python本身(相對, python根):
    """_internal 裡來自 Python 安裝本身的檔案（DLLs、python313.dll、base_library.zip…）。"""
    名 = os.path.basename(相對)
    if os.sep not in 相對 and (名.lower().endswith(".pyd") or 名.lower() in {
            "python3.dll", "python313.dll", "vcruntime140.dll", "vcruntime140_1.dll", "base_library.zip",
            "libcrypto-3.dll", "libssl-3.dll", "libffi-8.dll", "sqlite3.dll"}):
        return os.path.isfile(os.path.join(python根, "DLLs", 名)) or os.path.isfile(os.path.join(python根, 名)) \
            or 名 == "base_library.zip"
    return False


def _檔名(項目):
    return re.sub(r'[\\/:*?"<>|（）\s]+', "_", f"{項目['名稱']}-{項目['版本']}").strip("_") + ".txt"


def 寫出(輸出, 建置):
    """產生 輸出\\licenses\\；回傳 (總表路徑, 項目們, 對不到的檔案們)。"""
    import version
    項目們, 對不到 = 收集(輸出, 建置)
    資料夾 = os.path.join(輸出, 資料夾名)
    os.makedirs(資料夾, exist_ok=True)
    行們 = [f"{version.產品名}（LiveSummary）{version.版本字()} 第三方授權清單",
          "",
          "本程式本身以 GNU GPLv3 授權（全文：程式資料夾的 LICENSE.txt）。",
          "以下是程式資料夾裡隨附的第三方元件；每一項的授權全文在同一個資料夾、檔名列在「全文」欄。",
          "",
          f"{'名稱':<34}{'版本':<26}授權類型",
          "-" * 100]
    for 項目 in 項目們:
        檔 = _檔名(項目)
        with open(os.path.join(資料夾, 檔), "w", encoding="utf-8") as f:
            f.write(f"{項目['名稱']} {項目['版本']}\n授權：{項目['授權']}\n")
            if 項目["說明"]:
                f.write(f"說明：{項目['說明']}\n")
            f.writelines(f"\n===== {標題} =====\n\n{文字.rstrip()}\n" for 標題, 文字 in 項目["全文們"])
            if not 項目["全文們"]:
                f.write("\n（套件沒有附授權全文）\n")
        行們.append(f"{項目['名稱']:<34}{項目['版本']:<26}{項目['授權']}")
        行們.append(f"{'':<34}全文：{檔}" + ("" if 項目["全文們"] else "（套件沒有附授權全文）"))
        if 項目["說明"]:
            行們.append(f"{'':<34}說明：{項目['說明']}")
    if 對不到:
        行們 += ["", "來源待確認的檔案（沒有對應到上面任何一項）：", *(f"  _internal\\{x}" for x in 對不到)]
    總表 = os.path.join(資料夾, 總表檔名)
    with open(總表, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(行們) + "\n")
    return 總表, 項目們, 對不到


if __name__ == "__main__":       # 單獨跑：用現有的 dist\LiveSummary 與 build\LiveSummary 產生並印出摘要（不重新打包）
    總表, 項目們, 對不到 = 寫出(os.path.join(專案, "dist", "LiveSummary"), os.path.join(專案, "build", "LiveSummary"))
    for 項目 in 項目們:
        print(f"{項目['名稱']} | {項目['版本']} | {項目['授權']} | 全文 {len(項目['全文們'])} 份")
    print("對不到的檔案：", *對不到, sep="\n  ")
