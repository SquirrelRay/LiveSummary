"""開發測試用：把 Twitch VOD（直播檔）的指定時段轉成直播稿，再用「文字稿重播模式」快轉跑摘要。
不是產品功能，不接進介面。只處理音訊（不抓影片畫面、不抓 VOD 聊天室），轉錄只用本機 faster-whisper（不呼叫任何付費 API）。

用法（在專案根目錄）：
    python scripts/vod_to_transcript.py https://www.twitch.tv/videos/2898838036 --start 0:06:25 --end 1:30:00 --lang ja
    python scripts/vod_to_transcript.py https://www.twitch.tv/videos/2850504790 --end 1:30:00 --lang auto

流程：streamlink 只下載指定時段的音訊（--hls-start-offset／--hls-duration，不下載整支再裁切）
      → ffmpeg 轉 16kHz 單聲道 wav → 本機 Whisper 轉錄 → 寫成直播稿。
時間戳是 VOD 內的原始時間（第二支從 6:25 附近開始，不是 0:00；超過 1 小時用 h:mm:ss），和 Twitch 播放器對得上。
產生的檔案放在專案的 測試素材/（已被 .gitignore 忽略）。
VOD 的 HLS 分段約 10 秒，streamlink 只能從分段邊界開始，所以實際起點可能比 --start 晚幾秒：
本腳本讀 VOD 的播放清單算出實際起點，時間戳以實際起點為準，並寫在直播稿開頭的說明行。
"""
import argparse
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
import timefmt

預設資料夾 = ROOT / "測試素材"
語言們 = config.語言代碼們          # zh、ja、en、ko、auto


# ---------- 純函式（測試用假資料測這些）----------
def 解析時間(字):
    """「1:30:00」「6:25」「90」→ 秒數。兩段式是 分:秒（和直播稿的 [06:25] 一樣）。讀不懂丟出 ValueError。"""
    字 = str(字).strip()
    if not re.fullmatch(r"\d+(:\d{1,2}){0,2}(\.\d+)?", 字):
        raise ValueError(f"時間格式不對：{字!r}（例如 0:06:25、6:25、90）")
    秒 = 0.0
    for 段 in 字.split(":"):
        秒 = 秒 * 60 + float(段)
    return 秒


def 時間代號(秒):
    """檔名用：0h06m25s。"""
    秒 = int(秒)
    return f"{秒 // 3600}h{秒 % 3600 // 60:02d}m{秒 % 60:02d}s"


def vod編號(網址):
    m = re.search(r"/videos/(\d+)", 網址) or re.fullmatch(r"\s*(\d+)\s*", 網址)
    if not m:
        raise ValueError(f"看不出 VOD 編號：{網址!r}（網址應像 https://www.twitch.tv/videos/2898838036）")
    return m.group(1)


def 時間參數(秒):
    """streamlink 的時間參數 HH:MM:SS。"""
    秒 = max(0, round(秒))
    return f"{秒 // 3600:02d}:{秒 % 3600 // 60:02d}:{秒 % 60:02d}"


def 分段長度們(播放清單文字):
    """HLS 播放清單裡每個分段的秒數（照順序）。"""
    return [float(m.group(1)) for m in re.finditer(r"^#EXTINF:([\d.]+)", 播放清單文字, re.MULTILINE)]


def 算實際起點(播放清單文字, 起點):
    """streamlink 的 --hls-start-offset 規則（duration_to_sequence）：累計前面分段的秒數，
    第一次 >= 起點的那個分段開始。回傳這個分段在 VOD 內的起點秒數；播放清單讀不到分段就回傳 起點 本身。"""
    長度們 = 分段長度們(播放清單文字)
    if not 長度們:
        return 起點
    累計 = 0.0
    for 長度 in 長度們:
        if 累計 >= 起點:
            return 累計
        累計 += 長度
    return 累計 - 長度們[-1]       # 起點超過 VOD 結尾：streamlink 會停在最後一個分段


def 過濾段(s):
    """和 live_capture.轉錄一段 同一套規則：幻聽、沒人講話、重複度太高的段不要。回傳整理後的文字或 None。"""
    import live_capture
    文字 = s.text.strip()
    if not 文字 or live_capture.是幻聽(文字):
        return None
    if (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0) or s.compression_ratio > 2.4:
        return None
    return 文字


