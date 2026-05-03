import faulthandler
import sys
import threading
import time
import datetime
import os
import re
from collections import Counter


class MainLoopStallWatchdog:
    def __init__(self, threshold_ms=200, cooldown_ms=800, print_top_n=5):
        self.threshold_s = threshold_ms / 1000.0
        self.cooldown_s = cooldown_ms / 1000.0
        self.print_top_n = print_top_n

        self._last_beat = time.monotonic()
        self._last_dump = 0.0
        self._stop = False

        self._culprits = Counter()
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._t.start()

    def stop(self):
        self._stop = True

    def beat(self):
        self._last_beat = time.monotonic()

    def _read_faulthandler_dump(self) -> str:
        rfd, wfd = os.pipe()
        try:
            with os.fdopen(wfd, "w") as wf:
                faulthandler.dump_traceback(file=wf, all_threads=True)
            with os.fdopen(rfd, "r") as rf:
                return rf.read()
        finally:
            # fdopen closes its fd, but be safe in case of exceptions before context managers
            try:
                os.close(rfd)
            except OSError:
                pass
            try:
                os.close(wfd)
            except OSError:
                pass

    def _extract_main_thread_culprit(self, text: str) -> str | None:
        blocks = text.split("Thread ")
        for b in blocks:
            if "fabric/core/application.py" in b and " in run" in b:
                m = re.search(r'  File "([^"]+)", line (\d+) in ([^\n]+)', b)
                if m:
                    path, line, fn = m.group(1), m.group(2), m.group(3)
                    return f"{path}:{line} in {fn}"
        m = re.search(r'  File "([^"]+)", line (\d+) in ([^\n]+)', text)
        if m:
            path, line, fn = m.group(1), m.group(2), m.group(3)
            return f"{path}:{line} in {fn}"
        return None

    def _dump(self, gap_s: float):
        text = self._read_faulthandler_dump()
        culprit = self._extract_main_thread_culprit(text)
        if culprit:
            self._culprits[culprit] += 1

        ts = datetime.datetime.now().strftime("%H:%M:%S:%f")
        print(
            f"{ts} STALL gap={gap_s*1000:.1f}ms culprit={culprit}",
            file=sys.stderr,
            flush=True,
        )
        print(text, file=sys.stderr, flush=True)

        top = self._culprits.most_common(self.print_top_n)
        if top:
            print(
                f"{ts} stall culprits top{self.print_top_n}:",
                file=sys.stderr,
                flush=True,
            )
            for k, v in top:
                print(f"  {v:4d}  {k}", file=sys.stderr, flush=True)

    def _run(self):
        while not self._stop:
            time.sleep(self.threshold_s / 4)
            now = time.monotonic()
            gap = now - self._last_beat
            if gap > self.threshold_s and (now - self._last_dump) >= self.cooldown_s:
                self._last_dump = now
                self._dump(gap)


watchdog = MainLoopStallWatchdog(threshold_ms=200, cooldown_ms=800)
watchdog.start()
