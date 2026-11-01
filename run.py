import os, io, re, time, uuid, html, json, urllib.request, urllib.parse, urllib.error

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

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15", "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"}

def fetch_bytes(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=60).read()

def fetch(url, data=None, headers=None):
    return fetch_bytes(url, data, headers).decode("utf-8", "replace")

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

def new_media():
    return {"photos": [], "videos": [], "docs": []}

def add_media(m, url):
    url = html.unescape(url.strip())
    if not url.startswith("http"): return
    ext = url.split("?")[0].lower().rsplit(".", 1)[-1]
    kind = ("photos" if ext in ("jpg", "jpeg", "png", "webp") else
            "videos" if ext in ("mp4", "mov", "webm") else
            "docs" if ext in ("pdf", "doc", "docx", "xls", "xlsx", "zip", "rar", "ppt", "pptx") else None)
    if kind and url not in m[kind]: m[kind].append(url)

def tg_items(ch):
    page = fetch(f"https://t.me/s/{ch}")
    out = []
    for blk in page.split("tgme_widget_message_wrap")[1:]:
        m = re.search(r'data-post="[^/]+/(\d+)"', blk)
        t = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', blk, re.S)
        if not m: continue
        media = new_media()
        for u in re.findall(r"tgme_widget_message_photo_wrap[^>]*background-image:url\('([^']+)'\)", blk):
            if u not in media["photos"]: media["photos"].append(html.unescape(u))
        for u in re.findall(r'<video[^>]+src="([^"]+)"', blk):
            if u not in media["videos"]: media["videos"].append(html.unescape(u))
        out.append((int(m.group(1)), clean(t.group(1)) if t else "", media))
    return out

def rss_items(url):
    x = fetch(url)
    out = []
    for it in re.findall(r"<item>(.*?)</item>", x, re.S):
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1]
        link = clean(g("link")) or clean(g("guid"))
        raw = re.sub(r"<!\[CDATA\[|\]\]>", "", g("content:encoded") or g("description"))
        text = clean(re.sub(r"<!\[CDATA\[|\]\]>", "", g("title"))) + "\n\n" + clean(raw)
        media = new_media()
        for u in re.findall(r'<(?:enclosure|media:content)[^>]+url="([^"]+)"', it): add_media(media, u)
        for u in re.findall(r'<img[^>]+src="([^"]+)"', raw)[:3]: add_media(media, u)
        for u in re.findall(r'href="([^"]+\.(?:pdf|docx?|xlsx?|zip|rar))"', raw, re.I)[:2]: add_media(media, u)
        out.append((link, text[:3500], media))
    return out

def wco_items():
    page = fetch(WCO_LIST)
    links = []
    for l in re.findall(r"newsroom/(20\d\d/[a-z]+/[^'\"\s]+?\.aspx)", page):
        if l not in links: links.append(l)
    return [("https://www.wcoomd.org/en/media/newsroom/" + l, None, None) for l in links[:8]]

def wco_text(url):
    p = fetch(url)
    title = clean((re.search(r"<h1[^>]*>(.*?)</h1>", p, re.S) or [None, ""])[1])
    paras = [clean(x) for x in re.findall(r"<p[^>]*>(.*?)</p>", p, re.S)]
    body = "\n".join(x for x in paras if len(x) > 50)
    media = new_media()
    for u in re.findall(r'<img[^>]+src="([^"]+)"', p):
        if "press-releases" not in u and "/images/media/" not in u: continue
        full = urllib.parse.urljoin(url, html.unescape(u).split("?")[0])
        if full not in media["photos"]: media["photos"].append(full)
    for u in re.findall(r'href="([^"]+\.pdf)"', p, re.I)[:2]: add_media(media, urllib.parse.urljoin(url, u))
    return (title + "\n\n" + body)[:3500], media

_last_gemini = [0.0]
def ask(prompt, as_json=False):
    wait = 13 - (time.time() - _last_gemini[0])  # free tier: keep under ~5 requests/minute
    if wait > 0: time.sleep(wait)
    _last_gemini[0] = time.time()
    req = {"contents": [{"parts": [{"text": prompt}]}]}
    if as_json: req["generationConfig"] = {"responseMimeType": "application/json"}
    body = json.dumps(req).encode()
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

def rewrite(text, src, english=False):
    recent = "\n".join(f"- {r}" for r in state["recent"][-30:]) or "(هنوز موردی نیست)"
    prompt = PROMPT.format(recent=recent, src=src, text=text,
                           lang="، متن انگلیسی" if english else "",
                           translate="متن انگلیسی است؛ آن را به فارسی روان و طبیعی ترجمه و بازنویسی کن (نه ترجمه‌ی تحت‌اللفظی؛ اصطلاحات گمرکی را با معادل رایج فارسی بنویس)." if english else "")
    return ask(prompt)

