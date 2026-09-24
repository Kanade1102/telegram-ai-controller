"""Screenshot capture service supporting browser-native, Wayland, and X11 captures.

Screenshots default to browser-native (`page.screenshot`) to protect desktop privacy.
"""

import os
import shutil
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from config import settings

logger = logging.getLogger(__name__)


class ScreenshotService:
    def __init__(self, mode: Optional[str] = None, output_dir: Optional[Path] = None):
        self.mode = mode or settings.screenshot_mode
        self.output_dir = output_dir or settings.screenshot_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _generate_filepath(self, prefix: str = "shot") -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        return self.output_dir / f"{prefix}_{timestamp}.png"

    def is_wayland(self) -> bool:
        """Detect if the current environment is running under Wayland."""
        return (
            os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            or bool(os.environ.get("WAYLAND_DISPLAY"))
        )

    async def capture(self, page=None, force_mode: Optional[str] = None) -> Optional[str]:
        """Capture screenshot according to configured mode or force_mode."""
        target_mode = force_mode or self.mode
        filepath = self._generate_filepath()
        str_path = str(filepath)

        # 1. Browser-native mode (preferred & default)
        if target_mode == "browser" and page is not None:
            try:
                await page.screenshot(path=str_path, full_page=False)
                if filepath.is_file() and filepath.stat().st_size > 0:
                    return str_path
            except Exception as e:
                logger.warning("Browser-native screenshot failed: %s. Falling back to desktop.", e)

        # 2. Window / Desktop mode
        return await self._capture_desktop(str_path)

    async def _capture_desktop(self, output_path: str) -> Optional[str]:
        """Capture entire desktop using system utilities (Wayland grim / X11 scrot / ImageMagick / PIL)."""
        is_wl = self.is_wayland()

        # A. Wayland with grim
        if is_wl and shutil.which("grim"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "grim", output_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                _, stderr = await proc.communicate()
                if proc.returncode == 0 and os.path.exists(output_path):
                    return output_path
                logger.warning("grim command failed: %s", stderr.decode())
            except Exception as e:
                logger.warning("grim execution failed: %s", e)

        # B. X11 with gnome-screenshot
        if shutil.which("gnome-screenshot"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "gnome-screenshot", "-f", output_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.communicate()
                if proc.returncode == 0 and os.path.exists(output_path):
                    return output_path
            except Exception:
                pass

        # C. scrot
        if shutil.which("scrot"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "scrot", output_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.communicate()
                if proc.returncode == 0 and os.path.exists(output_path):
                    return output_path
            except Exception:
                pass

        # D. ImageMagick import
        if shutil.which("import"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "import", "-window", "root", output_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.communicate()
                if proc.returncode == 0 and os.path.exists(output_path):
                    return output_path
            except Exception:
                pass

        # E. PIL / Pillow fallback
        try:
            from PIL import ImageGrab
            loop = asyncio.get_running_loop()
            img = await loop.run_in_executor(None, ImageGrab.grab)
            if img:
                await loop.run_in_executor(None, img.save, output_path)
                if os.path.exists(output_path):
                    return output_path
        except Exception as e:
            logger.warning("Pillow ImageGrab failed: %s", e)

        return None


screenshot_service = ScreenshotService()
