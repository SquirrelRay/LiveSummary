# 第三方授權清單：打包時（scripts/build_exe.py）自動產生 dist\LiveSummary\licenses\。
#   licenses\第三方授權清單.txt   總表（名稱／版本／授權類型／全文檔名／說明，最後是「原始碼取得方式」）
#   licenses\<名稱>-<版本>.txt     每一項的授權全文（套件自己附的檔案原樣收進來）
# 涵蓋的東西怎麼找：
#   - Python 套件：PyInstaller 的建置紀錄（build\LiveSummary\PYZ-*.toc，純 Python 模組）＋ _internal 裡實際的檔案，
#     對回 .venv 裡每個套件的檔案清單（importlib.metadata），對到的才算有帶進去（開發用的 pytest、ruff 等不會出現）。
#   - Python 本身（標準函式庫、python313.dll 等）、PyInstaller 開機程式、隨附 ffmpeg、Intel OpenMP、VC++ 執行階段：固定項目。
#   - 套件沒附的全文（ctranslate2、tokenizers、Intel OpenMP、Qt 內含的第三方元件）與手寫的聲明（cuBLAS、VC++）：
#     third_party_licenses\（scripts\取得授權全文.py 從上游取得，提交進 git），這裡只讀、不連網。
#   - 對不到任何套件的檔案列在總表最後「來源待確認的檔案」，並在打包時印出來（不猜它是誰的）。
# 打包時印出的警告（不讓打包失敗，給人確認）：沒附全文、來源待確認、隨附函式庫（*.libs）的授權沒收錄、
#   LGPL／GPL／MPL 元件沒有原始碼取得方式、補充全文找不到或版本不符。
# 這支只負責「收集與列出」，不判斷相容性；相容性與附帶義務的決定記在 docs\打包調查.md。
# 只用標準函式庫＋.venv 已有的套件；不連網。
import glob
import hashlib
import os
import re
import sys
from importlib import metadata

專案 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 專案)

總表檔名 = "第三方授權清單.txt"
資料夾名 = "licenses"
補充根 = os.path.join(專案, "third_party_licenses")
OpenMP標記 = "libiomp5md.dll SHA-256："          # 和 scripts\取得授權全文.py 的 OpenMP_DLL標記 一樣

# 套件自己沒附授權全文時，用專案裡現成的標準全文（這些授權的全文每一份都一樣，不需要填版權人）
標準全文 = {
    "LGPL-3.0": os.path.join(專案, "vendor", "ffmpeg", "LICENSE.txt"),       # BtbN ffmpeg 附的 LGPL v3 全文
    "GPL-3.0": os.path.join(專案, "LICENSE"),
}
授權檔樣式 = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS|ThirdPartyNotices)", re.IGNORECASE)

# 套件沒附全文、改從 third_party_licenses\<資料夾>-<套件版本>\ 收（資料夾版本要等於 .venv 裡的版本，不然當作找不到）
上游全文 = {"ctranslate2": "ctranslate2", "tokenizers": "tokenizers", "PySide6_Essentials": "qt"}
# 額外附在某個套件後面的手寫聲明（third_party_licenses\ 底下的檔案）
附加聲明 = {"nvidia-cublas-cu12": os.path.join("nvidia-cublas", "聲明.txt")}

