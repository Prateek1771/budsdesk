"""Focus timer (issue #7): focus -> short break -> focus ... long break every `every` rounds.

Runs in Python on the monotonic clock (each phase is a fixed deadline, so no drift and it keeps going while the
window is hidden to the tray). The UI only renders state(); on_phase(old, new) drives the ANC / music automations.
"""
import threading
import time

CMDS = ("start", "pause", "reset", "skip")
DEFAULT = {"focus": 25, "short": 5, "long": 15, "every": 4, "auto": True, "anc": True, "music": False}


def clean_cfg(cfg):
    """Merge onto the defaults and clamp: minutes 1..180, every 1..12, flags to bool. Unknown keys are dropped."""
    out = dict(DEFAULT)
    for k, v in (cfg or {}).items():
        if k not in DEFAULT:
            continue
        if isinstance(DEFAULT[k], bool):
            out[k] = bool(v)
        else:
            try:
                out[k] = max(1, min(12 if k == "every" else 180, int(v)))
            except (TypeError, ValueError):
                pass
    return out


class Focus:
    def __init__(self, on_change=None, on_phase=None, cfg=None, now=time.monotonic):
        self._change, self._phase_cb, self._now = on_change or (lambda s: None), on_phase or (lambda a, b: None), now
        self.cfg = clean_cfg(cfg)
        self._lock = threading.RLock()
        self.phase, self.round, self.running, self._left, self._ends = "idle", 1, False, self.cfg["focus"] * 60, None

    def _total(self, phase=None):
        p = phase or self.phase
        return self.cfg["focus" if p == "idle" else p] * 60

    def left(self):
        return max(0.0, self._ends - self._now()) if self.running else self._left

    def state(self):
        with self._lock:
            return {"phase": self.phase, "running": self.running, "left": round(self.left(), 2), "total": self._total(),
                    "round": self.round, "cfg": dict(self.cfg)}

    def _enter(self, phase, run):
        old, self.phase = self.phase, phase
        self._left, self.running = self._total(), run
        self._ends = self._now() + self._left if run else None
        try:
            self._phase_cb(old, phase)
        except Exception:
            pass  # an automation failing (no buds, no player) must never stop the timer

    def _advance(self):
        if self.phase == "focus":
            nxt = "long" if self.round % self.cfg["every"] == 0 else "short"
        else:
            nxt = "focus"
            if self.phase != "idle":
                self.round += 1
        self._enter(nxt, self.cfg["auto"])

    def cmd(self, name):
        with self._lock:
            if name == "start" and not self.running:
                if self.phase == "idle":
                    self._enter("focus", True)
                else:  # resume (also: the next phase waiting when auto is off)
                    self.running, self._ends = True, self._now() + self._left
            elif name == "pause" and self.running:
                self._left, self.running, self._ends = self.left(), False, None
            elif name == "reset":
                was = self.phase
                self.phase, self.round, self.running, self._ends = "idle", 1, False, None
                self._left = self._total()
                if was != "idle":
                    try:
                        self._phase_cb(was, "idle")
                    except Exception:
                        pass
            elif name == "skip" and self.phase != "idle":
                self._advance()
            else:
                return self.state()
        self._change(self.state())
        return self.state()

    def set_cfg(self, patch):
        with self._lock:
            self.cfg = clean_cfg({**self.cfg, **(patch or {})})
            if not self.running:
                self._left = self._total()  # a new length applies to the waiting phase right away
        self._change(self.state())
        return self.state()

    def tick(self):
        """Advance at the deadline. Called twice a second by the thread (and directly by the self-check)."""
        with self._lock:
            if not (self.running and self.left() <= 0):
                return False
            self._advance()
        self._change(self.state())
        return True

    def start(self):
        def loop():
            while True:
                self.tick()
                time.sleep(0.5)

        threading.Thread(target=loop, daemon=True, name="focus-timer").start()
        return self


if __name__ == "__main__":
    t = [0.0]
    calls, changes = [], []
    f = Focus(changes.append, lambda a, b: calls.append((a, b)), {"focus": 25, "short": 5, "long": 15, "every": 2}, now=lambda: t[0])
    assert f.state()["phase"] == "idle" and f.state()["left"] == 1500 and not f.tick()
    f.cmd("start"); assert calls[-1] == ("idle", "focus") and f.running
    t[0] = 600; assert f.state()["left"] == 900
    f.cmd("pause"); t[0] = 5000; assert f.state()["left"] == 900 and not f.tick()  # paused: time frozen
    f.cmd("start"); t[0] = 5000 + 899.9; assert not f.tick()
    t[0] = 5000 + 900; assert f.tick() and f.phase == "short" and calls[-1] == ("focus", "short") and f.state()["left"] == 300
    t[0] += 300; assert f.tick() and f.phase == "focus" and f.round == 2
    t[0] += 1500; assert f.tick() and f.phase == "long", f.phase  # round 2 of every=2 -> long break
    f.cmd("skip"); assert f.phase == "focus" and f.round == 3
    f.cmd("reset"); assert f.phase == "idle" and f.round == 1 and not f.running and calls[-1] == ("focus", "idle")
    f.set_cfg({"auto": False}); f.cmd("start"); t[0] += 1500; f.tick()
    assert f.phase == "short" and not f.running and f.state()["left"] == 300  # auto off: the break waits for Start
    f.cmd("start"); assert f.running
    assert clean_cfg({"focus": 0, "short": 999, "every": 50, "anc": 0, "x": 1, "long": "nope"}) == {**DEFAULT, "focus": 1, "short": 180, "every": 12, "anc": False}
    f.set_cfg({"focus": 50}); assert f.cfg["focus"] == 50 and f.cmd("bogus")["phase"] == "short"
    boom = Focus(on_phase=lambda a, b: 1 / 0, now=lambda: t[0]); boom.cmd("start"); assert boom.running  # failing hook is harmless
    assert len(changes) > 5
    print("ok")
