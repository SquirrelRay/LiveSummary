"""從上游取得「套件自己沒附」的授權全文，存到 third_party_licenses\\（提交進 git；打包時 licenses.py 只讀這裡，不連網）。

用法（專案資料夾）：.venv\\Scripts\\python.exe scripts\\取得授權全文.py

取得的項目（版本從 .venv 讀；套件升級後重跑一次，舊版本的資料夾手動刪掉）：
  - ctranslate2、tokenizers：GitHub 上該版本標籤的 LICENSE（套件的 wheel 沒附）。
  - Intel OpenMP（ctranslate2 自帶的 libiomp5md.dll）：Intel 在 PyPI 發布的 intel-openmp wheel 裡的授權檔。
    版本與 wheel 的 SHA-256 釘在下面；還會確認 wheel 裡的 libiomp5md.dll 和 ctranslate2 自帶的那份一模一樣，不一樣就停（表示要換版本）。
  - ctranslate2.dll 靜態包含的元件（Intel oneMKL、oneDNN、spdlog、CCCL（thrust／cub／libcu++）、cpu_features、CUTLASS、
    BS_thread_pool、avx_mathfun、avx512_mathfun）：版本照 ctranslate2 該版本的 Windows 建置腳本與子模組（釘在下面的 ct2內含元件，
    ctranslate2 版本不同就停，要重查）。oneMKL 的授權檔取自 Intel 在 PyPI 發布的同版本 mkl-include wheel。
  - Qt（PySide6 內含的 Qt 6 DLL 與外掛）：qtbase、qtimageformats 該版本標籤的 qt_attribution.json，
    只留打包會帶到的模組（Qt Core／Gui／Widgets／Svg／Image Formats），連同引用的授權檔合成一份。
手寫、不由這支產生的：third_party_licenses\\nvidia-cublas\\、vc-runtime\\（見各資料夾）。
"""
import hashlib
import io
import json
import os
import sys
import time
import urllib.request
import zipfile
from importlib import metadata

專案 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
輸出根 = os.path.join(專案, "third_party_licenses")

# Intel OpenMP：ctranslate2 4.8.2 自帶的 libiomp5md.dll（檔案版本 20250910）和 intel-openmp 2025.3.0 的同一個檔案 SHA-256 相同（2026-10-14 比對）
OpenMP版本 = "2025.3.0"
OpenMP網址 = ("https://files.pythonhosted.org/packages/79/69/05addedd727061b61a85b4fd989754edb628b5be1cd5d161727f98cf4d86/"
            "intel_openmp-2025.3.0-py2.py3-none-win_amd64.whl")
OpenMP_DLL標記 = "libiomp5md.dll SHA-256："      # licenses.py 打包時用這行確認 _internal 裡的檔案就是這一版
OpenMP_SHA256 = "8ff899d01a41b92ffe0e618b221ea633127d16df726086082d381c431c31339d"      # PyPI 列的 digest

# ctranslate2.dll 靜態包含的元件（2026-10-14 查 ctranslate2 v4.8.2：python/tools/prepare_build_environment_windows.sh 與 third_party 子模組）。
# 建置參數：WITH_MKL（預設 ON）、WITH_DNNL=ON（oneDNN 3.1.1 靜態）、WITH_CUDA=ON、WITH_CUDNN=OFF、CUDA_DYNAMIC_LOADING=ON、BUILD_CLI=OFF；
# x86 不用 ruy；cxxopts 只給命令列工具、googletest 只給測試，都沒編進去。
ct2版本 = "4.8.2"
MKL版本 = "2025.3.0"           # 建置腳本裝的是 oneAPI Base Toolkit 2025.3.0 的 oneMKL
MKL網址 = ("https://files.pythonhosted.org/packages/b9/d7/0445e80511e70b653291daaac068712a780ee0e00bb791d047eed0053c4b/"
         "mkl_include-2025.3.0-py2.py3-none-win_amd64.whl")