# 原始碼取得方式：授權要求提供原始碼（LGPL／GPL／MPL）的元件，列出該版本的上游原始碼網址。{v}＝版本、{mm}＝主.次版本。
# FFmpeg 的另外從 scripts\下載ffmpeg.py 讀（提交與備份檔名）。網址 2026-10-14 逐一確認過。
原始碼網址 = {
    "PySide6_Essentials": [
        "PySide6（Qt for Python）：https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{v}-src/pyside-setup-everywhere-src-{v}.zip",
        ("Qt {v}（本程式只帶 qtbase、qtsvg、qtimageformats）：https://download.qt.io/official_releases/qt/{mm}/{v}/submodules/"
         "（qtbase-everywhere-src-{v}.zip、qtsvg-everywhere-src-{v}.zip、qtimageformats-everywhere-src-{v}.zip）")],
    "shiboken6": ["https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{v}-src/pyside-setup-everywhere-src-{v}.zip"],
    "pycountry": ["https://files.pythonhosted.org/packages/source/p/pycountry/pycountry-{v}.tar.gz",
                  "https://github.com/pycountry/pycountry/tree/{v}"],
    "certifi": ["https://files.pythonhosted.org/packages/source/c/certifi/certifi-{v}.tar.gz"],
    "tqdm": ["https://files.pythonhosted.org/packages/source/t/tqdm/tqdm-{v}.tar.gz", "https://github.com/tqdm/tqdm/tree/v{v}"],
    "PyInstaller（開機程式與執行期模組）": ["https://files.pythonhosted.org/packages/source/p/pyinstaller/pyinstaller-{v}.tar.gz",
                                    "https://github.com/pyinstaller/pyinstaller/tree/v{v}"],
}
要原始碼 = re.compile(r"\b(L?GPL|MPL)")
VC執行階段 = re.compile(r"^(msvcp140(_\d+)?|vcruntime140(_\d+)?|concrt140)(-[0-9a-f]{32})?\.dll$", re.IGNORECASE)


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