def 段轉行們(段們, 起點):
    """Whisper 的段落 → 直播稿的行（[h:mm:ss] 文字）。時間 = 起點 + 段內秒數；跟上一句一模一樣的跳過（多半是亂猜）。"""
    行們, 上一句 = [], ""
    for s in 段們:
        文字 = 過濾段(s)
        if 文字 is None or 文字 == 上一句:
            continue
        上一句 = 文字
        行們.append(f"{timefmt.標記(起點 + s.start)} {文字}")
    return 行們


def 直播稿開頭(網址, 要求起, 要求訖, 實際起, 語言說明):
    """「# 」開頭的說明行（文字稿重播模式讀檔時會略過這些行）。"""
    return [
        f"# 開發測試用：Twitch VOD 轉出的直播稿（{網址}）",
        (f"# 時段：要求 {timefmt.秒轉字(要求起)}～{timefmt.秒轉字(要求訖) if 要求訖 else 'VOD 結尾'}；"
         f"實際音訊從 {timefmt.秒轉字(實際起)} 開始（VOD 分段邊界）。時間戳是 VOD 內的原始時間。"),
        f"# 語言：{語言說明}；本機 Whisper 轉錄，沒有呼叫任何 API",
        "",
    ]


# ---------- 會連網、跑外部程式、跑模型的部分（測試時換成假的）----------
def 取得播放清單(網址, 串流名="audio_only"):
    """用 streamlink 找到音訊串流的播放清單網址，讀回內容（VOD 的完整分段清單）。"""
    from streamlink import Streamlink
    串流們 = Streamlink().streams(網址)
    if 串流名 not in 串流們:
        raise RuntimeError("這支 VOD 沒有音訊串流（可能已刪除、需要訂閱或登入）。")
    # 網址是 streamlink 從 Twitch 解析出來的 https 播放清單
    with urllib.request.urlopen(串流們[串流名].url, timeout=20) as r:    # noqa: S310
        return r.read().decode("utf-8", "replace")


