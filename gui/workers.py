import threading
import traceback

from PySide6.QtCore import QThread, Signal

from collectors.router_collector import collect_for_duration
from collectors.isp_collector import run as run_isp
from analysis.snapshot_differ import main as run_snapshot_differ
from analysis.dataset_builder import main as run_dataset_builder
from analysis.explore import main as run_explore
from ml.train import main as run_train
from ml.predict import main as run_predict


class _BaseWorker(QThread):
    log = Signal(str)
    done = Signal(bool)  # True = success, False = error / no-data

    def _emit(self, text: str) -> None:
        self.log.emit(str(text).rstrip())

    def _run_module(self, name: str, func) -> bool:
        self._emit(f"\n{'='*60}")
        self._emit(f"  {name}")
        self._emit("=" * 60)
        try:
            func()
            return True
        except SystemExit as e:
            if e.code == 2:
                self._emit(f"⏸ {name} skipped (no data yet).")
            else:
                self._emit(f"!! {name} exited with code {e.code}")
            return False
        except Exception as e:
            self._emit(f"!! {name} failed: {e}")
            self._emit(traceback.format_exc())
            return False


class RouterCollectorWorker(_BaseWorker):
    """Runs the router collection loop until stopped."""

    def __init__(self, hours: float, interval: int):
        super().__init__()
        self.hours = hours
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self):
        self._emit(f"Starting router collection for {self.hours}h ...")
        try:
            collect_for_duration(
                hours=self.hours,
                interval=self.interval,
                stop_event=self._stop_event,
            )
            self._emit("Router collection finished.")
            self.done.emit(True)
        except Exception as e:
            self._emit(f"Router collection error: {e}")
            self._emit(traceback.format_exc())
            self.done.emit(False)

    def stop(self):
        self._stop_event.set()
        self._emit("Stop signal sent — waiting for current scan to end...")


class IspCollectorWorker(_BaseWorker):
    """Runs the ISP scraper once."""

    def run(self):
        try:
            run_isp()
            self.done.emit(True)
        except Exception as e:
            self._emit(f"ISP error: {e}")
            self._emit(traceback.format_exc())
            self.done.emit(False)


class IspLoginWorker(_BaseWorker):
    """
    Opens a browser for manual ISP login (username, password, CAPTCHA).
    Stays alive until `save_session()` is called from the GUI,
    then saves the storage state to data/isp_state.json.
    """

    def __init__(self):
        super().__init__()
        self._save_event = threading.Event()
        self._cancel_event = threading.Event()

    def run(self):
        from playwright.sync_api import sync_playwright
        from config.settings import (
            CHROME_PATH, ISP_LOGIN_URL, ISP_STATE_FILE, VIEWPORT,
        )

        ISP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    executable_path=CHROME_PATH,
                )
                try:
                    ctx = browser.new_context(viewport=VIEWPORT)
                    page = ctx.new_page()

                    self._emit(f"Opening: {ISP_LOGIN_URL}")
                    page.goto(
                        ISP_LOGIN_URL,
                        wait_until="networkidle",
                        timeout=60_000,
                    )
                    self._emit("مرورگر باز شد. لطفاً وارد پنل آسیاتک شوید.")
                    self._emit("بعد از ورود موفق، دکمهٔ «💾 ذخیره نشست» را بزنید.")

                    # Wait until user clicks save (or cancels)
                    while not self._save_event.is_set():
                        if self._cancel_event.is_set():
                            self._emit("لغو شد.")
                            self.done.emit(False)
                            return
                        self._save_event.wait(timeout=0.5)

                    ctx.storage_state(path=str(ISP_STATE_FILE))
                    self._emit(f"✓ نشست ذخیره شد: {ISP_STATE_FILE}")
                    self.done.emit(True)

                except Exception as e:
                    self._emit(f"Login error: {e}")
                    self._emit(traceback.format_exc())
                    self.done.emit(False)
                finally:
                    browser.close()

        except Exception as e:
            self._emit(f"Playwright error: {e}")
            self.done.emit(False)

    def save_session(self):
        self._save_event.set()

    def cancel(self):
        self._cancel_event.set()


class AnalysisWorker(_BaseWorker):
    """
    Runs the full analysis chain:
        snapshot_differ → dataset_builder → explore → train → predict
    """

    def run(self):
        chain = [
            ("analysis.snapshot_differ", run_snapshot_differ),
            ("analysis.dataset_builder", run_dataset_builder),
            ("analysis.explore", run_explore),
            ("ml.train", run_train),
            ("ml.predict", run_predict),
        ]

        for name, func in chain:
            ok = self._run_module(name, func)
            if not ok:
                self._emit("\n⏸ Analysis chain stopped (no data yet).")
                self.done.emit(False)
                return

        self._emit("\n✓ Full analysis chain completed.")
        self.done.emit(True)