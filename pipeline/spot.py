"""EC2 spot interruption watcher (IMDSv2 spot/instance-action, polled every 5 s)."""
from __future__ import annotations

import threading
import urllib.error
import urllib.request

IMDS = "http://169.254.169.254"


def check_once(timeout: float = 2.0) -> dict | None:
    """The instance-action document (as text under key 'raw') when a notice is pending, else None."""
    try:
        treq = urllib.request.Request(f"{IMDS}/latest/api/token", method="PUT",
                                      headers={"X-aws-ec2-metadata-token-ttl-seconds": "120"})
        with urllib.request.urlopen(treq, timeout=timeout) as r:
            token = r.read().decode()
        req = urllib.request.Request(f"{IMDS}/latest/meta-data/spot/instance-action",
                                     headers={"X-aws-ec2-metadata-token": token})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status == 200:
                return {"raw": r.read().decode("utf-8", "replace")}
    except urllib.error.HTTPError:          # 404 = no notice
        return None
    except Exception:
        return None
    return None


class SpotWatcher(threading.Thread):
    """Calls on_notice(doc) once when a spot notice appears. Use only when env == 'aws'."""

    def __init__(self, on_notice, interval: float = 5.0, check=check_once):
        super().__init__(daemon=True, name="spot-watcher")
        self.on_notice, self.interval, self.check = on_notice, interval, check
        self._stop_evt = threading.Event()
        self.notice: dict | None = None

    def stop(self):
        self._stop_evt.set()

    def run(self):
        while not self._stop_evt.wait(self.interval):
            doc = self.check()
            if doc:
                self.notice = doc
                self.on_notice(doc)
                return
