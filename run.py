import os, re, time, html, json, urllib.request, urllib.parse, urllib.error

DRY = os.environ.get("DRY_RUN") == "1"
TG = os.environ.get("TG_TOKEN", "")
KEY = os.environ["GEMINI_API_KEY"]
DST = "@eskele_org"
MAX_PER_RUN = 6
# free-tier quotas are per model, so fall through to the next one when a model's daily quota is gone
MODELS = ["gemini-3.5-flash", "gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-2.5-flash"]
dead_models = set()
KEYWORDS = re.compile("گمرک|ترخیص|تعرفه|واردات|صادرات|بازرگانی|تجارت|ارز|بندر|حمل|ترانزیت|کالا|کانتینر|مرز|مبادلات|ثبت سفارش|تسهیل")

TG_CHANNELS = ["Tarkhis_Karan", "Gomrok_news"]
RSS = {
    "akhbargomroki": "https://akhbargomroki.com/feed",
    "mefa-news": "http://mefa.ir/rss/tp/11352",
    "mefa-notices": "http://mefa.ir/rss/tp/11377",
    "mefa-circulars": "http://mefa.ir/rss/tp/190",
}
WCO_LIST = "https://www.wcoomd.org/en/media/newsroom.aspx"

FOOTER = """

━━━━━━━━━━━━━━
🚢 اسکله | حمل بین‌المللی و ترخیص کالا
حمل دریایی، هوایی، زمینی و ریلی و ترخیص از گمرکات؛ از استعلام تا تحویل درب‌به‌درب، با یک مسئول پرونده.
👉 eskele.org
📢 @eskele_org"""

PROMPT = """تو دبیر خبر کانال «اسکله» (حمل بین‌المللی و ترخیص کالا) هستی.

خبرهای اخیراً منتشرشده در کانال:
{recent}

خبر جدید (منبع: {src}{lang}):
{text}

قواعد (به ترتیب):
1. اگر خبر ربطی به گمرک، ترخیص، تعرفه، واردات و صادرات، تجارت خارجی، حمل‌ونقل بین‌المللی، بنادر و مناطق آزاد، ارز بازرگانی یا مقررات بازرگانی ندارد، یا فقط تبریک/تاریخ روز است: فقط کلمه‌ی SKIP را بنویس.
2. اگر همین خبر قبلاً در کانال منتشر شده (حتی با منبع یا لحن دیگر) و اطلاعات تازه‌ی مهمی ندارد: فقط کلمه‌ی DUP را بنویس.
3. اگر موضوع همان خبر قبلی است ولی اطلاعات تازه و مهمی دارد: با تیتر و ساختار و کلمات کاملاً متفاوت بنویس، روی نکته‌ی تازه تأکید کن و با «🔄 تکمیل خبر» شروع کن.
4. در غیر این صورت: خبر را به فارسی روان و حرفه‌ای با کلمات خودت بازنویس. {translate}

همه‌ی واقعیت‌ها، اعداد، نام‌ها و فهرست‌ها دقیق بماند و چیزی از خودت اضافه نکن. با یک ایموجی و تیتر کوتاه شروع کن. امضا، لینک و نام و آیدی کانال یا سایت منبع را حذف کن. فقط متن نهایی (یا SKIP/DUP) را بنویس."""

state = json.load(open("state.json"))
if "last_id" in state:
    state = {"Tarkhis_Karan": state["last_id"]}
state.setdefault("seen", {})
state.setdefault("recent", [])

def fetch(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")

def call(url, data=None, headers=None):
    for wait in (15, 40, 0):
        try:
            return fetch(url, data, headers)
        except urllib.error.HTTPError as e:
            if e.code != 429 or not wait: raise
            time.sleep(wait)

def clean(s):
    s = re.sub(r"<br\s*/?>|</p>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n{3,}", "\n\n", s).strip()

def tg_items(ch):
    page = fetch(f"https://t.me/s/{ch}")
    out = []
    for blk in page.split("tgme_widget_message_wrap")[1:]:
        m = re.search(r'data-post="[^/]+/(\d+)"', blk)
        t = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', blk, re.S)
        if m: out.append((int(m.group(1)), clean(t.group(1)) if t else ""))
    return out

def rss_items(url):
    x = fetch(url)
    out = []
    for it in re.findall(r"<item>(.*?)</item>", x, re.S):
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1]
        link = clean(g("link")) or clean(g("guid"))
        body = re.sub(r"<!\[CDATA\[|\]\]>", "", g("content:encoded") or g("description"))
        text = clean(re.sub(r"<!\[CDATA\[|\]\]>", "", g("title"))) + "\n\n" + clean(body)
        out.append((link, text[:3500]))
    return out

