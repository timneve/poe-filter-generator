"""Drive filterblade.xyz headless (Playwright, installed) and dump what a section shows.

python .claude/skills/filterblade-parity/fb.py OUTDIR "Customize" "Endgame - Special Bases & Crafting" "Influenced" ...
  [--poe2]   start at ?game=Poe2
Each arg = click the LAST visible element whose trimmed text equals it (case-insensitive),
then wait. Writes OUTDIR/page.txt (body text) + OUTDIR/page.png (full-page screenshot) at the end,
plus OUTDIR/step<N>.png after each click. Cookie banner is accepted first.
Prefix an arg with "~" for a substring match instead of exact.
"""
import os
import sys

from playwright.sync_api import sync_playwright

CLICK = """([t, sub]) => {
  const norm = s => (s || '').trim().replace(/\\s+/g, ' ').toLowerCase();
  const want = norm(t);
  const els = [...document.querySelectorAll('*')].filter(e => e.offsetParent &&
     (sub ? norm(e.innerText).includes(want) && e.children.length < 4 : norm(e.innerText) === want));
  const e = els[els.length - 1];
  if (!e) return 'NOT FOUND: ' + t;
  e.scrollIntoView(); e.click(); return 'clicked: ' + e.tagName + ' ' + norm(e.innerText).slice(0, 80);
}"""


def main(argv):
    poe2 = "--poe2" in argv
    argv = [a for a in argv if a != "--poe2"]
    out, steps = argv[0], argv[1:]
    os.makedirs(out, exist_ok=True)
    url = "https://www.filterblade.xyz/" + ("?game=Poe2" if poe2 else "")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1600, "height": 1200})
        pg.goto(url, wait_until="networkidle", timeout=90000)
        pg.wait_for_timeout(3000)
        def dismiss():  # cookie banner + "Select a game" modal (pops up late, covers screenshots)
            try:
                pg.get_by_role("button", name="Accept").click(timeout=2000)
            except Exception:
                pass
            pg.evaluate(CLICK, ["pre-built for beginners" if poe2 else "FilterBlade offers PoE1", True])
            pg.wait_for_timeout(1500)

        pg.wait_for_timeout(3000)
        dismiss()
        for i, s in enumerate(steps):
            sub = s.startswith("~")
            print(pg.evaluate(CLICK, [s.lstrip("~"), sub]))
            pg.wait_for_timeout(3000)
            pg.screenshot(path=os.path.join(out, f"step{i}.png"))
        dismiss()
        pg.screenshot(path=os.path.join(out, "page.png"), full_page=True)
        with open(os.path.join(out, "page.txt"), "w", encoding="utf8") as f:
            f.write(pg.inner_text("body"))
        b.close()


if __name__ == "__main__":
    main(sys.argv[1:])
