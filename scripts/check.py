"""提交前檢查：pytest 必須全過，ruff 警告數不得比 .ruff-baseline 多。

手動執行：python scripts/check.py
通過回傳 0，失敗回傳 1。由 .githooks/pre-commit 在 git commit 時自動呼叫。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = ROOT / ".ruff-baseline"


def run(args):
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", *args], cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
    )


def staged_files():
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=ROOT,  # noqa: S607
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )
    return {Path(p).as_posix() for p in r.stdout.split("\n") if p.strip()}


def check_pytest():
    print("【1/2】執行 pytest ...")
    r = run(["pytest", "-q"])
    if r.returncode == 0:
        print("  通過：pytest 全部通過。")
        return True
    print("  失敗：pytest 有測試沒通過（或無法執行）。輸出如下：")
    print((r.stdout + r.stderr).rstrip())
    return False


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
    ok = check_pytest()
    ok = check_ruff() and ok
    print("\n檢查通過，可以提交。" if ok else "\n檢查失敗，提交已被擋下。請先修正上面列出的問題。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
