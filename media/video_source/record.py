"""Record every scene of the Analytivest tutorial with Playwright (1920x1080 video, 1280x720 CSS viewport).

Title cards are HTML pages with CSS animations timed to the narration's sentence cues; app scenes drive the
real running app at http://127.0.0.1:8000. A fake cursor + click ripple is drawn because headless video has
no pointer. Output: clips/<id>.webm and clips.json (lead-in seconds to trim per clip).
"""
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).parent
BASE = "http://127.0.0.1:8000"
VW, VH = 1280, 720
TIMINGS = {t["id"]: t for t in json.loads((HERE / "timings.json").read_text(encoding="utf-8"))}
SCRIPT = {s["id"]: s for s in json.loads((HERE / "script.json").read_text(encoding="utf-8"))}
TAIL = 0.9  # seconds recorded beyond the narration of each scene

LOGO = ('<svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg"><rect width="32" height="32" rx="8" fill="#2a78d6"/>'
        '<path d="M7 21l6-6 4 4 8-9" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>')

ZOOM_JS = """
document.addEventListener('DOMContentLoaded', () => {
  const s = document.createElement('style'); s.textContent = 'body{zoom:1.5}'; document.head.appendChild(s);
});
"""

CURSOR_JS = """
(() => {
  const mk = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div'); c.id = '__cur';
    c.innerHTML = '<svg width="38" height="38" viewBox="0 0 24 24"><path d="M4 2l16 9-7 2-3 7z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position:'fixed', left:'-50px', top:'-50px', zIndex: 2147483647, pointerEvents:'none', transition:'transform .06s'});
    document.documentElement.appendChild(c);
    addEventListener('mousemove', e => { c.style.left = e.clientX - 3 + 'px'; c.style.top = e.clientY - 2 + 'px'; }, true);
    addEventListener('mousedown', e => {
      const r = document.createElement('div');
      Object.assign(r.style, {position:'fixed', left: e.clientX - 18 + 'px', top: e.clientY - 18 + 'px', width:'36px', height:'36px',
        borderRadius:'50%', border:'3px solid #3987e5', zIndex: 2147483646, pointerEvents:'none', transition:'all .45s ease-out', opacity: 1});
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = 0; });
      setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mk); else mk();
})();
"""


def cue_time(sid: str, phrase: str, default: float = 0.0) -> float:
    """Narration time where `phrase` is spoken (interpolated inside the sentence cue)."""
    for c in TIMINGS[sid]["cues"]:
        k = c["text"].find(phrase)
        if k >= 0:
            return c["start"] + (c["end"] - c["start"]) * k / max(1, len(c["text"]))
    return default