def 下載音訊(網址, 起點, 時長, 輸出, 執行=subprocess.run):
    """只下載 起點 開始、約 時長 秒的音訊（streamlink 依播放清單只抓需要的分段）。時長 None = 到 VOD 結尾。"""
    指令 = [sys.executable, "-m", "streamlink_cli", "--loglevel", "warning", "--force",
          "--hls-start-offset", 時間參數(起點)]
    if 時長 is not None:
        指令 += ["--hls-duration", 時間參數(時長)]
    指令 += ["-o", str(輸出), 網址, "audio_only"]
    r = 執行(指令, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if r.returncode != 0 or not Path(輸出).exists() or Path(輸出).stat().st_size == 0:
        raise RuntimeError("下載音訊失敗：" + ((r.stderr or r.stdout or "").strip()[-300:] or f"結束碼 {r.returncode}"))


def 轉成wav(來源, 輸出, ffmpeg, 執行=subprocess.run):
    指令 = [ffmpeg, "-y", "-loglevel", "error", "-i", str(來源), "-vn", "-ac", "1", "-ar", "16000", str(輸出)]
    r = 執行(指令, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 轉檔失敗：" + (r.stderr or "").strip()[-300:])


def 載入模型(語言):
    """本機 Whisper：顯示卡優先，失敗退回 CPU（沿用 live_capture 的作法）。"""
    import events
    import live_capture
    import transcribe
    if events.印到終端機 not in events.接收者們:
        events.接收者們.append(events.印到終端機)
    transcribe.GPU_MODEL = config.目前設定()["whisper_model"]
    return live_capture.載入模型(語言)


def 轉錄(wav, 起點, 語言, 模型=None, 進度=print):
    """回傳 (行們, 語言代碼, 說明)。語言 auto = 用 5 段音訊投票偵測。"""
    import live_capture
    model = 模型 or 載入模型(語言)
    自動 = 語言 == config.自動
    段們, 資訊 = model.transcribe(
        str(wav), language=None if 自動 else 語言, vad_filter=True, condition_on_previous_text=False,
        initial_prompt=live_capture.中文提示 if 語言 == "zh" else None,
        **({"language_detection_segments": 5} if 自動 else {}))
    語 = 資訊.language if 自動 else 語言
    說明 = f"{語}（自動偵測，信心 {資訊.language_probability:.2f}）" if 自動 else f"{語}（手動指定）"

    下個進度 = [300]

    def 看進度(串):
        for s in 串:
            if s.end >= 下個進度[0]:
                進度(f"  轉錄進度：音訊 {timefmt.秒轉字(s.end)}")
                下個進度[0] += 300
            yield s
    return 段轉行們(看進度(段們), 起點), 語, 說明


# ---------- 主流程 ----------
def 處理(網址, 起點=0.0, 終點=None, 語言="auto", 資料夾=預設資料夾, 保留音訊=True, 取清單=取得播放清單,
       下載=下載音訊, 轉檔=轉成wav, 轉錄函式=轉錄, 找ffmpeg=None, 進度=print):
    """下載、轉檔、轉錄、寫檔。回傳 結果 dict（稿路徑、實際起點、行數、語言、花的秒數）。各步驟可換成假的來測試。"""
    if 終點 is not None and 終點 <= 起點:
        raise ValueError("--end 必須比 --start 晚。")
    編號 = vod編號(網址)
    資料夾 = Path(資料夾)
    資料夾.mkdir(parents=True, exist_ok=True)
    基底 = f"vod{編號}_{時間代號(起點)}-{時間代號(終點) if 終點 else 'end'}"
    ts, wav, 稿 = 資料夾 / f"{基底}.ts", 資料夾 / f"{基底}.wav", 資料夾 / f"{基底}_直播稿.txt"

    開始 = time.time()
    try:
        實際起 = 算實際起點(取清單(網址), 起點)
    except Exception as e:     # noqa: BLE001  讀不到播放清單：改用要求的起點
        進度(f"警告：讀不到播放清單（{type(e).__name__}），時間戳以要求的起點為準，可能差一個分段（約 10 秒）。")
        實際起 = 起點
    時長 = None if 終點 is None else max(終點 - 實際起, 1)
    進度(f"下載音訊：{timefmt.秒轉字(實際起)}～{timefmt.秒轉字(終點) if 終點 else 'VOD 結尾'}（要求起點 {timefmt.秒轉字(起點)}）")
    下載(網址, 起點, 時長, ts)
    進度(f"  下載完成：{ts.stat().st_size / 1024 ** 2:.1f} MB，用了 {time.time() - 開始:.0f} 秒")

    if 找ffmpeg is None:
        import live_capture
        找ffmpeg = live_capture.找ffmpeg
    轉檔(ts, wav, 找ffmpeg())
    ts.unlink(missing_ok=True)

    轉錄開始 = time.time()
    進度("轉錄中（本機 Whisper）…")
    行們, 語, 說明 = 轉錄函式(wav, 實際起, 語言)
    轉錄秒 = time.time() - 轉錄開始
    if not 保留音訊:
        wav.unlink(missing_ok=True)
    with open(稿, "w", encoding="utf-8") as f:
        f.write("\n".join(直播稿開頭(網址, 起點, 終點, 實際起, 說明)))
        f.write("\n".join(行們) + ("\n" if 行們 else ""))
    return {"稿": 稿, "wav": wav, "實際起點": 實際起, "行數": len(行們), "語言": 說明, "語言代碼": 語,
            "下載秒": 轉錄開始 - 開始, "轉錄秒": 轉錄秒, "總秒": time.time() - 開始}


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="開發測試用：Twitch VOD 指定時段 → 直播稿（只下載音訊、本機轉錄、不花 API 費用）")
    ap.add_argument("網址", help="https://www.twitch.tv/videos/編號")
    ap.add_argument("--start", default="0", help="起點，例如 0:06:25 或 6:25（預設從 0 開始）")
    ap.add_argument("--end", help="終點，例如 1:30:00（不給就到 VOD 結尾）")
    ap.add_argument("--lang", default="auto", choices=語言們, help="轉錄語言，auto = 自動偵測（預設）")
    ap.add_argument("--out", default=str(預設資料夾), help="輸出資料夾（預設 測試素材/，已被 .gitignore 忽略）")
    ap.add_argument("--no-keep-audio", action="store_true", help="轉錄完刪掉 wav（預設保留）")
    args = ap.parse_args(argv)
    try:
        起 = 解析時間(args.start)
        訖 = 解析時間(args.end) if args.end else None
        結果 = 處理(args.網址, 起, 訖, args.lang, args.out, not args.no_keep_audio)
    except (ValueError, RuntimeError) as e:
        print(f"失敗：{e}")
        return 1
    print(f"\n完成：{結果['稿']}\n  實際起點 {timefmt.秒轉字(結果['實際起點'])}；{結果['行數']} 行；語言 {結果['語言']}；"
          f"下載 {結果['下載秒']:.0f} 秒、轉錄 {結果['轉錄秒']:.0f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
