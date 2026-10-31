import os, re, time, html, json, urllib.request, urllib.parse

TG = os.environ["TG_TOKEN"]
KEY = os.environ["GEMINI_API_KEY"]
DST = "@eskele_org"
CHANNELS = ["Tarkhis_Karan", "Gomrok_news"]
state = json.load(open("state.json"))
if "last_id" in state:  # migrate old single-channel format
    state = {"Tarkhis_Karan": state["last_id"]}

FOOTER = """

━━━━━━━━━━━━━━
🚢 اسکله | حمل بین‌المللی و ترخیص کالا
حمل دریایی، هوایی، زمینی و ریلی و ترخیص از گمرکات؛ از استعلام تا تحویل درب‌به‌درب، با یک مسئول پرونده.
👉 eskele.org
📢 @eskele_org"""

PROMPT = """متن زیر یک خبر/بخشنامه‌ی گمرکی است. آن را به فارسی روان و با کلمات خودت بازنویسی کن؛ همه‌ی واقعیت‌ها، اعداد و فهرست‌ها دقیق بماند و چیزی اضافه نکن. با یک ایموجی و تیتر کوتاه شروع کن. امضای کانال، لینک منبع، آیدی و نام کانال مبدأ را حذف کن. اگر متن فقط تبریک/تاریخ روز و بدون محتواست، فقط کلمه‌ی SKIP را بنویس. فقط متن نهایی را بده.

"""

def fetch(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    return urllib.request.urlopen(req, timeout=60).read().decode()

def call(url, data=None, headers=None):
    for wait in (15, 40, 0):
        try:
            return fetch(url, data, headers)
        except urllib.error.HTTPError as e:
            if e.code != 429 or not wait: raise
            time.sleep(wait)

def get_posts(ch):
    page = fetch(f"https://t.me/s/{ch}")
    posts = []
    for blk in page.split("tgme_widget_message_wrap")[1:]:
        m = re.search(r'data-post="[^/]+/(\d+)"', blk)
        t = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', blk, re.S)
        if not m: continue
        text = ""
        if t:
            text = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", t.group(1)))).strip()
        posts.append((int(m.group(1)), text))
    return posts

for ch in CHANNELS:
    try:
        posts = get_posts(ch)
        if not posts:
            print(f"{ch}: no readable posts (web preview disabled?)"); continue
        if ch not in state:  # first sight: baseline only, don't flood
            state[ch] = max(i for i, _ in posts); continue
        for pid, text in sorted(p for p in posts if p[0] > state[ch])[:5]:  # max 5 per run
            if text:
                body = json.dumps({"contents": [{"parts": [{"text": PROMPT + text}]}]}).encode()
                r = json.loads(call("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                                    body, {"x-goog-api-key": KEY, "content-type": "application/json"}))
                out = r["candidates"][0]["content"]["parts"][0]["text"].strip()
                if not out.upper().startswith("SKIP"):
                    call(f"https://api.telegram.org/bot{TG}/sendMessage",
                         urllib.parse.urlencode({"chat_id": DST, "text": out + FOOTER}).encode())
                    time.sleep(8)  # stay under Gemini/Telegram rate limits
            state[ch] = pid  # advance only after success
    except Exception as e:
        print(f"{ch}: error {e}")

json.dump(state, open("state.json", "w"))
