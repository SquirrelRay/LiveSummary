"""提交前檢查：pytest 必須全過，ruff 警告數不得比 .ruff-baseline 多。

手動執行（用開發環境 .venv 的 Python 3.13；先啟動 .venv 的話直接打 python 也可以）：
          .venv\\Scripts\\python.exe scripts/check.py          一般檢查（git hook 跑的就是這個，不含標成 slow 的慢測試）
          .venv\\Scripts\\python.exe scripts/check.py --all    完整檢查（連 slow 慢測試一起跑；改到置頂、滑鼠提示、視窗層級相關程式、打包前要跑）
通過回傳 0，失敗回傳 1。由 .githooks/pre-commit 在 git commit 時自動呼叫（加 --commit，不加 --all）。
--commit：這次 commit 沒有任何檔案變更（空的存檔點 commit）就不跑檢查、直接通過；有變更照常完整檢查。
pytest 分兩段：一般測試用 pytest-xdist 平行跑（-n）；標成 依序 的測試（真的 Windows 視窗等）之後另外單獨依序跑。
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = ROOT / ".ruff-baseline"
開發版本 = (3, 13)          # 開發環境的 Python 版本（.venv，用 requirements-lock.txt 建）
平行數上限 = 8              # 實測 8 個最快（20 執行緒的筆電：1 個 105 秒、4 個 35 秒、8 個 28 秒、16 個 31 秒）
依序標記 = "依序"           # @pytest.mark.依序：不能和其他測試同時跑的（設定在 pyproject.toml）


def run(args):
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", *args], cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},   # 子程序一律輸出 UTF-8，中文訊息才不會亂碼
    )


def staged_files():
    r = subprocess.run(
        ["git", "-c", "core.quotepath=off", "diff", "--cached", "--name-only"], cwd=ROOT,  # noqa: S607
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )
    return {Path(p).as_posix() for p in r.stdout.split("\n") if p.strip()}


def 沒有變更():
    """這次 commit 和 HEAD 比沒有任何檔案變更（空的存檔點 commit）才回 True。
    git diff --cached --quiet：0 = 沒有變更、1 = 有變更；其他（git 出錯）一律當成有變更，照常檢查。
    hook 裡 git 會設好 GIT_INDEX_FILE（例如 git commit 檔名 時的暫時索引），子程序沿用，比對的就是這次要提交的內容。"""
    r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT, capture_output=True, check=False)  # noqa: S607
    return r.returncode == 0


def 有平行套件():
    try:
        import xdist  # noqa: F401
    except ImportError:
        return False
    return True


def 依序測試檔():
    """含 @pytest.mark.依序 的測試檔（第二段只收集這些檔，不必再收集全部測試）。"""
    標 = re.compile(rf"@pytest\.mark\.{依序標記}\b")
    return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_*.py")
                  if 標.search(p.read_text(encoding="utf-8")))


def 通過數(輸出):
    m = re.search(r"(\d+) passed", 輸出)
    return int(m.group(1)) if m else 0


def check_pytest(全部=False):
    # pyproject.toml 的 addopts 預設 -m 'not slow'；這裡一律自己給 -m（後面的 -m 會蓋掉 addopts 的）
    print("【1/2】執行 pytest（含慢測試）..." if 全部 else "【1/2】執行 pytest（不含慢測試；要全部請加 --all）...")
    基本 = "" if 全部 else "not slow and "
    開始 = time.time()
    if 有平行套件():
        平行數 = min(平行數上限, os.cpu_count() or 1)
        段們 = [("平行", ["pytest", "-q", "-n", str(平行數), "-m", f"{基本}not {依序標記}"])]
        檔們 = 依序測試檔()
        if 檔們:
            段們.append(("依序", ["pytest", "-q", "-p", "no:xdist", "-m", f"{基本}{依序標記}", *檔們]))
    else:
        print("  注意：沒裝 pytest-xdist，全部依序跑（比較慢）。請重裝：.venv\\Scripts\\python.exe -m pip install -r requirements-lock.txt")
        段們 = [("依序", ["pytest", "-q", "-m", "" if 全部 else "not slow"])]
    說明們 = []
    for 名, 參數 in 段們:
        r = run(參數)
        if r.returncode == 5 and 名 == "依序" and len(段們) > 1 and not 全部:   # 5 = 沒選到測試：依序的都是慢測試，一般檢查本來就不跑
            continue
        if r.returncode != 0:
            print(f"  失敗：pytest（{名}執行的部分）有測試沒通過（或無法執行）。輸出如下：")
            print((r.stdout + r.stderr).rstrip())
            return False
        說明們.append(f"{名} {通過數(r.stdout)} 個")
    print(f"  通過：pytest 全部通過（{'＋'.join(說明們)}，{time.time() - 開始:.0f} 秒）。")
    return True


def check_ruff():
    print("【2/2】執行 ruff check，並與基準比較 ...")
    try:
        baseline = int(BASELINE_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        print(f"  失敗：讀不到有效的基準檔 {BASELINE_FILE.name}（內容應為一個整數）。")
        return False
    r = run(["ruff", "check", ".", "--output-format", "json"])
    try:
        items = json.loads(r.stdout)
    except ValueError:
        print("  失敗：ruff 無法執行或輸出無法解析（是否已安裝 requirements-dev.txt？）：")
        print((r.stdout + r.stderr).rstrip())
        return False
    now = len(items)
    if now > baseline:
        print(f"  失敗：ruff 警告數 {now}，比基準 {baseline} 多了 {now - baseline} 個。")
        staged = staged_files()
        rows = []
        for it in items:
            rel = Path(it["filename"]).resolve().relative_to(ROOT).as_posix()
            rows.append((rel, it["location"]["row"], it["location"]["column"],
                         it["code"], it["message"]))
        mine = [x for x in rows if x[0] in staged] or rows
        label = "本次要提交的檔案中的警告" if mine is not rows else "所有警告"
        print(f"  {label}（基準檔只存數量，無法精確指出哪幾個是新增，請對照這份清單）：")
        for rel, row, col, code, msg in mine:
            print(f"    {rel}:{row}:{col}: {code} {msg}")
        return False
    if now < baseline:
        print(f"  通過：ruff 警告數 {now}，比基準 {baseline} 少。"
              f"可以把 .ruff-baseline 調低為 {now}。")
    else:
        print(f"  通過：ruff 警告數 {now}，與基準 {baseline} 相同。")
    return True


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    if sys.version_info[:2] != 開發版本:
        print(f"失敗：這是 Python {sys.version.split()[0]}（{sys.executable}），開發環境是 Python {開發版本[0]}.{開發版本[1]}。")
        print("請用 .venv\\Scripts\\python.exe scripts/check.py（建立 .venv 的方法見 README「開發環境」）。")
        return 1
    if "--commit" in sys.argv[1:] and 沒有變更():
        print("這次 commit 沒有任何檔案變更（空的存檔點 commit），不必檢查，直接通過。")
        return 0
    ok = check_pytest("--all" in sys.argv[1:])
    ok = check_ruff() and ok
    print("\n檢查通過，可以提交。" if ok else "\n檢查失敗，提交已被擋下。請先修正上面列出的問題。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
