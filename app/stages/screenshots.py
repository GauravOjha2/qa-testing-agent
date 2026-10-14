"""Stage 1 — multi-viewport screenshots + horizontal-overflow probe."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from playwright.async_api import Browser

from .. import config
from ..models import Finding, ScreenshotMeta, finding_id
from ..ratelimit import RateLimiter
from .browser import goto_polite, new_context

_OVERFLOW_JS = """() => {
  const doc = document.scrollingElement || document.documentElement;
  const vw = window.innerWidth;
  const offenders = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width && (r.right > vw + 1 || r.left < -1)) {
      offenders.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className && el.className.toString().slice(0, 80)) || '',
        right: Math.round(r.right)
      });
    }
    if (offenders.length >= 5) break;
  }
  return {scrollWidth: doc.scrollWidth, innerWidth: vw, offenders};
}"""


def make_thumbnail(png_bytes: bytes, dest: Path, max_width: int = 1100) -> tuple[int, int]:
    """Pillow: downscale the capture to a JPEG thumbnail for the report
    and the evidence grid (keeps PDF size and page weight sane)."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, max(1, round(img.height * ratio))), Image.LANCZOS)
    img.save(dest, "JPEG", quality=78, optimize=True)
    return img.width, img.height


async def run(
    browser: Browser, url: str, run_dir: Path, limiter: RateLimiter, log
) -> tuple[list[Finding], list[ScreenshotMeta], str]:
    """Returns (findings, screenshot metadata, final_url)."""
    shots_dir = run_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    findings: list[Finding] = []
    shots: list[ScreenshotMeta] = []
    final_url = url

    for name, viewport in config.VIEWPORTS.items():
        log(f"capturing {name} viewport {viewport['width']}x{viewport['height']}")
        context = await new_context(browser, viewport)
        try:
            page = await context.new_page()
            resp = await goto_polite(page, url, limiter)
            if name == "desktop" and resp is not None:
                final_url = page.url
            await page.wait_for_timeout(config.SCREENSHOT_SETTLE_MS)
            # Trigger lazy-loaded content before measuring/capturing.
            await page.evaluate(
                "async () => { await new Promise(r => {"
                "  let y = 0; const step = () => {"
                "    y += window.innerHeight; window.scrollTo(0, y);"
                "    if (y < document.body.scrollHeight) setTimeout(step, 120);"
                "    else { window.scrollTo(0, 0); setTimeout(r, 300); }"
                "  }; step(); }); }"
            )
            png = await page.screenshot(full_page=True, type="png")
            probe = await page.evaluate(_OVERFLOW_JS)
        finally:
            await context.close()

        png_path = shots_dir / f"{name}.png"
        png_path.write_bytes(png)
        thumb_path = shots_dir / f"{name}.jpg"
        w, h = make_thumbnail(png, thumb_path)

        overflow_px = max(0, probe["scrollWidth"] - probe["innerWidth"])
        overflow = overflow_px > 1
        shots.append(
            ScreenshotMeta(
                viewport=name,
                path=str(png_path.relative_to(config.REPO_ROOT)),
                thumb=str(thumb_path.relative_to(config.REPO_ROOT)),
                width=w,
                height=h,
                overflow_x=overflow,
                overflow_px=overflow_px,
            )
        )
        if overflow:
            offenders = ", ".join(
                f"<{o['tag']}> right={o['right']}px" for o in probe["offenders"][:3]
            ) or "unknown element"
            findings.append(
                Finding(
                    id=finding_id("visual", "horizontal-overflow", name),
                    category="visual",
                    severity="high" if overflow_px > 40 else "medium",
                    title=f"Horizontal overflow on {name} ({overflow_px}px)",
                    detail=(
                        f"Page scrolls sideways by {overflow_px}px at "
                        f"{viewport['width']}px width. Offenders: {offenders}"
                    ),
                    evidence={"viewport": name, "overflow_px": overflow_px,
                              "screenshot": str(thumb_path.relative_to(config.REPO_ROOT))},
                    recommendation=(
                        "Audit fixed-width elements and 100vw usage; add "
                        "overflow-x guards on wide media/tables."
                    ),
                )
            )
        log(f"{name}: captured ({w}x{h} thumb), overflow={'yes' if overflow else 'no'}")
    return findings, shots, final_url
