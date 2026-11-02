import os, io, re, base64, time, uuid, html, json, urllib.request, urllib.parse, urllib.error

DRY = os.environ.get("DRY_RUN") == "1"
TG = os.environ.get("TG_TOKEN", "")
# Google key first; the AvalAI key (same native Gemini API on its own host) is the backup
KEYS = [k for k in (os.environ.get("GEMINI_API_KEY"), os.environ.get("GEMINI_API_KEY_2")) if k]
BASES = ["https://generativelanguage.googleapis.com/v1beta/models/" if k == os.environ.get("GEMINI_API_KEY") else "https://api.avalai.ir/v1beta/models/" for k in KEYS]
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

def fetch_bytes(url, data=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout).read()

def fetch(url, data=None, headers=None, timeout=60):
    return fetch_bytes(url, data, headers, timeout).decode("utf-8", "replace")

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
PAID_MODELS = ["gemini-3.1-flash-lite"]           # the only text model used on the paid AvalAI key
PAID_IMAGE_MODELS = ["gemini-2.5-flash-image"]     # the only (cheapest) image model used on the paid AvalAI key

def plan(models, paid):
    """Every free (Google) attempt before any paid (AvalAI) one."""
    return [(m, i) for i in range(len(KEYS)) for m in (models if BASES[i].startswith("https://generativelanguage") else paid)]

def ask(prompt, as_json=False, search=False, max_tokens=None):
    wait = 13 - (time.time() - _last_gemini[0])  # free tier: keep under ~5 requests/minute
    if wait > 0: time.sleep(wait)
    _last_gemini[0] = time.time()
    req = {"contents": [{"parts": [{"text": prompt}]}]}
    cfg = {}
    if as_json: cfg["responseMimeType"] = "application/json"
    if max_tokens: cfg["maxOutputTokens"] = max_tokens
    if cfg: req["generationConfig"] = cfg
    last = None
    for model, i in plan(MODELS, PAID_MODELS):
            key = KEYS[i]
            paid = not BASES[i].startswith("https://generativelanguage")
            if search and paid: raise RuntimeError("search is free-key only")
            body = json.dumps({**req, **({"tools": [{"google_search": {}}]} if search else {})}).encode()
            if (model, i) in dead_models: continue
            try:
                r = json.loads(fetch(f"{BASES[i]}{model}:generateContent",
                                     body, {"x-goog-api-key": key, "content-type": "application/json"}, timeout=300))
                return "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"]).strip()
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (429, 404, 403):
                    dead_models.add((model, i)); print(f"model {model} key{i + 1} unavailable ({e.code})"); continue
                if e.code in (500, 502, 503, 504):
                    print(f"model {model} overloaded ({e.code}), trying next"); continue
                if search and e.code == 400: raise
                raise
            except (TimeoutError, urllib.error.URLError) as e:  # long briefs can outlast a slow key: try the next one
                last = e; print(f"model {model} key{i + 1} timed out ({e}), trying next"); continue
    raise last or RuntimeError("no Gemini model available")

# strongest image model first; each is tried on every key before falling back to a weaker one
IMAGE_MODELS = ["gemini-3-pro-image", "gemini-3-pro-image-preview", "gemini-3.1-flash-image",
                "gemini-3.1-flash-image-preview", "gemini-2.5-flash-image", "gemini-3.1-flash-lite-image"]
BASE_SCENE = "Photorealistic editorial photograph, wide 16:9, shallow depth of field, natural light. "
SCENES = ['A busy container port with stacked plain-coloured shipping containers, a large gantry crane and a cargo ship at the quay, golden hour light.', 'Aerial view of a cargo ship loaded with plain-coloured containers entering a harbour at sunrise.', 'A long row of cargo trucks and plain-coloured containers at a border terminal, dusk light, shallow depth of field.', 'Forklift moving wooden pallets of plain cardboard boxes inside a large clean warehouse, soft light from skylights.', 'Gantry cranes silhouetted against an orange sky above stacked containers at a port, wide shot.', 'Close view of plain stacked shipping containers with rust-free colour blocks, shallow depth of field, soft overcast light.']

def scene_for(title):
    return BASE_SCENE + SCENES[sum(map(ord, title)) % len(SCENES)] + " Clean scene with plain surfaces only, nothing with writing on it."