MKL_SHA256 = "d8efcf39c37767c65abdf42976189475bab36f456e5e7e53bab00bc35c6a3209"
ct2原始碼 = "https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2"
# (名稱, 版本或提交, 授權, [(標題, 網址)])；標題結尾是「（檔頭）」的只取檔案開頭的註解（第一個 # 開頭的行之前）
ct2內含元件 = [
    ("oneDNN", "3.1.1", "Apache-2.0（另附第三方程式聲明）",
     [("LICENSE", "https://raw.githubusercontent.com/oneapi-src/oneDNN/v3.1.1/LICENSE"),
      ("THIRD-PARTY-PROGRAMS", "https://raw.githubusercontent.com/oneapi-src/oneDNN/v3.1.1/THIRD-PARTY-PROGRAMS")]),
    ("spdlog", "76fb40d95455f249bd70824ecfcae7a8f0930fa3", "MIT",
     [("LICENSE", "https://raw.githubusercontent.com/gabime/spdlog/76fb40d95455f249bd70824ecfcae7a8f0930fa3/LICENSE")]),
    ("CCCL（thrust、cub、libcu++）", "b5fe509fd11a925f90d6495176707cc1184eed9d", "Apache-2.0（thrust 部分另有例外）、Apache-2.0 WITH LLVM-exception、BSD-3-Clause",
     [("LICENSE", "https://raw.githubusercontent.com/NVIDIA/cccl/b5fe509fd11a925f90d6495176707cc1184eed9d/LICENSE")]),
    ("cpu_features", "8a494eb1e158ec2050e5f699a504fbc9b896a43b", "Apache-2.0",
     [("LICENSE", "https://raw.githubusercontent.com/google/cpu_features/8a494eb1e158ec2050e5f699a504fbc9b896a43b/LICENSE")]),
    ("CUTLASS", "bbe579a9e3beb6ea6626d9227ec32d0dae119a49", "BSD-3-Clause",
     [("LICENSE.txt", "https://raw.githubusercontent.com/NVIDIA/cutlass/bbe579a9e3beb6ea6626d9227ec32d0dae119a49/LICENSE.txt")]),
    ("BS::thread_pool", f"ctranslate2 v{ct2版本} 隨附", "MIT", [("BS_thread_pool.hpp（檔頭）", f"{ct2原始碼}/third_party/BS_thread_pool.hpp")]),
    ("avx_mathfun", f"ctranslate2 v{ct2版本} 隨附", "zlib／MIT（見檔頭）", [("avx_mathfun.h（檔頭）", f"{ct2原始碼}/third_party/avx_mathfun.h")]),
    ("avx512_mathfun", f"ctranslate2 v{ct2版本} 隨附", "BSD-2-Clause（見檔頭）", [("avx512_mathfun.h（檔頭）", f"{ct2原始碼}/third_party/avx512_mathfun.h")]),
]

# Qt：打包會帶到的模組（spec 排除了 QtNetwork；PySide6 的 hook 收 QtCore／Gui／Widgets＋Svg、影像格式外掛）
Qt庫們 = ("qtbase", "qtimageformats")
Qt模組 = {"qtcore", "qtgui", "qtwidgets", "qtsvg", "qtimageformats"}
# 只在其他平台或建置工具用的（Windows 版 DLL 裡沒有）
Qt排除路徑 = ("/wayland/", "/xcb/", "/android/", "/cocoa/", "/wasm/", "/forkfd/", "/gradle/", "cmake/3rdparty/",
           "/testlib/", "/testinternal/", "tests/", "util/", "src/dbus/")


def 下載(網址):
    if not 網址.startswith("https://"):
        raise ValueError(f"只下載 https 網址：{網址}")
    要求 = urllib.request.Request(網址, headers={"User-Agent": "LiveSummary-license-fetch"})  # noqa: S310  上面已限定 https
    for 次 in range(3):
        try:
            with urllib.request.urlopen(要求, timeout=60) as r:      # noqa: S310  固定的 https 網址（GitHub、PyPI）
                return r.read()
        except OSError:
            if 次 == 2:
                raise
            time.sleep(2)


def 寫(資料夾, 檔名, 文字):
    os.makedirs(資料夾, exist_ok=True)
    with open(os.path.join(資料夾, 檔名), "w", encoding="utf-8", newline="\n") as f:
        f.write(文字.replace("\r\n", "\n").rstrip() + "\n")


def 寫來源(資料夾, 行們):
    寫(資料夾, "來源.txt", "\n".join([f"取得日期：{time.strftime('%Y-%m-%d')}（scripts\\取得授權全文.py 產生，不要手改）", *行們]))


def 版本(套件):
    return metadata.version(套件)


def 取GitHub授權(套件, 倉庫, 標籤, 檔="LICENSE"):
    網址 = f"https://raw.githubusercontent.com/{倉庫}/{標籤}/{檔}"
    資料夾 = os.path.join(輸出根, f"{套件}-{版本(套件)}")
    寫(資料夾, "LICENSE.txt", 下載(網址).decode("utf-8"))
    寫來源(資料夾, [f"{套件} {版本(套件)} 的授權全文（套件的 wheel 沒附）", f"網址：{網址}"])
    print(f"{套件}：{網址}")