# ---------------- title cards ----------------
CARD_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:100%;height:100%;overflow:hidden;font-family:'Segoe UI Variable Display','Segoe UI',system-ui,sans-serif;color:#eef2f8}
body{zoom:1.5;background:radial-gradient(1200px 700px at 15% 10%,#173a6b 0%,transparent 60%),radial-gradient(900px 600px at 95% 100%,#0f5a4a 0%,transparent 55%),#0a1322}
.grid{position:absolute;inset:-40px;background-image:linear-gradient(rgba(255,255,255,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.045) 1px,transparent 1px);background-size:48px 48px;animation:drift 30s linear infinite}
@keyframes drift{to{transform:translate(48px,48px)}}
.wrap{position:relative;height:100%;padding:64px 80px;display:flex;flex-direction:column}
.a{opacity:0;transform:translateY(22px)}
.go .a{animation:up .6s cubic-bezier(.2,.8,.2,1) forwards}
@keyframes up{to{opacity:1;transform:none}}
.pop{opacity:0;transform:scale(.6)}
.go .pop{animation:pop .7s cubic-bezier(.2,1.4,.3,1) forwards}
@keyframes pop{to{opacity:1;transform:none}}
.kicker{font-size:15px;letter-spacing:.24em;text-transform:uppercase;font-weight:700;color:#7fb2f0}
.h1{font-size:60px;font-weight:800;letter-spacing:-.02em}
.h2{font-size:40px;font-weight:750;letter-spacing:-.01em}
.muted{color:#a8b3c4}
.logo{width:96px;height:96px;filter:drop-shadow(0 12px 30px rgba(42,120,214,.45))}
.chip{display:inline-flex;align-items:center;gap:8px;padding:10px 20px;border-radius:999px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);font-size:18px}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:40px}
.tile{border-radius:20px;padding:30px 30px;min-height:205px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);min-height:150px}
.tile.bad{border-left:5px solid #ec835a}
.tile .t{font-size:31px;font-weight:700;display:flex;gap:12px;align-items:center}
.tile .d{font-size:21px;color:#c4cdda;margin-top:12px;line-height:1.45}
.num{font-size:16px;font-weight:800;color:#ec835a;letter-spacing:.12em}
.verdicts{display:grid;grid-template-columns:repeat(3,1fr);gap:26px;margin-top:56px}
.v{border-radius:22px;padding:36px 32px;min-height:300px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);border-top:5px solid #3987e5}
.v .t{font-size:34px;font-weight:750;margin-top:10px}
.v .q{font-size:22px;color:#c4cdda;margin-top:8px;line-height:1.4}
.v .ic{font-size:46px}
.bar{height:10px;border-radius:9px;background:rgba(255,255,255,.1);margin-top:28px;overflow:hidden}
.bar i{display:block;height:100%;width:0;border-radius:9px;background:#0ca30c}
.go .bar i{animation:fill 1.4s ease-out forwards;animation-delay:inherit}
@keyframes fill{to{width:var(--w)}}
.foot{margin-top:auto;display:flex;gap:14px;flex-wrap:wrap}
.strike{position:relative}
.note{border-radius:16px;padding:18px 22px;background:rgba(236,131,90,.12);border:1px solid rgba(236,131,90,.4);font-size:20px;color:#ffd9c8}
"""


def d(t: float) -> str:
    return f"animation-delay:{max(0.0, t):.2f}s"


def card_html(sid: str) -> str:
    if sid == "s01_intro":
        t_title, t_tag = cue_time(sid, "walk you through", 1.7), cue_time(sid, "Invest with evidence", 5.1)
        t_sub, t_flow = cue_time(sid, "data-led", 7.1), cue_time(sid, "the problems", 13.3)
        t_sol = cue_time(sid, "solves them", 16.0)
        body = f"""
<div class="wrap" style="justify-content:center;align-items:center;text-align:center">
  <div class="pop logo" style="{d(0.15)}">{LOGO}</div>
  <div class="a kicker" style="margin-top:26px;{d(0.6)}">Hello everyone 👋</div>
  <div class="a h1" style="margin-top:10px;font-size:84px;{d(t_title)}">Analytivest</div>
  <div class="a h2" style="margin-top:6px;color:#7fb2f0;{d(t_tag)}">Invest with evidence.</div>
  <div class="a muted" style="font-size:22px;margin-top:18px;{d(t_sub)}">Data-led investment analysis &nbsp;·&nbsp; NSE &amp; BSE stocks &nbsp;·&nbsp; IPOs</div>
  <div style="margin-top:44px;display:flex;gap:16px;align-items:center">
    <span class="a chip" style="{d(t_flow)}">⚠️ The problems</span>
    <span class="a" style="font-size:26px;{d(t_flow + 0.4)}">→</span>
    <span class="a chip" style="border-color:#3987e5;{d(t_sol)}">✅ The solutions</span>
  </div>
</div>"""
    elif sid == "s02_problems":
        ts = [cue_time(sid, "Problem one", 0.1), cue_time(sid, "Problem two", 10.3), cue_time(sid, "Problem three", 17.5),
              cue_time(sid, "problem four", 24.2)]
        tiles = [
            ("📱", "Tips &amp; hype", "WhatsApp forwards, Telegram calls, grey-market premium, ‘heavily subscribed’ headlines."),
            ("🗂️", "Scattered data", "Annual reports, exchange filings, many websites, 500-page RHPs."),
            ("❓", "Ratings without reasons", "One buy/sell label, no evidence, lots of jargon: EBITDA, ROCE, P/E…"),
            ("⚠️", "Hidden traps", "Bonus issues distort EPS · results in dollars · one-time gains · wrong data."),
        ]
        items = "".join(f"""<div class="a tile bad" style="{d(ts[i])}"><div class="num">PROBLEM {i + 1}</div>
              <div class="t">{ic} {t}</div><div class="d">{tx}</div></div>""" for i, (ic, t, tx) in enumerate(tiles))
        body = f"""<div class="wrap"><div class="a kicker" style="color:#f0a585;{d(0)}">Before Analytivest</div>
            <div class="a h2" style="margin-top:8px;{d(0.25)}">Investing on noise, not evidence</div><div class="tiles">{items}</div></div>"""
    elif sid == "s03_solution":
        t1, t2, t3 = cue_time(sid, "Business quality", 3.2), cue_time(sid, "Financial risk", 6.0), cue_time(sid, "valuation", 9.1)
        t4 = cue_time(sid, "Every number", 12.0)
        vs = [("🏛️", "Business quality", "Is the company fundamentally strong?", "#0ca30c", "79%", t1),
              ("🛡️", "Financial risk", "How vulnerable is it to debt or cash-flow problems?", "#fab219", "28%", t2),
              ("⚖️", "Valuation", "Is today’s price reasonable vs fundamentals &amp; peers?", "#3987e5", "56%", t3)]
        cards = "".join(f"""<div class="a v" style="border-top-color:{c};{d(t)}"><div class="ic">{ic}</div><div class="t">{ti}</div>
              <div class="q">{q}</div><div class="bar" style="{d(t + 0.3)}"><i style="--w:{w};background:{c}"></i></div></div>"""
                        for ic, ti, q, c, w, t in vs)
        body = f"""<div class="wrap"><div class="a kicker" style="{d(0)}">After Analytivest</div>
            <div class="a h2" style="margin-top:8px;{d(0.25)}">Three separate verdicts, never one blind rating</div>
            <div class="verdicts">{cards}</div>
            <div class="foot"><span class="a chip" style="{d(t4)}">📍 Source</span><span class="a chip" style="{d(t4 + .2)}">🗓️ Period</span>
            <span class="a chip" style="{d(t4 + .4)}">🧮 Formula</span><span class="a chip" style="{d(t4 + .6)}">✅ for every number</span></div></div>"""
    else:  # s12_outro
        t_logo, t_tag, t_thx = cue_time(sid, "So that's", 4.9), cue_time(sid, "Invest with evidence", 7.0), cue_time(sid, "Thanks", 8.9)
        body = f"""
<div class="wrap" style="justify-content:center;align-items:center;text-align:center">
  <div class="a note" style="{d(0.1)}">⚖️ Research &amp; decision support, <b>not investment advice</b>. Always read the filings.</div>
  <div class="pop logo" style="margin-top:46px;{d(t_logo)}">{LOGO}</div>
  <div class="a h1" style="margin-top:18px;font-size:76px;{d(t_logo + .2)}">Analytivest</div>
  <div class="a h2" style="color:#7fb2f0;{d(t_tag)}">Invest with evidence.</div>
  <div class="a" style="font-size:30px;margin-top:34px;{d(t_thx)}">Thanks for watching 🙏 &nbsp;Happy investing!</div>
</div>"""
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CARD_CSS}</style></head><body><div class='grid'></div>{body}</body></html>"


# ---------------- helpers for app scenes ----------------
async def smooth_scroll(page, to_y: float, ms: int = 1200):
    await page.evaluate("""([to, ms]) => new Promise(res => {
        const from = scrollY, t0 = performance.now();
        const step = (t) => { const k = Math.min(1, (t - t0) / ms); const e = k < .5 ? 2*k*k : 1 - Math.pow(-2*k + 2, 2) / 2;
          scrollTo(0, from + (to - from) * e); k < 1 ? requestAnimationFrame(step) : res(); };
        requestAnimationFrame(step); })""", [to_y, ms])


async def scroll_to_el(page, locator, offset: int = 90, ms: int = 1200):
    # Native scrollIntoView handles the body zoom correctly (manual rect maths does not).
    await locator.evaluate("""(el, off) => { el.style.scrollMarginTop = off + 'px';
        el.scrollIntoView({behavior: 'smooth', block: 'start'}); }""", offset)
    await page.wait_for_timeout(ms)


async def move(page, locator, steps: int = 22, click: bool = False):
    try:
        await locator.scroll_into_view_if_needed(timeout=8000)
        box = await locator.bounding_box()
    except Exception as e:  # keep recording; report what was not found
        print(f"   ! cursor target not found: {locator} ({type(e).__name__})", flush=True)
        return
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    await page.mouse.move(x, y, steps=steps)
    if click:
        await page.wait_for_timeout(150)
        await page.mouse.click(x, y)


class Clock:
    def __init__(self, page):
        self.page, self.t0 = page, time.monotonic()

    async def at(self, t: float):
        """Wait until `t` seconds after scene start (no-op if already past)."""
        dt = t - (time.monotonic() - self.t0)
        if dt > 0:
            await self.page.wait_for_timeout(int(dt * 1000))


async def ready(page, url: str, text: str | None = None):
    await page.goto(BASE + url)
    if text:
        await page.get_by_text(text, exact=False).first.wait_for(timeout=60000)
    await page.wait_for_timeout(700)


# ---------------- app scenes ----------------
async def s04_search(page, dur):
    await ready(page, "/", "Data-led analysis")
    c = Clock(page)
    box = page.get_by_role("combobox")
    await move(page, box, click=True)
    await page.keyboard.type("TCS", delay=180)
    await c.at(3.5)
    await move(page, page.get_by_role("option").first)
    await c.at(6.0)
    await move(page, page.get_by_title("Open TCS.BO").first)
    await c.at(8.0)
    await move(page, page.get_by_role("option").first, click=True)
    await c.at(dur + TAIL)
    return c


async def s05_overview(page, dur):
    await ready(page, "/c/TCS.NS", "Business quality")
    c = Clock(page)
    await c.at(2.0)
    await move(page, page.get_by_text("Strong fundamentals").first)
    await c.at(4.6)
    await move(page, page.get_by_role("button", name="Why this score").first, click=True)
    await c.at(8.0)
    await move(page, page.get_by_text("Within estimated fair-value range").first)
    await c.at(11.0)
    await scroll_to_el(page, page.get_by_role("heading", name="Share price"), ms=1300)
    chart = page.locator(".recharts-wrapper").first
    box = await chart.bounding_box()
    for k in range(1, 9):
        await page.mouse.move(box["x"] + box["width"] * k / 9, box["y"] + box["height"] * 0.5, steps=4)
        await page.wait_for_timeout(110)
    await c.at(16.5)
    await scroll_to_el(page, page.get_by_role("heading", name="Positive factors"), ms=1300)
    await move(page, page.get_by_role("heading", name="Major risks"))
    await c.at(dur + TAIL)
    return c


async def s06_tabs(page, dur):
    await ready(page, "/c/TCS.NS/financials", "Profit & loss")
    c = Clock(page)
    await c.at(1.3)
    await smooth_scroll(page, 300, 900)
    await c.at(3.0)
    await move(page, page.get_by_role("link", name="Growth & profitability"), click=True)
    await c.at(4.6)
    term = page.get_by_role("button", name="What is CAGR?").first
    await move(page, term)
    await c.at(7.4)
    await move(page, page.get_by_role("link", name="Debt & balance sheet"), click=True)
    await c.at(9.0)
    await move(page, page.get_by_role("button", name="Table").first, click=True)
    await c.at(11.0)
    await move(page, page.get_by_role("link", name="Cash flow"), click=True)
    await c.at(dur + TAIL)
    return c


async def s07_valuation(page, dur):
    await ready(page, "/c/TCS.NS/valuation", "Estimated fair-value range")
    c = Clock(page)
    await c.at(1.6)
    await move(page, page.get_by_text("Valuation multiples").first)
    await c.at(3.3)
    await scroll_to_el(page, page.get_by_role("heading", name="Historical P/E band"), ms=1100)
    await c.at(5.6)
    await scroll_to_el(page, page.get_by_role("heading", name="Discounted cash flow (DCF)"), ms=1100)
    growth = page.get_by_label("Growth, stage 1")
    await move(page, growth)
    await growth.click(click_count=3)
    await c.at(8.4)
    await page.keyboard.type("12", delay=250)
    await c.at(10.3)
    await move(page, page.get_by_text("Value per share", exact=True).first)
    await c.at(12.6)
    await smooth_scroll(page, 0, 700)
    await move(page, page.get_by_role("link", name="Peers"), click=True)
    await page.get_by_text("Peer comparison").first.wait_for()
    excl = page.get_by_text("excl.").first
    if await excl.count():
        await move(page, excl)
    await c.at(dur + TAIL)
    return c


async def s08_risks(page, dur):
    await ready(page, "/c/DEMO-LEVER/risks", "Red flags")
    c = Clock(page)
    await c.at(1.5)
    await move(page, page.get_by_text("Persistent negative free cash flow").first)
    await c.at(4.0)
    await smooth_scroll(page, 330, 1500)
    await move(page, page.get_by_text("Profits rising but operating cash flow is weak").first)
    await c.at(8.0)
    await smooth_scroll(page, 700, 1500)
    await move(page, page.get_by_text("Exceptional gains repeatedly support profits").first)
    await c.at(12.0)
    await smooth_scroll(page, 1000, 1500)
    await c.at(dur + TAIL)
    return c


async def s09_traps(page, dur):
    await ready(page, "/c/HDFCBANK.NS", "Business quality")
    c = Clock(page)
    await move(page, page.get_by_text("Financial-sector model").first)
    await c.at(2.6)
    await move(page, page.get_by_text("This is a bank or financial company").first)
    t_inf = cue_time("s09_traps", "Infosys", 5.5)
    await c.at(t_inf - 0.6)
    await ready(page, "/c/INFY.NS", "Business quality")
    await scroll_to_el(page, page.get_by_role("heading", name="Data sources & freshness"), offset=260, ms=900)
    await move(page, page.get_by_text("converted to INR").first)
    t_dem = cue_time("s09_traps", "demerger", 10.5)
    await c.at(t_dem - 0.6)
    await ready(page, "/c/TMPV.NS", "Business quality")
    await move(page, page.get_by_text("not meaningful: company made a loss").first)
    await c.at(dur + TAIL)
    return c


async def s10_ipo(page, dur):
    await ready(page, "/ipo", "IPO analysis")
    c = Clock(page)
    await c.at(0.8)
    await move(page, page.get_by_role("link", name="Upload RHP/DRHP"), click=True)
    await page.get_by_text("Drop the document here").wait_for()
    await c.at(3.0)
    await move(page, page.get_by_role("button", name="Choose a file"))
    await page.evaluate("""async () => {
        const blob = await fetch('/api/ipos/sample-rhp').then(r => r.blob());
        const file = new File([blob], 'Demo_Precision_RHP.pdf', {type: 'application/pdf'});
        const input = document.querySelector('input[type=file]'); const dt = new DataTransfer(); dt.items.add(file);
        input.files = dt.files; input.dispatchEvent(new Event('change', {bubbles: true})); }""")
    await c.at(5.0)
    await move(page, page.get_by_role("button", name="Read & analyse"), click=True)
    await page.get_by_text("Review the extracted figures").wait_for()
    await c.at(cue_time("s10_ipo", "extracts the price band", 9.1) - 0.3)
    await move(page, page.get_by_role("button", name="Source for this field: page 1").nth(1))
    await c.at(12.6)
    await scroll_to_el(page, page.get_by_text("Restated financials (₹ Cr)").first, offset=300, ms=1000)
    await move(page, page.get_by_role("button", name="Source for this field: page 9").last)
    await c.at(16.4)
    await move(page, page.get_by_role("button", name="Confirm figures & get suggestion"), steps=26, click=True)
    await page.get_by_text("Analytivest suggestion", exact=False).first.wait_for()
    await page.evaluate("scrollTo(0,0)")
    await c.at(cue_time("s10_ipo", "clear suggestion", 19.2) + 0.4)
    await move(page, page.get_by_text("BORDERLINE").first)
    await c.at(22.5)
    await move(page, page.get_by_text("In favour").first)
    await c.at(24.0)
    await move(page, page.get_by_text("Against").first)
    await c.at(cue_time("s10_ipo", "Grey market", 24.5) + 0.3)
    await move(page, page.get_by_text("Listing-day gains are not predicted").first)
    await c.at(dur + TAIL)
    return c


async def s11_extras(page, dur):
    await ready(page, "/compare?s=TCS.NS,INFY.NS,HDFCBANK.NS", "Compare companies")
    await page.get_by_text("VERDICTS", exact=False).first.wait_for()
    c = Clock(page)
    await c.at(1.0)
    await smooth_scroll(page, 380, 1600)
    await c.at(4.0)
    await ready(page, "/watchlist", "Watchlist & saved analyses")
    await c.at(6.2)
    await ready(page, "/c/TCS.NS", "Business quality")
    await move(page, page.get_by_role("button", name="Theme:", exact=False), click=True)
    await c.at(dur + TAIL)
    return c


APP_SCENES = {"s04_search": s04_search, "s05_overview": s05_overview, "s06_tabs": s06_tabs, "s07_valuation": s07_valuation,
              "s08_risks": s08_risks, "s09_traps": s09_traps, "s10_ipo": s10_ipo, "s11_extras": s11_extras}


async def record(pw, sid: str, out: Path) -> dict:
    dur = TIMINGS[sid]["duration"]
    tmp = HERE / "rec_tmp" / sid
    shutil.rmtree(tmp, ignore_errors=True)
    browser = await pw.chromium.launch()
    ctx = await browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, color_scheme="light",
                                    record_video_dir=str(tmp), record_video_size={"width": 1920, "height": 1080})
    await ctx.add_init_script("try{localStorage.setItem('stockiq-theme','light')}catch(e){}")
    await ctx.add_init_script(CURSOR_JS)
    if sid in APP_SCENES:
        await ctx.add_init_script(ZOOM_JS)
    page = await ctx.new_page()
    t_start = time.monotonic()
    if sid in APP_SCENES:
        clock = await APP_SCENES[sid](page, dur)
        lead = clock.t0 - t_start
    else:
        await page.set_content(card_html(sid))
        await page.wait_for_timeout(500)  # fonts/emoji settle
        lead = time.monotonic() - t_start
        await page.evaluate("document.body.classList.add('go')")
        await page.wait_for_timeout(int((dur + TAIL) * 1000))
    video = page.video
    await ctx.close()
    await browser.close()
    src = Path(await video.path())
    dst = out / f"{sid}.webm"
    shutil.move(str(src), dst)
    return {"id": sid, "lead": lead, "duration": dur}


async def main(only: list[str]):
    out = HERE / "clips"
    out.mkdir(exist_ok=True)
    meta_path = HERE / "clips.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    async with async_playwright() as pw:
        for sid in SCRIPT:
            if only and sid not in only:
                continue
            t = time.monotonic()
            m = await record(pw, sid, out)
            meta[sid] = m
            meta_path.write_text(json.dumps(meta, indent=1))
            print(f"{sid}: recorded in {time.monotonic() - t:.1f}s (lead {m['lead']:.2f}s)", flush=True)


asyncio.run(main(sys.argv[1:]))
