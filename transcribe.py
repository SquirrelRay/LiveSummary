# 直播轉文字 - 階段 2
# 用法：python transcribe.py 影片或音訊檔路徑
#       python transcribe.py https://www.twitch.tv/videos/xxxx   （公開影片網址）
#       加 --lang ja（或 en、ko、zh、auto）可轉錄外語，預設 zh
# 輸出：每行 [mm:ss] 文字 的 .txt，可直接給 summarize.py 使用
import os
import sys
import tempfile

import app_paths
import config
import timefmt

GPU_MODEL = config.出廠預設()["whisper_model"]  # 用顯示卡時的模型（比 medium 更快、更省記憶體）；live_topics.執行() 依設定改寫
CPU_MODEL = "small"   # 用 CPU 時換小一點，不然太慢


def 時間(秒):
    """[mm:ss]／[h:mm:ss]：格式統一由 timefmt 決定。"""
    return timefmt.標記(秒)


def 下載音訊(網址, 資料夾):
    import yt_dlp
    設定 = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(資料夾, "%(id)s.%(ext)s"),
        "quiet": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(設定) as ydl:
            資訊 = ydl.extract_info(網址, download=True)
            return ydl.prepare_filename(資訊), 資訊.get("id", "影片")
    except Exception as e:
        訊息 = str(e).lower()
        if any(k in 訊息 for k in ["subscriber", "sign in", "login", "private", "members"]):
            print("這部影片需要登入或訂閱才能看，這個工具只支援公開影片。")
        else:
            print(f"下載失敗：{e}")
        sys.exit(1)


_加過 = set()       # 已經加過的顯示卡函式庫資料夾


def 找顯示卡函式庫():
    """告訴系統去哪找 CUDA 函式庫（cuBLAS）：位置由 app_paths.顯示卡函式庫資料夾們 決定
    （開發 site-packages\\nvidia\\*\\bin、打包版 _internal\\nvidia\\*\\bin）。
    os.add_dll_directory 和 PATH 兩個都要加：只加前者實測會找不到 cublas64_12.dll（見 docs/打包調查.md）。
    可以重複呼叫：加過的資料夾不再加（PATH 不會越來越長）。"""
    for bin路徑 in app_paths.顯示卡函式庫資料夾們():
        if bin路徑 in _加過:
            continue
        os.add_dll_directory(bin路徑)
        os.environ["PATH"] = bin路徑 + os.pathsep + os.environ.get("PATH", "")
        _加過.add(bin路徑)


def 轉錄(音檔, 語言="zh"):
    找顯示卡函式庫()
    from faster_whisper import WhisperModel

    def 跑(裝置, 計算型態, 模型):
        model = WhisperModel(模型, device=裝置, compute_type=計算型態)
        段們, 資訊 = model.transcribe(音檔, language=None if 語言 == "auto" else 語言, vad_filter=True,
                                  initial_prompt="以下是繁體中文的直播逐字稿。" if 語言 == "zh" else None)
        if 語言 == "auto":
            print(f"偵測到語言：{資訊.language}")
        return [f"{時間(s.start)} {s.text.strip()}" for s in 段們]  # 這裡才會真的開始算

    try:
        return 跑("cuda", "float16", GPU_MODEL)
    except Exception as e:
        print(f"顯示卡（GPU）無法使用（{type(e).__name__}: {e}），改用 CPU，會比較慢。")
        return 跑("cpu", "int8", CPU_MODEL)


def main():
    參數 = sys.argv[1:]
    語言 = "zh"
    if "--lang" in 參數:
        i = 參數.index("--lang")
        語言 = 參數[i + 1] if i + 1 < len(參數) else ""
        參數 = 參數[:i] + 參數[i + 2:]
    if len(參數) != 1 or 語言 not in config.語言代碼們:
        print("用法：python transcribe.py 檔案路徑或網址 [--lang " + "|".join(config.語言代碼們) + "]")
        sys.exit(1)
    來源 = 參數[0]
    sys.stdout.reconfigure(encoding="utf-8")

    with tempfile.TemporaryDirectory() as 暫存:
        if 來源.startswith("http"):
            print("下載音訊中...")
            音檔, 名稱 = 下載音訊(來源, 暫存)
            os.makedirs(app_paths.輸出資料夾(), exist_ok=True)
            輸出檔 = os.path.join(app_paths.輸出資料夾(), f"直播_{名稱}.txt")
        else:
            if not os.path.exists(來源):
                print(f"找不到檔案：{來源}")
                sys.exit(1)
            音檔 = 來源
            輸出檔 = os.path.splitext(來源)[0] + ".txt"
        print("轉錄中（第一次會先下載模型，需要一點時間）...")
        行們 = 轉錄(音檔, 語言)

    with open(輸出檔, "w", encoding="utf-8") as f:
        f.write("\n".join(行們) + "\n")
    print(f"完成：{輸出檔}（共 {len(行們)} 行）")


if __name__ == "__main__":
    main()
