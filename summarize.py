# 直播重點摘要 - 階段 1
# 用法：python summarize.py 文字稿.txt --type game   （或 --type chat）
import os
import sys
import argparse

import llm  # 呼叫語言模型都在這裡

MODEL = "claude-haiku-5-5"  # 模型名稱只在這裡定義
CHUNK_CHARS = 12000         # 每段最多幾個字，超過就切段


# 外語直播時（language 不是 zh）才會被 live_topics.py 填入，加在各個提示詞裡；中文直播維持空字串，提示詞完全不變
語言說明 = ""
外語提示 = (
    "【外語說明】語音稿與聊天室留言可能是外語（日文、英文、韓文等）。所有輸出一律用繁體中文，不可出現簡體字。"
    "作品名、人名、遊戲名等專有名詞，第一次出現時附上原文，例如「艾連（エレン）」。"
    "看不懂、或轉錄疑似錯誤的詞，直接寫原文並註明「不確定」，不要硬翻。"
    "聊天室若為外語，觀眾反應也翻成繁體中文；日文聊天室常見的 w、草 代表笑。"
    "日文的漢字詞也要翻成台灣慣用的繁體中文詞（例如 赤→紅、青→藍、円→日圓、黄色→黃色），不可直接沿用日文漢字或日文字形。"
    "日文假名或外文只能出現在專有名詞後面的括號裡，正文一律用中文。"
    "正文不可夾雜英文單字，專有名詞的原文除外，原文也一樣放在括號裡。\n\n"
)


def call_llm(提示詞):
    """真正呼叫模型的程式在 llm.py。"""
    return llm.call_llm(提示詞, MODEL)


def 格式說明(類型):
    if 類型 == "chat":
        重點 = "聊過的主題、有結論的觀點、提到的推薦或事件"
    else:
        重點 = "精彩或關鍵時刻、重大決定、成敗"
    return (
        "請用繁體中文，依下面格式輸出（用 Markdown）：\n"
        "## 整場概述\n三到五句。\n"
        f"## 重點清單\n條列：{重點}。文字稿若有 [mm:ss] 或 [hh:mm:ss] 時間戳記，每個重點開頭保留對應時間。\n"
        "## 適合剪成短片的片段\n若有，列出「時間 - 一句理由」；沒有就寫「無」。\n"
        "不要編造文字稿裡沒有的內容。"
    )


聊天室規則 = (
    "聊天室留言只是輔助線索：用來判斷梗的意思、觀眾反應，以及話題是否換了。"
    "不可把聊天室內容當成實況主說的話；聊天室與語音稿矛盾時，以語音稿為準。"
)


def summarize_chunk(新文字, 上一版摘要=None, 聊天室紀錄=None, 類型="game", 格式=None):
    # 上一版摘要 目前先留位置，尚未實作
    # 聊天室紀錄：留言字串的清單（沒有就傳 None）
    # 格式：想用自己的輸出格式時傳入（不傳就用原本的整場摘要格式）
    聊天段 = ""
    if 聊天室紀錄:
        聊天段 = "\n\n聊天室留言（" + 聊天室規則 + "）：\n" + "\n".join(聊天室紀錄)
    提示詞 = (
        "你是直播重點摘要助手。以下是一場"
        + ("聊天雜談" if 類型 == "chat" else "遊戲實況")
        + "直播的文字稿（或其中一段）。\n\n"
        + 語言說明
        + (格式 or 格式說明(類型))
        + "\n\n文字稿：\n"
        + 新文字
        + 聊天段
    )
    return call_llm(提示詞)


def 切段(文字):
    """照行切，累積到 CHUNK_CHARS 就換下一段。"""
    段們, 目前, 長度 = [], [], 0
    for 行 in 文字.splitlines():
        if 長度 + len(行) > CHUNK_CHARS and 目前:
            段們.append("\n".join(目前))
            目前, 長度 = [], 0
        目前.append(行)
        長度 += len(行) + 1
    if 目前:
        段們.append("\n".join(目前))
    return 段們


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("檔案", nargs="?")
    ap.add_argument("--type", choices=["game", "chat"], default="game")
    ap.add_argument("--show-config", action="store_true", help="印出目前實際生效的設定與來源，然後結束")
    args = ap.parse_args()

    # 和 live_topics.py 讀同一份 config.json（provider、model、base_url、api_key_env）
    global MODEL
    import live_topics
    sys.stdout.reconfigure(encoding="utf-8")
    設定, 來源, 警告們 = live_topics.載入設定({})
    for w in 警告們:
        print("警告：" + w)
    llm.套用設定(設定)
    MODEL = 設定["model"]
    if args.show_config:
        live_topics.印設定(設定, 來源)
        return
    if not args.檔案:
        print("用法：python summarize.py 文字稿.txt --type game")
        sys.exit(1)

    錯誤 = llm.檢查金鑰()
    if 錯誤:
        print(錯誤)
        sys.exit(1)

    with open(args.檔案, encoding="utf-8") as f:
        文字 = f.read()

    段們 = 切段(文字)
    try:
        if len(段們) == 1:
            結果 = summarize_chunk(段們[0], 類型=args.type)
        else:
            各段 = []
            for i, 段 in enumerate(段們, 1):
                print(f"處理第 {i}/{len(段們)} 段...", file=sys.stderr)
                各段.append(summarize_chunk(段, 類型=args.type))
            合併 = "\n\n".join(f"【第 {i} 段摘要】\n{s}" for i, s in enumerate(各段, 1))
            結果 = call_llm(
                "以下是同一場直播各段落的摘要。請合併成一份完整的最終摘要，保留時間戳記。\n\n"
                + 格式說明(args.type) + "\n\n" + 合併
            )
    except llm.模型錯誤 as e:
        print(e)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已中斷。")
        sys.exit(1)

    print(結果)
    輸出檔 = os.path.splitext(args.檔案)[0] + "_摘要.md"
    with open(輸出檔, "w", encoding="utf-8") as f:
        f.write(結果)
    print(f"\n已存成：{輸出檔}", file=sys.stderr)


if __name__ == "__main__":
    main()
