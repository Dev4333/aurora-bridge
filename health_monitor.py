"""Health Monitor — system tray icon with connection status.

Shows green/yellow/red status:
- Green: SSE connected, MT5 files accessible
- Yellow: Polling fallback (SSE disconnected but still receiving)
- Red: Disconnected or MT5 files inaccessible
"""

import logging
import os
import sys
import threading
from pathlib import Path
from enum import Enum

logger = logging.getLogger("aurora-bridge")


class HealthStatus(Enum):
    CONNECTED = "connected"      # green — SSE active
    POLLING = "polling"          # yellow — polling fallback
    DISCONNECTED = "disconnected"  # red — no connection
    MT5_ERROR = "mt5_error"      # red — can't write to MT5


class HealthMonitor:
    """Monitors connection health and shows system tray icon."""

    def __init__(self, mt5_files_path: str | None = None):
        self.mt5_files_path = mt5_files_path
        self.status = HealthStatus.DISCONNECTED
        self._tray_icon = None
        self._tray_thread = None

    def update_status(self, status: HealthStatus):
        """Update the health status and tray icon."""
        if status != self.status:
            self.status = status
            logger.info(f"Status: {status.value}")
            self._update_tray_icon()

    def check_mt5_access(self) -> bool:
        """Check if MT5 files directory is accessible."""
        if not self.mt5_files_path:
            return False
        p = Path(self.mt5_files_path)
        return p.exists() and os.access(str(p), os.W_OK)

    def start_tray(self, on_quit: callable = None):
        """Start system tray icon (Windows only)."""
        if sys.platform != "win32":
            logger.info("System tray not available on this platform")
            return

        try:
            import pystray
            from PIL import Image, ImageDraw

            def create_icon(color: str) -> Image.Image:
                img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                colors = {
                    "green": (34, 197, 94),
                    "yellow": (234, 179, 8),
                    "red": (239, 68, 68),
                    "gray": (107, 114, 128),
                }
                c = colors.get(color, colors["gray"])
                draw.ellipse([8, 8, 56, 56], fill=c)
                # "A" for Aurora
                draw.text((22, 16), "A", fill=(255, 255, 255))
                return img

            self._create_icon = create_icon

            menu = pystray.Menu(
                pystray.MenuItem("Aurora Bridge Agent", lambda: None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    lambda item: f"Status: {self.status.value}",
                    lambda: None,
                    enabled=False,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda: on_quit() if on_quit else sys.exit(0)),
            )

            self._tray_icon = pystray.Icon(
                "aurora-bridge",
                create_icon("gray"),
                "Aurora Bridge Agent",
                menu,
            )

            self._tray_thread = threading.Thread(
                target=self._tray_icon.run,
                daemon=True,
            )
            self._tray_thread.start()
            logger.info("System tray icon started")

        except ImportError:
            logger.info("pystray not available — running without tray icon")
        except Exception as e:
            logger.warning(f"Failed to start tray icon: {e}")

    def _update_tray_icon(self):
        """Update tray icon color based on status."""
        if not self._tray_icon or not hasattr(self, '_create_icon'):
            return

        color_map = {
            HealthStatus.CONNECTED: "green",
            HealthStatus.POLLING: "yellow",
            HealthStatus.DISCONNECTED: "red",
            HealthStatus.MT5_ERROR: "red",
        }
        try:
            color = color_map.get(self.status, "gray")
            self._tray_icon.icon = self._create_icon(color)
            self._tray_icon.title = f"Aurora Bridge — {self.status.value}"
        except Exception:
            pass

    def stop(self):
        """Stop the tray icon."""
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