CF_TOKEN, CF_ACCOUNT = os.environ.get("CF_API_TOKEN"), os.environ.get("CF_ACCOUNT_ID")

def gen_image_cf(prompt):
    """Cloudflare Workers AI, FLUX.1 schnell: free daily allowance, so it goes before any paid model."""
    if not (CF_TOKEN and CF_ACCOUNT): return None
    try:
        body = json.dumps({"prompt": prompt, "steps": 6}).encode()
        r = json.loads(fetch(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/@cf/black-forest-labs/flux-1-schnell",
                             body, {"Authorization": f"Bearer {CF_TOKEN}", "content-type": "application/json"}, timeout=120))
        print("image by cloudflare flux-1-schnell")
        return base64.b64decode(r["result"]["image"])
    except Exception as e:
        print(f"cloudflare image failed: {e}"); return None

def gen_image(prompt, cf_prompt=None):
    img = gen_image_cf(cf_prompt or prompt)
    if img: return img
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "16:9"}}}).encode()
    for model, i in plan(IMAGE_MODELS, PAID_IMAGE_MODELS):
            key = KEYS[i]
            if (model, i) in dead_models: continue
            try:
                r = json.loads(fetch(f"{BASES[i]}{model}:generateContent",
                                     body, {"x-goog-api-key": key, "content-type": "application/json"}))
                for p in r["candidates"][0]["content"]["parts"]:
                    if "inlineData" in p:
                        print(f"image by {model} key{i + 1}")
                        return base64.b64decode(p["inlineData"]["data"])
            except urllib.error.HTTPError as e:
                if e.code in (429, 404, 403, 400): dead_models.add((model, i))
                print(f"image model {model} key{i + 1} failed ({e.code})")
            except Exception as e:
                print(f"image model {model} key{i + 1} failed ({e})")
    return None


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

BRIEF_SKILL = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "brief_skill.md"), encoding="utf-8").read()

ARTICLE_PROMPT = """تو نویسنده‌ی ارشد بلاگ «اسکله» (حمل بین‌المللی و ترخیص کالا) هستی.
بریف سئوی زیر را مو‌به‌مو اجرا کن و مقاله‌ی کامل فارسی بنویس: ساختار H2 و H3، نکته‌ها، پرسش‌های متداول و طول هدف بریف را رعایت کن و جای همه‌ی یادداشت‌های داخل [ ] را با متن واقعی پر کن.
واقعیت‌ها، عددها، نام‌ها و تاریخ‌ها فقط از خبر اصلی بیایند؛ عدد یا آمار یا نقل‌قول جدید نساز. می‌توانی زمینه، توضیح مفاهیم و راهنمای عملی عمومی برای خواننده اضافه کنی.

خبر اصلی (منبع: {src}):
{text}

بریف:
{brief}

فقط یک شیء JSON معتبر برگردان:
{{"title": "H1 / عنوان سئو (حداکثر ۷۰ حرف)", "excerpt": "خلاصه‌ی یک‌جمله‌ای", "seo_description": "توضیح متا تا ۱۵۵ حرف", "paragraphs": ["پاراگراف", "## تیتر H2", "پاراگراف", "### تیتر H3 را هم با ## بنویس", "..."]}}
هر عنصر paragraphs یا یک پاراگراف است یا تیتری که با «## » شروع می‌شود. حداکثر ۵۵ عنصر."""

def blog_draft(text, src, link, cover_jpg=None):
    if not (BLOG_URL and BLOG_TOKEN): return
    try:
        brief_req = BRIEF_SKILL + "\n\n---\nبرای خبر زیر یک بریف مقاله‌ی بلاگ (Article / Blog Brief) به زبان فارسی بساز. کلمه‌ی کلیدی اصلی را خودت از خبر استخراج کن.\n\n" + text[:3000]
        try: brief = ask(brief_req, search=True, max_tokens=2500)
        except Exception as e:
            print(f"brief with search failed ({e}), retrying without search"); brief = ask(brief_req, max_tokens=2500)
        raw = ask(ARTICLE_PROMPT.format(src=src, text=text[:3000], brief=brief[:8000]), as_json=True, max_tokens=6000)
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip()
        art = json.loads(raw)
        art["paragraphs"] = [p.replace("### ", "## ", 1) for p in art["paragraphs"] if isinstance(p, str) and p.strip()][:60]
        art["title"] = art["title"][:180]
        art["source_url"] = link if link.startswith("https://") else None
        if cover_jpg: art["cover"] = base64.b64encode(cover_jpg).decode()
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
        if OWNER_CHAT and not DRY:
            try: tg_api("sendMessage", {"chat_id": OWNER_CHAT, "text": f"⚠️ ساخت پیش‌نویس بلاگ ناموفق بود:\n{link}\n\n{str(e)[:500]}"})
            except Exception: pass

