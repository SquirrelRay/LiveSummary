"""開發／整理詞庫用：把指定直播主詞庫裡「還沒查過的候選」上網查證一遍（不跑直播、不做摘要）。
規則和直播中的上網查證一樣（web_verify.py）：查到可靠的台灣通行寫法 → 改成「上網」並附來源網址；
查無 → 保持候選、標「已查」，之後不再查；沒查成（逾時、錯誤）→ 不改，下次再查。手動、上網的詞條不動。
會呼叫付費 API（模型與上網搜尋照 config.json；只支援 provider = anthropic）；每次最多查 --max 個（預設 web_verify.每場上限）。

用法（在專案根目錄）：
    python scripts/verify_glossary.py test_vod2850504790 --transcript 測試素材/vod2850504790_0h00m00s-1h30m00s_直播稿.txt
    python scripts/verify_glossary.py abc --max 5 --category "Minecraft"
--transcript 用來找「名詞在稿裡出現的那一兩句」給模型當脈絡；沒給就找專案資料夾裡 直播主_*_直播稿.txt。
"""
import argparse
import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_paths
import config
import glossary
import llm
import model_catalog
import web_verify


def 讀稿(路徑們):
    行們 = []
    for 路徑 in 路徑們:
        try:
            with open(路徑, encoding="utf-8") as f:
                行們 += [l.rstrip("\n") for l in f if l.strip() and not l.startswith("# ")]
        except OSError as e:
            print(f"讀不到直播稿 {路徑}（{e}），略過")
    return 行們


def 跑(直播主, 稿行們, 脈絡, 模型, 上限, 印=print):
    """查一遍，回傳計數 dict（查、確認、查無、失敗）。"""
    詞庫 = glossary.詞庫(glossary.檔名安全(直播主))
    if 詞庫.讀錯誤:
        印(f"詞庫讀不到（{詞庫.讀錯誤}）：{詞庫.路徑}")
        return None
    待查 = 詞庫.待查證們()
    印(f"詞庫：{詞庫.路徑}，還沒查過的候選 {len(待查)} 個，這次最多查 {上限} 個")
    計數 = {"查": 0, "確認": 0, "查無": 0, "失敗": 0, "略過": max(0, len(待查) - 上限)}
    for e in 待查[:上限]:
        計數["查"] += 1
        狀態, 字 = web_verify.查一個(詞庫, e, 脈絡, 稿行們, 模型)
        計數[狀態] += 1
        印(f"[{狀態}] {字}")
    return 計數


def main():
    ap = argparse.ArgumentParser(description="上網查證指定直播主詞庫裡還沒查過的候選（開發／整理詞庫用，會花 API 費用）")
    ap.add_argument("直播主")
    ap.add_argument("--max", type=int, default=web_verify.每場上限, help=f"最多查幾個（預設 {web_verify.每場上限}）")
    ap.add_argument("--transcript", action="append", default=[], help="直播稿（可給多個）；用來找名詞出現的句子")
    ap.add_argument("--category", default="", help="直播分類／遊戲（給模型當脈絡）")
    ap.add_argument("--title", default="", help="直播標題（給模型當脈絡）")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    設定, _, 警告們 = config.載入設定()
    for w in 警告們:
        print("警告：" + w)
    llm.套用設定(設定)
    if not llm.支援上網查證():
        print(f"上網查證無法使用：目前的模型服務（{設定['provider']}）沒有支援的上網搜尋工具。")
        sys.exit(1)
    錯誤 = llm.檢查金鑰()
    if 錯誤:
        print(錯誤)
        sys.exit(1)
    稿們 = args.transcript or sorted(glob.glob(os.path.join(glob.escape(app_paths.輸出資料夾()), f"{glossary.檔名安全(args.直播主)}_*_直播稿.txt")))
    print(f"直播稿：{'、'.join(稿們) or '（沒有，只用名詞本身查）'}")
    脈絡 = {"直播主": args.直播主, "分類": args.category, "標題": args.title}
    try:
        計數 = 跑(args.直播主, 讀稿(稿們), 脈絡, 設定["model"], max(0, args.max))
    except llm.模型錯誤 as e:
        print(e)
        sys.exit(1)
    if 計數 is None:
        sys.exit(1)
    print(web_verify.結束文字(計數, max(0, args.max)) + "；" + llm.查證用量文字(*(model_catalog.單價(設定) or (None, None))))


if __name__ == "__main__":
    main()