def save_state():
    if not DRY:
        json.dump(state, open("state.json", "w"), ensure_ascii=False)

def to_html(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t, flags=re.S)
    t = re.sub(r"(?m)^\s*[\*\-]\s+", "▫️ ", t)
    return t.replace("*", "")

BLOG_URL = os.environ.get("BLOG_URL", "")
BLOG_TOKEN = os.environ.get("BLOG_INGEST_TOKEN", "")
OWNER_CHAT = os.environ.get("OWNER_CHAT_ID", "")

BLOG_PROMPT = """تو نویسنده‌ی بلاگ «اسکله» (حمل بین‌المللی و ترخیص کالا) هستی.
از خبر زیر یک مقاله‌ی فارسی کامل‌تر از پست کانال بنویس: ۳ تا ۵ بخش با تیتر میانی، هر بخش ۲ تا ۴ جمله، و در آخر جمع‌بندی کوتاه برای فعالان بازرگانی.
فقط به واقعیت‌های خبر تکیه کن، چیزی اضافه نکن، و عددها، نام‌ها و مهلت‌ها را دقیق نگه دار.

خبر (منبع: {src}):
{text}

فقط یک شیء JSON معتبر برگردان با این کلیدها (بدون ``` یا متن اضافه):
{{"title": "تیتر فارسی کوتاه و جذاب (۶۰ تا ۹۰ حرف)", "excerpt": "خلاصه‌ی یک‌جمله‌ای", "seo_description": "توضیح متا تا ۱۵۰ حرف", "paragraphs": ["پاراگراف", "## تیتر میانی", "پاراگراف", "..."]}}"""

def blog_draft(text, src, link):
    if not (BLOG_URL and BLOG_TOKEN): return
    try:
        raw = ask(BLOG_PROMPT.format(src=src, text=text[:3000]), as_json=True)
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip()
        art = json.loads(raw)
        art["paragraphs"] = [p for p in art["paragraphs"] if isinstance(p, str) and p.strip()][:60]
        art["source_url"] = link if link.startswith("https://") else None
        if DRY:
            print("  blog draft:", art["title"]); return
        r = json.loads(call(BLOG_URL, json.dumps(art, ensure_ascii=False).encode(),
                            {"Content-Type": "application/json", "X-Ingest-Token": BLOG_TOKEN}))
        if OWNER_CHAT:
            tg_api("sendMessage", {"chat_id": OWNER_CHAT, "disable_web_page_preview": "true",
                   "text": f"📝 پیش‌نویس بلاگ آماده‌ی بررسی است:\n{art['title']}\n\nویرایش:\n{r['edit_url']}",
                   **({"reply_markup": json.dumps({"inline_keyboard": [[{"text": "✅ تأیید و انتشار", "url": r["approve_url"]}]]})} if r.get("approve_url") else {})})
    except Exception as e:
        print(f"blog draft failed: {e}")