# --- cover: 1200x630 for the channel post and the blog. A Gemini image when one is available, else a brand card.
IMAGE_PROMPT = """Create a high-quality, photorealistic editorial cover photo (16:9) for a news story about international shipping, customs clearance, ports, containers and trade.
Headline (Persian): «{title}»
Show the real-world subject of the story in a clean, modern, professional style with natural light and depth.
Absolutely no text, letters, words, numbers, labels, UI text, screens with writing, logos, flags or watermarks anywhere in the image (Persian text is added later). Keep any screens or documents blurred or blank."""

def cover(out):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    line = next((l for l in out.splitlines() if l.strip()), "")
    title = re.sub("[^\\w\\s\u200c،؛:؟!%\\-.()«»]", "", line).strip()[:110]
    W, H = 1200, 630
    bg, bg2, fg, accent, sub = (12, 36, 48), (18, 52, 68), (232, 240, 244), (219, 167, 60), (91, 191, 229)
    here = os.path.dirname(os.path.abspath(__file__))
    fpath = os.path.join(here, "Vazir-Bold.ttf")
    photo = gen_image(IMAGE_PROMPT.format(title=title), scene_for(title))
    if photo:
        im = ImageOps.fit(Image.open(io.BytesIO(photo)).convert("RGB"), (W, H), Image.LANCZOS)
        band_h = 230
        band = Image.new("RGBA", (W, band_h), bg + (236,))
        im.paste(band, (0, H - band_h), band)
        d = ImageDraw.Draw(im)
        d.rectangle([0, H - band_h, W, H - band_h + 6], fill=accent)
        size, max_lines, top = 44, 2, H - band_h + 34
    else:
        im = Image.new("RGB", (W, H)); d = ImageDraw.Draw(im)
        for y in range(H):
            d.line([(0, y), (W, y)], fill=tuple(a + (b - a) * y // H for a, b in zip(bg, bg2)))
        d.rectangle([W - 18, 0, W, H], fill=accent)
        size, max_lines, top = 58, 4, None
    font = ImageFont.truetype(fpath, size); small = ImageFont.truetype(fpath, 28)
    lines, cur = [], ""
    for w in title.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) > W - 200 and cur: lines.append(cur); cur = w
        else: cur = t
    lines = (lines + [cur])[:max_lines]
    y = top if top is not None else (H - 120 - len(lines) * int(size * 1.45)) // 2
    for l in lines:
        d.text((W - 70, y), l, font=font, fill=fg, anchor="ra"); y += int(size * 1.45)
    logo = Image.open(os.path.join(here, "watermark.png")).convert("RGBA").resize((76, 76), Image.LANCZOS)
    im.paste(logo, (70, H - 110), logo)
    d.text((162, H - 72), "eskele.org", font=small, fill=accent if photo else sub, anchor="lm")
    b = io.BytesIO(); im.save(b, "JPEG", quality=92)
    return b.getvalue()

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
    photos = ([media["cover"]] if media.get("cover") else []) + get_photos(media["photos"][:3])
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
    try: media["cover"] = cover(out)
    except Exception as e: print(f"cover failed: {e}")
    msg = to_html(out)
    if len(msg) + len(FOOTER) > 4000: msg = msg[:4000 - len(FOOTER)].rsplit("\n", 1)[0]
    msg += FOOTER
    if DRY: print(f"[{src}] WOULD POST:\n{msg}\n")
    send(msg, media)
    if not DRY: time.sleep(8)
    if not DRY and link: blog_draft(text, src, link, media.get("cover"))
    state["recent"].append(out.replace("\n", " ")[:160])
    state["recent"] = state["recent"][-40:]
    sent += 1
    save_state()  # persist right after each post so a later crash can't cause duplicates
    return True

if os.environ.get("BACKFILL"):  # one-off: blog drafts for the channel's last 5 posts
    for pid, text, _ in tg_items("eskele_org")[-5:]:
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