def 取OpenMP():
    資料 = 下載(OpenMP網址)
    if hashlib.sha256(資料).hexdigest() != OpenMP_SHA256:
        sys.exit("intel-openmp wheel 的 SHA-256 不符，停止")
    z = zipfile.ZipFile(io.BytesIO(資料))
    名們 = z.namelist()
    dll = next(n for n in 名們 if n.lower().endswith("/library/bin/libiomp5md.dll"))
    自帶 = os.path.join(專案, ".venv", "Lib", "site-packages", "ctranslate2", "libiomp5md.dll")
    with open(自帶, "rb") as f:
        dll雜湊 = hashlib.sha256(f.read()).hexdigest()
        if hashlib.sha256(z.read(dll)).hexdigest() != dll雜湊:
            sys.exit(f"ctranslate2 自帶的 libiomp5md.dll 和 intel-openmp {OpenMP版本} 的不同：ctranslate2 升級了？要找對應的 intel-openmp 版本")
    資料夾 = os.path.join(輸出根, f"intel-openmp-{OpenMP版本}")
    授權 = next(n for n in 名們 if n.endswith(".dist-info/LICENSE.txt"))
    第三方 = next(n for n in 名們 if n.endswith("third-party-programs.txt"))
    寫(資料夾, "LICENSE.txt", z.read(授權).decode("cp1252"))                  # Intel 的檔案是 Windows-1252
    寫(資料夾, "third-party-programs.txt", z.read(第三方).decode("cp1252"))
    寫來源(資料夾, [f"Intel OpenMP 執行期 {OpenMP版本}（ctranslate2 自帶的 libiomp5md.dll；和這個 wheel 裡的檔案 SHA-256 相同）",
              f"網址：{OpenMP網址}", f"wheel SHA-256：{OpenMP_SHA256}",
              f"{OpenMP_DLL標記}{dll雜湊}", f"LICENSE.txt ← {授權}", f"third-party-programs.txt ← {第三方}"])
    print(f"Intel OpenMP：{OpenMP網址}")


def Qt要收(路徑, 項):
    """qt_attribution.json 的一項要不要收：打包會帶到的模組，而且不是其他平台／建置工具用的。"""
    if any(x in "/" + 路徑 for x in Qt排除路徑):
        return False
    模組 = (項.get("QDocModule") or "").lower()
    return not 模組 or 模組 in Qt模組


def _串(值):
    return "\n".join(值) if isinstance(值, list) else (值 or "")


def 檔頭註解(文字):
    """C／C++ 檔案開頭的註解（第一個 # 開頭的前置處理指令之前的部分）。"""
    行們 = []
    for 行 in 文字.splitlines():
        if 行.lstrip().startswith("#"):
            break
        行們.append(行)
    return "\n".join(行們).strip()


def 取ctranslate2內含():
    if 版本("ctranslate2") != ct2版本:
        sys.exit(f"ctranslate2 是 {版本('ctranslate2')}，ct2內含元件是照 {ct2版本} 查的：重查建置腳本與子模組後更新")
    區塊們, 來源行 = [], [f"ctranslate2 {ct2版本} 的 ctranslate2.dll 靜態包含的元件",
                      f"依據：{ct2原始碼}/python/tools/prepare_build_environment_windows.sh、{ct2原始碼}/CMakeLists.txt、{ct2原始碼}/.gitmodules"]
    資料 = 下載(MKL網址)
    if hashlib.sha256(資料).hexdigest() != MKL_SHA256:
        sys.exit("mkl-include wheel 的 SHA-256 不符，停止")
    z = zipfile.ZipFile(io.BytesIO(資料))
    授權 = next(n for n in z.namelist() if n.endswith(".dist-info/LICENSE.txt"))
    區塊們.append("\n".join([f"===== Intel oneAPI Math Kernel Library（oneMKL）{MKL版本} =====",
                            "授權：Intel Simplified Software License（Version October 2022）",
                            "Intel(R) oneAPI Math Kernel Library, Copyright (C) Intel Corporation. All rights reserved.",
                            f"（授權檔取自 Intel 在 PyPI 發布的 mkl-include {MKL版本}：{MKL網址}）", "",
                            z.read(授權).decode("utf-8").rstrip(), ""]))
    來源行 += [f"  oneMKL：{MKL網址}（SHA-256 {MKL_SHA256}，{授權}）"]
    for 名, 版, 授權類型, 檔們 in ct2內含元件:
        內容 = [f"===== {名} {版} =====", f"授權：{授權類型}"]
        for 標題, 網址 in 檔們:
            文字 = 下載(網址).decode("utf-8", "replace")
            if 標題.endswith("（檔頭）"):
                文字 = 檔頭註解(文字)
            內容 += [f"--- {標題}（{網址}）---", 文字.rstrip(), ""]
            來源行.append(f"  {名}：{網址}")
        區塊們.append("\n".join(內容))
    區塊們.append("===== NVIDIA CUDA 執行期（CUDA 12.8，靜態連結） =====\n"
                "ctranslate2.dll 以 CUDA Toolkit 12.8 建置並靜態連結 CUDA 執行期（cudart_static.lib），\n"
                "依 NVIDIA CUDA Toolkit 最終使用者授權合約附件 A 可再散布；合約全文見 nvidia-cublas-cu12 那一項的 License.txt。\n")
    資料夾 = os.path.join(輸出根, f"ctranslate2-內含-{ct2版本}")
    寫(資料夾, "內含元件.txt", "\n".join([f"ctranslate2 {ct2版本} 的 ctranslate2.dll 靜態包含的第三方元件（{len(區塊們)} 項）", ""] + 區塊們))
    寫來源(資料夾, 來源行)
    print(f"ctranslate2 內含元件：{len(區塊們)} 項")