def wco_items():
    page = fetch(WCO_LIST)
    links = []
    for l in re.findall(r"newsroom/(20\d\d/[a-z]+/[^'\"\s]+?\.aspx)", page):
        if l not in links: links.append(l)
    return [("https://www.wcoomd.org/en/media/newsroom/" + l, None) for l in links[:8]]

def wco_text(url):
    p = fetch(url)
    title = clean((re.search(r"<h1[^>]*>(.*?)</h1>", p, re.S) or [None, ""])[1])
    paras = [clean(x) for x in re.findall(r"<p[^>]*>(.*?)</p>", p, re.S)]
    body = "\n".join(x for x in paras if len(x) > 50)
    return (title + "\n\n" + body)[:3500]

_last_gemini = [0.0]
def rewrite(text, src, english=False):
    wait = 13 - (time.time() - _last_gemini[0])  # free tier: keep under ~5 requests/minute
    if wait > 0: time.sleep(wait)
    _last_gemini[0] = time.time()
    recent = "\n".join(f"- {r}" for r in state["recent"][-30:]) or "(هنوز موردی نیست)"
    prompt = PROMPT.format(recent=recent, src=src, text=text,
                           lang="، متن انگلیسی" if english else "",
                           translate="متن انگلیسی است؛ آن را به فارسی روان و طبیعی ترجمه و بازنویسی کن (نه ترجمه‌ی تحت‌اللفظی؛ اصطلاحات گمرکی را با معادل رایج فارسی بنویس)." if english else "")
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    last = None
    for model in MODELS:
        if model in dead_models: continue
        try:
            r = json.loads(fetch(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                 body, {"x-goog-api-key": KEY, "content-type": "application/json"}))
            return r["candidates"][0]["content"]["parts"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 404):
                dead_models.add(model); print(f"model {model} unavailable ({e.code}), trying next"); continue
            if e.code in (500, 502, 503, 504):
                print(f"model {model} overloaded ({e.code}), trying next"); continue
            raise
    raise last or RuntimeError("no Gemini model available")

def save_state():
    if not DRY:
        json.dump(state, open("state.json", "w"), ensure_ascii=False)

def to_html(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t, flags=re.S)
    t = re.sub(r"(?m)^\s*[\*\-]\s+", "▫️ ", t)
    return t.replace("*", "")

sent = 0
def publish(text, src, english=False):
    """Returns True when handled (sent, skipped or duplicate)."""
    global sent
    out = rewrite(text, src, english)
    head = out.split()[0].upper() if out.split() else ""
    if head in ("SKIP", "DUP") and len(out) < 8:
        print(f"[{src}] {head}: {text[:60]!r}"); return True
    if DRY:
        print(f"[{src}] WOULD POST:\n{out}\n"); 
    else:
        msg = to_html(out)
        if len(msg) + len(FOOTER) > 4000: msg = msg[:4000 - len(FOOTER)].rsplit("\n", 1)[0]
        call(f"https://api.telegram.org/bot{TG}/sendMessage",
             urllib.parse.urlencode({"chat_id": DST, "text": msg + FOOTER, "parse_mode": "HTML",
                                     "disable_web_page_preview": "true"}).encode())
        time.sleep(8)
    state["recent"].append(out.replace("\n", " ")[:160])
    state["recent"] = state["recent"][-40:]
    sent += 1
    save_state()  # persist right after each post so a later crash can't cause duplicates
    return True

# --- Telegram channels (numeric last-id)
for ch in TG_CHANNELS:
    if sent >= MAX_PER_RUN: break
    try:
        posts = tg_items(ch)
        if not posts:
            print(f"{ch}: no readable posts"); continue
        if ch not in state:
            state[ch] = max(i for i, _ in posts); continue
        for pid, text in sorted(p for p in posts if p[0] > state[ch]):
            if sent >= MAX_PER_RUN: break
            if text: publish(text, "@" + ch)
            state[ch] = pid
            save_state()
    except Exception as e:
        print(f"{ch}: error {e}")

# --- RSS / WCO (seen-set)
def run_source(name, items, text_of=None, english=False, first_run_post=0):
    global sent
    seen = state["seen"].setdefault(name, None)
    if seen is None:
        state["seen"][name] = [k for k, _ in items][first_run_post:]; print(f"{name}: baseline {len(items)}"); return
    for key, text in items:
        if sent >= MAX_PER_RUN: break
        if key in seen: continue
        if text_of: text = text_of(key)
        if text and (not name.startswith("mefa") or KEYWORDS.search(text)): publish(text, name, english)
        seen.append(key)
    state["seen"][name] = seen[-300:]

for name, url in RSS.items():
    try: run_source(name, rss_items(url))
    except Exception as e: print(f"{name}: error {e}")
try: run_source("wco", wco_items(), wco_text, english=True, first_run_post=2)
except Exception as e: print(f"wco: error {e}")

save_state()
print("done, posted:", sent)