# --- images: watermark with the eskele logo + domain
def watermark(raw):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    if min(im.size) < 200: raise ValueError("image too small")
    w, h = im.size
    logo = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "watermark.png")).convert("RGBA")
    size = max(48, int(min(w, h) * 0.13))
    logo = logo.resize((size, size))
    logo.putalpha(logo.getchannel("A").point(lambda a: int(a * 0.9)))
    font = ImageFont.load_default(size=max(14, size // 3))
    label = "eskele.org"
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pad = max(8, size // 5)
    tw = d.textlength(label, font=font)
    x_logo = w - pad - size
    y_logo = h - pad - size
    # soft dark pill behind the label so it reads on any photo
    d.rounded_rectangle([x_logo - tw - pad * 1.6, y_logo + size * 0.22, x_logo - pad * 0.4, y_logo + size * 0.78],
                        radius=size // 4, fill=(11, 37, 48, 170))
    d.text((x_logo - tw - pad, y_logo + size * 0.5), label, font=font, fill=(235, 197, 114, 255), anchor="lm")
    im = Image.alpha_composite(im, layer)
    im.alpha_composite(logo, (x_logo, y_logo))
    out = io.BytesIO(); im.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()

def multipart(fields, files):
    b = "----eskele" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (fname, data) in files.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={b}"}

def tg_api(method, fields, files=None):
    url = f"https://api.telegram.org/bot{TG}/{method}"
    if files:
        data, hdr = multipart(fields, files)
        return call(url, data, hdr)
    return call(url, urllib.parse.urlencode(fields).encode())

def get_photos(urls):
    out = []
    for u in urls[:4]:
        try:
            raw = fetch_bytes(u)
            if len(raw) > 9_000_000: continue
            out.append(watermark(raw))
        except Exception as e:
            print(f"photo skipped ({u[:60]}): {e}")
    return out

def send(msg, media):
    base = {"chat_id": DST, "parse_mode": "HTML"}
    photos = get_photos(media["photos"])
    if DRY:
        for i, p in enumerate(photos): open(f"out_{i}.jpg", "wb").write(p)
        print(f"  media: {len(photos)} photo(s) watermarked, {len(media['videos'])} video(s), {len(media['docs'])} doc(s)")
        return
    caption_ok = len(msg) <= 1024
    sent_text = False
    try:
        if len(photos) == 1 and caption_ok:
            tg_api("sendPhoto", {**base, "caption": msg}, {"photo": ("p.jpg", photos[0])}); sent_text = True
        elif photos:
            if len(photos) > 1:
                att = json.dumps([{"type": "photo", "media": f"attach://p{i}"} for i in range(len(photos))])
                tg_api("sendMediaGroup", {"chat_id": DST, "media": att}, {f"p{i}": (f"p{i}.jpg", p) for i, p in enumerate(photos)})
            else:
                tg_api("sendPhoto", {"chat_id": DST}, {"photo": ("p.jpg", photos[0])})
    except Exception as e:
        print(f"photo send failed: {e}")
    if not sent_text:
        tg_api("sendMessage", {**base, "text": msg, "disable_web_page_preview": "true"})
    for v in media["videos"][:1]:
        try: tg_api("sendVideo", {"chat_id": DST, "video": v})
        except Exception as e: print(f"video send failed: {e}")
    for d in media["docs"][:2]:
        try: tg_api("sendDocument", {"chat_id": DST, "document": d})
        except Exception as e: print(f"document send failed: {e}")

sent = 0
def publish(text, src, english=False, media=None, link=""):
    """Returns True when handled (sent, skipped or duplicate)."""
    global sent
    media = media or new_media()
    out = rewrite(text, src, english)
    head = out.split()[0].upper() if out.split() else ""
    if head in ("SKIP", "DUP") and len(out) < 8:
        print(f"[{src}] {head}: {text[:60]!r}"); return True
    msg = to_html(out)
    if len(msg) + len(FOOTER) > 4000: msg = msg[:4000 - len(FOOTER)].rsplit("\n", 1)[0]
    msg += FOOTER
    if DRY: print(f"[{src}] WOULD POST:\n{msg}\n")
    send(msg, media)
    if not DRY: time.sleep(8)
    if not DRY and link: blog_draft(text, src, link)
    state["recent"].append(out.replace("\n", " ")[:160])
    state["recent"] = state["recent"][-40:]
    sent += 1
    save_state()  # persist right after each post so a later crash can't cause duplicates
    return True

if os.environ.get("BACKFILL"):  # one-off: blog drafts for the channel's last 5 posts
    for pid, text, _ in [p for p in tg_items("eskele_org") if p[0] == 66]:
        text = text.split("━━━")[0].strip()
        print("backfill", pid, len(text))
        if text: blog_draft(text, "@eskele_org", "")
    raise SystemExit

# --- Telegram channels (numeric last-id)
for ch in TG_CHANNELS:
    if sent >= MAX_PER_RUN: break
    try:
        posts = tg_items(ch)
        if not posts:
            print(f"{ch}: no readable posts"); continue
        if ch not in state:
            state[ch] = max(p[0] for p in posts); continue
        for pid, text, media in sorted((p for p in posts if p[0] > state[ch]), key=lambda p: p[0]):
            if sent >= MAX_PER_RUN: break
            if text: publish(text, "@" + ch, media=media, link=f"https://t.me/{ch}/{pid}")
            state[ch] = pid
            save_state()
    except Exception as e:
        print(f"{ch}: error {e}")

# --- RSS / WCO (seen-set)
def run_source(name, items, text_of=None, english=False, first_run_post=0):
    global sent
    seen = state["seen"].setdefault(name, None)
    if seen is None:
        state["seen"][name] = [i[0] for i in items][first_run_post:]; print(f"{name}: baseline {len(items)}"); return
    for key, text, media in items:
        if sent >= MAX_PER_RUN: break
        if key in seen: continue
        if text_of: text, media = text_of(key)
        if text and (not name.startswith("mefa") or KEYWORDS.search(text)): publish(text, name, english, media, link=key)
        seen.append(key)
    state["seen"][name] = seen[-300:]

for name, url in RSS.items():
    try: run_source(name, rss_items(url))
    except Exception as e: print(f"{name}: error {e}")
try: run_source("wco", wco_items(), wco_text, english=True, first_run_post=2)
except Exception as e: print(f"wco: error {e}")

save_state()
print("done, posted:", sent)