def _雜湊(路徑):
    with open(路徑, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def 補充全文(資料夾):
    """third_party_licenses\\<資料夾>\\ 裡的全文（來源.txt 以外的每個檔）；資料夾不存在回傳 None。"""
    完整 = os.path.join(補充根, 資料夾)
    if not os.path.isdir(完整):
        return None
    return [(f"{名}（{資料夾}）", _讀(os.path.join(完整, 名))) for 名 in sorted(os.listdir(完整))
            if 名 != "來源.txt" and os.path.isfile(os.path.join(完整, 名))]


def _檔案版本(路徑):
    """DLL 的 FileVersion（讀不到回傳空字串）。"""
    import pefile
    try:
        pe = pefile.PE(路徑, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        try:
            for 資訊 in getattr(pe, "FileInfo", []) or []:
                for 項 in 資訊:
                    for 表 in getattr(項, "StringTable", []) or []:
                        版本 = 表.entries.get(b"FileVersion")
                        if 版本:
                            return 版本.decode(errors="replace")
        finally:
            pe.close()
    except (OSError, pefile.PEFormatError):
        return ""
    return ""


def _Intel_OpenMP(輸出, 磁碟):
    """ctranslate2 自帶的 libiomp5md.dll：找雜湊相同的 third_party_licenses\\intel-openmp-*\\。沒帶這個檔回傳 None。"""
    相對 = next((x for x in 磁碟 if os.path.basename(x).lower() == "libiomp5md.dll"), None)
    if 相對 is None:
        return None
    雜湊 = _雜湊(os.path.join(輸出, "_internal", 相對))
    for 資料夾 in sorted(glob.glob(os.path.join(補充根, "intel-openmp-*"))):
        來源 = os.path.join(資料夾, "來源.txt")
        if os.path.isfile(來源) and f"{OpenMP標記}{雜湊}" in _讀(來源):
            名 = os.path.basename(資料夾)
            return {"名稱": "Intel OpenMP 執行期", "版本": 名.split("-", 2)[-1],
                    "授權": "Intel End User License Agreement for Developer Tools（Intel 專有授權，可再散布）",
                    "全文們": 補充全文(名), "相對": [相對],
                    "說明": f"_internal\\{相對}（ctranslate2 自帶，檔案版本 {_檔案版本(os.path.join(輸出, '_internal', 相對))}；"
                          f"和 Intel 在 PyPI 發布的 intel-openmp {名.split('-', 2)[-1]} 的同一個檔案 SHA-256 相同）"}
    return {"名稱": "Intel OpenMP 執行期", "版本": "（版本待確認）", "授權": "Intel 專有授權", "全文們": [], "相對": [相對],
            "說明": "third_party_licenses 裡沒有對應這個 libiomp5md.dll 的授權全文：重跑 scripts\\取得授權全文.py"}


def _VC執行階段(輸出, 磁碟):
    檔們 = sorted(x for x in 磁碟 if VC執行階段.match(os.path.basename(x)))
    if not 檔們:
        return None
    清單 = "\n".join(f"  _internal\\{x}（{_檔案版本(os.path.join(輸出, '_internal', x)) or '版本讀不到'}）" for x in 檔們)
    說明檔 = os.path.join(補充根, "vc-runtime", "說明.txt")
    全文 = [("說明.txt（vc-runtime）", _讀(說明檔).rstrip() + "\n\n本程式資料夾裡的檔案：\n" + 清單)] if os.path.isfile(說明檔) else []
    return {"名稱": "Microsoft Visual C++ 執行階段", "版本": "14.x", "授權": "Microsoft Visual Studio 授權條款（可散發程式碼）",
            "全文們": 全文, "相對": 檔們, "說明": f"msvcp140／vcruntime140 等 {len(檔們)} 個檔（各套件與 Python 隨附、或建置電腦的 System32）"}


def _原始碼(項目):
    """這一項的原始碼網址們（版本代進樣板）。"""
    v = 項目["版本"]
    mm = ".".join(v.split(".")[:2])
    return [x.format(v=v, mm=mm) for x in 原始碼網址.get(項目["名稱"], [])]


def 隨附庫沒提到(輸出, 項目們):
    """*.libs（delvewheel 放的套件隨附 DLL）裡、套件授權全文沒提到名稱的函式庫：{資料夾: [函式庫名]}。VC++ 執行階段另有一項，不算。"""
    內部 = os.path.join(輸出, "_internal")
    結果 = {}
    for 資料夾 in sorted(os.listdir(內部)):
        if not 資料夾.endswith(".libs") or not os.path.isdir(os.path.join(內部, 資料夾)):
            continue
        主 = 資料夾[:-5].lower()
        文字 = " ".join(t for x in 項目們 if x["名稱"].lower().replace("-", "_") == 主 for _, t in x["全文們"]).lower()
        沒提到 = []
        for 檔 in sorted(os.listdir(os.path.join(內部, 資料夾))):
            if not 檔.lower().endswith(".dll") or VC執行階段.match(檔):
                continue
            名 = re.sub(r"-[0-9a-f]{32}$", "", 檔[:-4])
            詞們 = [w[3:] if w.startswith("lib") and len(w) > 6 else w for w in re.split(r"[-_.\d]+", 名.lower())]
            if not any(len(w) >= 3 and re.search(rf"\b{re.escape(w)}\b", 文字) for w in 詞們):      # 整個詞（避免 enc 之類的片段誤中）
                沒提到.append(名)
        if 沒提到:
            結果[資料夾] = 沒提到
    return 結果


def 收集(輸出, 建置):
    """回傳 (項目們, 對不到的檔案們, 警告們)。項目：dict(名稱, 版本, 授權, 全文們[(標題, 文字)], 說明, 原始碼[網址])。"""
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
    缺補充 = []

    # ---- 固定項目 ----
    項目們.append({
        "名稱": "Python", "版本": sys.version.split()[0], "授權": "PSF-2.0（另含 OpenSSL、libffi、SQLite、zlib 等的授權，見全文）",
        "全文們": [("LICENSE.txt", _讀(os.path.join(sys.base_prefix, "LICENSE.txt")))],
        "說明": "Python 直譯器與標準函式庫（python313.dll、*.pyd、libcrypto-3.dll／libssl-3.dll（OpenSSL）、sqlite3.dll、libffi；"
              "vcruntime140*.dll 見「Microsoft Visual C++ 執行階段」）"})
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
        "說明": f"_internal\\ffmpeg\\bin（ffmpeg.exe 與 DLL，未修改）。建置來源：{下載.網址}",
        "原始碼": [f"https://github.com/FFmpeg/FFmpeg/tree/{下載.原始碼提交}",
                f"壓縮檔：{下載.原始碼網址}（發布頁另附同一份備份 {下載.原始碼檔名}，SHA-256 {下載.原始碼SHA256}）",
                "建置腳本：https://github.com/BtbN/FFmpeg-Builds"]})
    for 相對 in 磁碟:
        if 相對.lower().startswith("ffmpeg" + os.sep):
            對到的磁碟檔.add(_正規(相對))
    for 固定 in (_Intel_OpenMP(輸出, 磁碟), _VC執行階段(輸出, 磁碟)):
        if 固定:
            對到的磁碟檔.update(_正規(x) for x in 固定.pop("相對"))
            項目們.append(固定)

    # ---- Python 套件 ----
    用到.pop("pyinstaller", None)            # 執行期模組已列在上面的固定項目
    for 名 in sorted(用到, key=str.lower):
        套件 = 用到[名]
        類型 = _授權類型(套件)
        全文 = _授權全文們(套件)
        說明 = ""
        if 名 in 上游全文:
            資料夾 = f"{上游全文[名]}-{套件.version}"
            補 = 補充全文(資料夾)
            if 補 is None:
                缺補充.append(資料夾)
            else:
                全文 += 補
                說明 = "Qt 內含的第三方元件聲明另附（qt 第三方元件.txt）。" if 上游全文[名] == "qt" else "授權全文取自上游該版本的原始碼庫。"
        if not 全文:
            for 鍵, 路徑 in 標準全文.items():
                if 鍵 in 類型 and os.path.isfile(路徑):
                    全文 = [(f"{鍵}（標準全文）", _讀(路徑))]
                    說明 = f"套件沒有附 {鍵} 全文，收錄標準全文。"
                    break
        if 全文 and all("Qt-Commercial" in 標題 or "（qt-" in 標題 for 標題, _ in 全文):   # PySide6／shiboken6 只附商業授權說明
            for 鍵 in ("LGPL-3.0", "GPL-3.0"):
                全文.append((f"{鍵}（標準全文）", _讀(標準全文[鍵])))
            說明 = ("套件只附 Qt 商業授權說明；本程式依 LGPL-3.0 使用，收錄 LGPL-3.0 與 GPL-3.0 標準全文。" + 說明).strip()
        if 名 in 附加聲明:
            路徑 = os.path.join(補充根, 附加聲明[名])
            if os.path.isfile(路徑):
                全文.insert(0, (os.path.basename(路徑), _讀(路徑)))
            else:
                缺補充.append(附加聲明[名])
        項目們.append({"名稱": 名, "版本": 套件.version, "授權": 類型, "全文們": 全文, "說明": 說明})

    for 項目 in 項目們:
        項目.setdefault("原始碼", _原始碼(項目))

    對不到 = sorted(相對 for 相對 in 磁碟
                 if _正規(相對) not in 對到的磁碟檔 and not 是Python本身(相對, python根))
    警告們 = []
    沒全文 = [f"{x['名稱']} {x['版本']}" for x in 項目們 if not x["全文們"]]
    if 沒全文:
        警告們.append("沒有授權全文：" + "、".join(沒全文))
    if 對不到:
        警告們.append("來源待確認的檔案（沒對應到任何一項）：" + "、".join(對不到))
    for 資料夾, 名們 in 隨附庫沒提到(輸出, 項目們).items():
        警告們.append(f"{資料夾} 隨附的函式庫沒有收錄授權全文（套件的授權檔沒提到）：" + "、".join(名們))
    沒原始碼 = [f"{x['名稱']}（{x['授權']}）" for x in 項目們 if 要原始碼.search(x["授權"]) and not x["原始碼"]]
    if 沒原始碼:
        警告們.append("授權要求提供原始碼、但沒有列出原始碼取得方式：" + "、".join(沒原始碼))
    if 缺補充:
        警告們.append("third_party_licenses 裡找不到（或版本不符）：" + "、".join(缺補充) + "（重跑 scripts\\取得授權全文.py）")
    return 項目們, 對不到, 警告們


