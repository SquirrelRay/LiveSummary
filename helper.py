# 打包版的命令列版 exe（helper.exe）進入點：主程式另開程序時用（指令由 external.py 組）。
#   helper.exe --streamlink 參數…        = streamlink 命令列（python -m streamlink_cli 參數…）
#   helper.exe --yt-audio 網址 串流名     = python yt_audio.py 網址 串流名
# 為什麼要另一個 exe：打包後 sys.executable 是主程式（無視窗）exe，不能 -m streamlink_cli；
# 命令列版 exe 用管線傳二進位 stdout 一定可靠。和主程式共用同一個打包資料夾（_internal）。開發時不用它（external.py 直接用 python）。
import sys

用法 = "用法：helper --streamlink 參數… ／ helper --yt-audio 網址 串流名"


def main(參數):
    if 參數[:1] == ["--streamlink"]:
        from streamlink_cli.main import main as streamlink主程式
        sys.argv = ["streamlink", *參數[1:]]
        return streamlink主程式()
    if 參數[:1] == ["--yt-audio"] and len(參數) == 3:
        import yt_audio
        return yt_audio.main(參數[1:])
    print(用法, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