def 取Qt():
    qt版本 = 版本("PySide6_Essentials")
    標籤 = f"v{qt版本}"
    區塊們, 來源行 = [], [f"Qt {qt版本}（PySide6_Essentials {qt版本} 內含）的第三方元件聲明", "從各個 qt_attribution.json 與它引用的授權檔合成："]
    已收全文 = {}
    for 庫 in Qt庫們:
        樹 = json.loads(下載(f"https://api.github.com/repos/qt/{庫}/git/trees/{標籤}?recursive=1"))
        if 樹.get("truncated"):
            sys.exit(f"GitHub 回傳的 {庫} 檔案清單不完整，停止")
        for 路徑 in sorted(x["path"] for x in 樹["tree"] if x["path"].endswith("qt_attribution.json")):
            網址 = f"https://raw.githubusercontent.com/qt/{庫}/{標籤}/{路徑}"
            內容 = json.loads(下載(網址), strict=False)          # 有幾個檔字串裡有 tab
            for 項 in 內容 if isinstance(內容, list) else [內容]:
                if not Qt要收(路徑, 項):
                    continue
                資料夾 = 路徑.rsplit("/", 1)[0]
                全文們 = []
                for 檔 in ([項["LicenseFile"]] if isinstance(項.get("LicenseFile"), str) else 項.get("LicenseFile") or []):
                    檔路徑 = os.path.normpath(f"{資料夾}/{檔}").replace("\\", "/")
                    鍵 = f"{庫}/{檔路徑}"
                    if 鍵 in 已收全文:
                        全文們.append(f"（授權全文同上：{已收全文[鍵]}）")
                    else:
                        全文們.append(下載(f"https://raw.githubusercontent.com/qt/{庫}/{標籤}/{檔路徑}").decode("utf-8", "replace").rstrip())
                        已收全文[鍵] = 項.get("Name", 檔路徑)
                區塊們.append("\n".join([
                    f"===== {項.get('Name', '')} {項.get('Version', '')} =====".replace("  ", " "),
                    f"Qt 原始碼位置：{庫}/{資料夾}",
                    f"用途：{項.get('QtUsage', '')}",
                    f"授權：{項.get('License', '')}（{項.get('LicenseId', '')}）",
                    "版權：" + _串(項.get("Copyright")).replace("\n", "\n      "),
                    "", *全文們, ""]))
                來源行.append(f"  {網址}")
    資料夾 = os.path.join(輸出根, f"qt-{qt版本}")
    寫(資料夾, "第三方元件.txt", "\n".join([f"Qt {qt版本} 內含的第三方元件（{len(區塊們)} 項）",
                                     "下列元件編譯在本程式隨附的 Qt DLL（Qt6Core、Qt6Gui、Qt6Widgets、Qt6Svg）與影像格式外掛裡。", ""] + 區塊們))
    寫來源(資料夾, 來源行)
    print(f"Qt {qt版本}：{len(區塊們)} 項第三方元件")


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    取GitHub授權("ctranslate2", "OpenNMT/CTranslate2", f"v{版本('ctranslate2')}")
    取GitHub授權("tokenizers", "huggingface/tokenizers", f"v{版本('tokenizers')}")
    取OpenMP()
    取ctranslate2內含()
    取Qt()
    print(f"完成：{輸出根}")


if __name__ == "__main__":
    main()