def 是Python本身(相對, python根):
    """_internal 裡來自 Python 安裝本身的檔案（DLLs、python313.dll、base_library.zip…）。"""
    名 = os.path.basename(相對)
    if os.sep not in 相對 and (名.lower().endswith(".pyd") or 名.lower() in {
            "python3.dll", "python313.dll", "vcruntime140.dll", "vcruntime140_1.dll", "base_library.zip",
            "libcrypto-3.dll", "libssl-3.dll", "libffi-8.dll", "sqlite3.dll"}):
        return os.path.isfile(os.path.join(python根, "DLLs", 名)) or os.path.isfile(os.path.join(python根, 名)) \
            or 名 == "base_library.zip"
    return False


def OpenSSL來源問題(輸出):
    """_internal 裡所有 OpenSSL DLL 都要是 Python 自己的（同名、與 Python 安裝的 DLLs 裡那份 SHA-256 相同）。
    回傳 (問題們, 檢查過的檔名們)；問題是空的就是通過。"""
    問題, 檢查過 = [], []
    for 路, _, 檔們 in os.walk(os.path.join(輸出, "_internal")):
        for 檔 in 檔們:
            if not re.match(r"(?i)^lib(crypto|ssl)\b.*\.dll$", 檔):
                continue
            相對 = os.path.relpath(os.path.join(路, 檔), 輸出)
            原檔 = os.path.join(sys.base_prefix, "DLLs", 檔)
            if not os.path.isfile(原檔):
                問題.append(f"{相對}：Python 安裝裡沒有同名的檔案（不是 Python 自己的 OpenSSL）")
            elif _雜湊(原檔) != _雜湊(os.path.join(路, 檔)):
                問題.append(f"{相對}：和 {原檔} 內容不同")
            else:
                檢查過.append(檔)
    if not 檢查過 and not 問題:
        問題.append("打包結果裡沒有 OpenSSL（libcrypto-3.dll／libssl-3.dll），HTTPS 會失敗")
    return 問題, sorted(檢查過)


