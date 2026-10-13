# YouTube 音訊擷取：和「streamlink --stdout 網址 串流名」完全一樣把音訊送到 stdout，
# 另外在 stderr 印一行「PDT 段號 epoch秒」：第一個寫出的 HLS 片段在直播端的實際時刻（#EXT-X-PROGRAM-DATE-TIME）。
# live_capture 用它算第一段音訊的直播時間（= PDT − 開播時間），不靠估計的串流延遲；讀不到就不印（改用延遲常數）。
# YouTube 的播放清單只在第一段標 PDT，後面的片段用「前一段的 PDT + 片段長度」往下推。
# 用法：python yt_audio.py 網址 串流名（live_capture 自己呼叫；直接執行檔案，專案資料夾不必是目前資料夾）
import sys

PDT字首 = "PDT "


def 推算片段時刻(片段們):
    """播放清單的片段們 → {段號: PDT(epoch 秒)}；沒有任何 PDT 標記就是空的。"""
    結果, 時刻 = {}, None
    for 片段 in 片段們:
        if 片段.date is not None:
            時刻 = 片段.date.timestamp()
        if 時刻 is not None:
            結果[片段.num] = 時刻
            時刻 += 片段.duration
    return 結果


def 解析PDT行(行):
    """stderr 的一行 → PDT(epoch 秒)；不是 PDT 行或讀不懂回傳 None。"""
    if not 行.startswith(PDT字首):
        return None
    try:
        return float(行.split()[2])
    except (IndexError, ValueError):
        return None


def 掛上記錄():
    from streamlink.stream.hls import hls

    原本處理 = hls.HLSStreamWorker.process_segments
    原本寫 = hls.HLSStreamWriter.write

    def 處理(self, playlist):
        self._片段時刻 = {**getattr(self, "_片段時刻", {}), **推算片段時刻(playlist.segments)}
        return 原本處理(self, playlist)

    def 寫(self, segment, result, *資料):
        if not getattr(self, "_印過PDT", False):
            self._印過PDT = True
            時刻 = getattr(self.reader.worker, "_片段時刻", {}).get(segment.num)
            if 時刻 is not None:
                print(f"{PDT字首}{segment.num} {時刻:.3f}", file=sys.stderr, flush=True)
        return 原本寫(self, segment, result, *資料)

    hls.HLSStreamWorker.process_segments = 處理
    hls.HLSStreamWriter.write = 寫


def main(參數):
    掛上記錄()
    from streamlink_cli.main import main as streamlink主程式
    sys.argv = ["streamlink", "--loglevel", "error", "--stdout", *參數]
    streamlink主程式()


if __name__ == "__main__":
    main(sys.argv[1:])