def _檔名(項目):
    return re.sub(r'[\\/:*?"<>|（）\s]+', "_", f"{項目['名稱']}-{項目['版本']}").strip("_") + ".txt"


def 寫出(輸出, 建置):
    """產生 輸出\\licenses\\；回傳 (總表路徑, 項目們, 對不到的檔案們, 警告們)。"""
    import version
    項目們, 對不到, 警告們 = 收集(輸出, 建置)
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
            if 項目["原始碼"]:
                f.write("原始碼：\n" + "".join(f"  {x}\n" for x in 項目["原始碼"]))
            f.writelines(f"\n===== {標題} =====\n\n{文字.rstrip()}\n" for 標題, 文字 in 項目["全文們"])
            if not 項目["全文們"]:
                f.write("\n（套件沒有附授權全文）\n")
        行們.append(f"{項目['名稱']:<34}{項目['版本']:<26}{項目['授權']}")
        行們.append(f"{'':<34}全文：{檔}" + ("" if 項目["全文們"] else "（套件沒有附授權全文）"))
        if 項目["說明"]:
            行們.append(f"{'':<34}說明：{項目['說明']}")
    行們 += ["", "原始碼取得方式",
           "-" * 100,
           "下列元件的授權（LGPL／GPL／MPL）要求提供原始碼。本程式隨附的是未修改的版本，對應原始碼可從下列網址取得：", ""]
    for 項目 in 項目們:
        if 項目["原始碼"]:
            行們.append(f"{項目['名稱']} {項目['版本']}（{項目['授權']}）")
            行們 += [f"  {x}" for x in 項目["原始碼"]]
    行們 += ["", "本程式自己的原始碼：見發布頁（GPLv3）。"]
    if 對不到:
        行們 += ["", "來源待確認的檔案（沒有對應到上面任何一項）：", *(f"  _internal\\{x}" for x in 對不到)]
    其他 = [x for x in 警告們 if not x.startswith(("沒有授權全文", "來源待確認"))]
    if 其他:
        行們 += ["", "尚待處理：", *(f"  {x}" for x in 其他)]
    總表 = os.path.join(資料夾, 總表檔名)
    with open(總表, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(行們) + "\n")
    return 總表, 項目們, 對不到, 警告們


if __name__ == "__main__":       # 單獨跑：用現有的 dist\LiveSummary 與 build\LiveSummary 產生並印出摘要（不重新打包）
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    總表, 項目們, 對不到, 警告們 = 寫出(os.path.join(專案, "dist", "LiveSummary"), os.path.join(專案, "build", "LiveSummary"))
    for 項目 in 項目們:
        print(f"{項目['名稱']} | {項目['版本']} | {項目['授權']} | 全文 {len(項目['全文們'])} 份")
    print("警告：", *警告們, sep="\n  ")
