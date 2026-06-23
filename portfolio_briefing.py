"""
포트폴리오 자동 브리핑
- 국내 뉴스/종가: 네이버 API + pykrx
- 해외 뉴스/종가: yfinance
- 발송: Gmail SMTP + 카카오톡 나에게 보내기

환경변수 (GitHub Secrets):
  NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
  GMAIL_ADDRESS, GMAIL_APP_PASSWORD
  KAKAO_REST_API_KEY, KAKAO_REFRESH_TOKEN
  BRIEFING_TYPE = morning | evening
"""

import os, json, re, urllib.request, urllib.parse, smtplib, requests
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── 환경변수 ──────────────────────────────────────────────
NAVER_ID       = os.environ["NAVER_CLIENT_ID"]
NAVER_SECRET   = os.environ["NAVER_CLIENT_SECRET"]
GMAIL_ADDRESS  = os.environ["GMAIL_ADDRESS"]
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
KAKAO_API_KEY  = os.environ["KAKAO_REST_API_KEY"]
KAKAO_REFRESH  = os.environ["KAKAO_REFRESH_TOKEN"]
BRIEFING_TYPE  = os.environ.get("BRIEFING_TYPE", "evening")  # morning | evening

# ── 날짜 계산 ─────────────────────────────────────────────
KST   = timezone(timedelta(hours=9))
today = datetime.now(KST).date()

if BRIEFING_TYPE == "morning":
    # 월요일이면 금요일 기준
    news_date      = today - timedelta(days=3 if today.weekday() == 0 else 1)
    briefing_emoji = "🌅"
    briefing_name  = "모닝 브리핑"
    time_note      = f"전일 기준 ({news_date.strftime('%m/%d')})"
else:
    news_date      = today
    briefing_emoji = "📊"
    briefing_name  = "마감 브리핑"
    time_note      = "당일 기준"

TODAY_KR       = today.strftime("%Y년 %m월 %d일")
NEWS_DATE_KR   = news_date.strftime("%Y년 %m월 %d일")
NEWS_DATE_EN   = news_date.strftime("%B %d %Y")
NEWS_DATE_LABEL = news_date.strftime("%d %b %Y")   # pubDate 매칭용
NEWS_DATE_STR  = news_date.strftime("%Y%m%d")
FROM_DATE_STR  = (news_date - timedelta(days=5)).strftime("%Y%m%d")

# ── 종목 설정 ─────────────────────────────────────────────
KR_STOCKS = {
    "삼성전자":          ("005930", "삼성전자"),
    "한솔케미칼":        ("014680", "한솔케미칼"),
    "ISC":              ("095340", "ISC 반도체"),
    "KODEX 2차전지산업": ("305720", "KODEX 2차전지산업"),
}
US_STOCKS = {
    "하우멧 에어로스페이스": "HWM",
    "시에나":               "CIEN",
    "브로드컴":             "AVGO",
}

# ── 유틸 ──────────────────────────────────────────────────
def strip_html(t): return re.sub(r"<[^>]+>", "", t or "")

def arrow(v): return "🔴▲" if v >= 0 else "🔵▼"

# ── 가격 수집 ─────────────────────────────────────────────
def get_kr_price(code):
    try:
        from pykrx import stock
        df = stock.get_market_ohlcv_by_date(FROM_DATE_STR, NEWS_DATE_STR, code)
        if df is None or df.empty: return None
        r = df.iloc[-1]
        close = int(r["종가"]); prev = int(r["시가"])
        chg = close - prev; pct = chg / prev * 100
        return {"price": f"{close:,}원", "chg": chg, "pct": pct}
    except: return None

def get_us_price(ticker):
    try:
        import yfinance as yf
        fi = yf.Ticker(ticker).fast_info
        price = fi.last_price; prev = fi.previous_close
        chg = price - prev; pct = chg / prev * 100
        return {"price": f"${price:,.2f}", "chg": chg, "pct": pct}
    except: return None

# ── 뉴스 수집 ─────────────────────────────────────────────
def get_kr_news(query):
    try:
        enc = urllib.parse.quote(query)
        url = (f"https://openapi.naver.com/v1/search/news.json"
               f"?query={enc}&sort=date&display=30")
        req = urllib.request.Request(url)
        req.add_header("X-Naver-Client-Id",     NAVER_ID)
        req.add_header("X-Naver-Client-Secret", NAVER_SECRET)
        with urllib.request.urlopen(req, timeout=10) as r:
            items = json.loads(r.read().decode())["items"]
        result = []
        for i in [x for x in items if NEWS_DATE_LABEL in x.get("pubDate", "")][:3]:
            result.append({
                "title": strip_html(i["title"]),
                "time":  i["pubDate"][17:22],
                "desc":  strip_html(i.get("description",""))[:100],
                "link":  i.get("originallink") or i["link"],
            })
        return result
    except: return []

def get_us_news(ticker):
    try:
        import yfinance as yf
        from deep_translator import GoogleTranslator
        tr = GoogleTranslator(source="en", target="ko")
        result = []
        for a in (yf.Ticker(ticker).news or []):
            pub_dt = datetime.fromtimestamp(a.get("providerPublishTime", 0), tz=KST).date()
            if pub_dt == news_date:
                title_en = a.get("title", "")
                result.append({
                    "title":    tr.translate(title_en[:400]),
                    "title_en": title_en,
                    "time":     datetime.fromtimestamp(a["providerPublishTime"], tz=KST).strftime("%H:%M"),
                    "desc":     tr.translate((a.get("summary","") or "")[:300]),
                    "link":     a.get("link",""),
                    "source":   a.get("publisher",""),
                })
            if len(result) >= 3: break
        return result
    except: return []

# ── 카카오 토큰 갱신 ──────────────────────────────────────
def get_kakao_access_token():
    res = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type":    "refresh_token",
            "client_id":     KAKAO_API_KEY,
            "refresh_token": KAKAO_REFRESH,
        },
        timeout=10
    )
    return res.json().get("access_token")

# ── 카카오톡 나에게 보내기 ─────────────────────────────────
def send_kakao(text):
    token = get_kakao_access_token()
    template = {
        "object_type": "text",
        "text": text[:2000],
        "link": {"web_url": "", "mobile_web_url": ""}
    }
    res = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {token}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=10
    )
    return res.json()

# ── Gmail 발송 ────────────────────────────────────────────
def send_gmail(subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = GMAIL_ADDRESS
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        s.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())

# ── 데이터 수집 ───────────────────────────────────────────
print(f"\n⏳ {briefing_name} 데이터 수집 중... (기준: {NEWS_DATE_KR})")
data = {}

for name, (code, query) in KR_STOCKS.items():
    print(f"  🇰🇷 {name}")
    data[name] = {"flag":"🇰🇷", "id":code,
                  "price": get_kr_price(code),
                  "news":  get_kr_news(query), "us": False}

for name, ticker in US_STOCKS.items():
    print(f"  🌐 {name} ({ticker})")
    data[name] = {"flag":"🌐", "id":ticker,
                  "price": get_us_price(ticker),
                  "news":  get_us_news(ticker), "us": True}

# ── 텍스트 브리핑 (카카오톡용) ────────────────────────────
lines = [f"{briefing_emoji} 포트폴리오 {briefing_name} | {TODAY_KR}",
         f"({time_note})",
         "━" * 22]

for name, d in data.items():
    p = d["price"]
    if p:
        a = arrow(p["chg"]); amt = abs(p["chg"])
        amt_str = f"{amt:,}원" if not d["us"] else f"${amt:.2f}"
        lines.append(f"\n{d['flag']} {name} ({d['id']})")
        lines.append(f"💰 {p['price']}  {a} {amt_str} ({abs(p['pct']):.2f}%)")
    else:
        lines.append(f"\n{d['flag']} {name} ({d['id']})")
        lines.append("💰 가격 조회 불가 (장 미개장)")

    lines.append("📰 뉴스")
    if not d["news"]:
        lines.append("  해당일 뉴스 없음")
    for i, n in enumerate(d["news"], 1):
        t = f"[{n['time']}] " if n.get("time") else ""
        lines.append(f"  {i}. {t}{n['title']}")
        if n.get("title_en"):
            lines.append(f"     (원문: {n['title_en']})")
        if n.get("link"):
            lines.append(f"     🔗 {n['link']}")
    lines.append("━" * 22)

lines.append("⚙️ Cowork 자동 브리핑 | GitHub Actions")
kakao_text = "\n".join(lines)

# ── HTML 이메일 (Gmail용) ─────────────────────────────────
def price_row(d):
    p = d["price"]
    if not p: return '<p style="color:#999">가격 조회 불가</p>'
    a = arrow(p["chg"]); amt = abs(p["chg"])
    amt_str = f"{amt:,}원" if not d["us"] else f"${amt:.2f}"
    color = "#e03131" if p["chg"] >= 0 else "#1971c2"
    return (f'<span style="font-size:1.3em;font-weight:700">{p["price"]}</span> '
            f'<span style="color:{color};font-weight:600">'
            f'{a} {amt_str} ({abs(p["pct"]):.2f}%)</span>')

def news_rows(d):
    if not d["news"]: return "<p style='color:#aaa'>해당일 뉴스 없음</p>"
    html = ""
    for n in d["news"]:
        t = f'<span style="background:#f1f3f5;padding:1px 6px;border-radius:4px;font-size:.78em">{n["time"]}</span> ' if n.get("time") else ""
        orig = f'<div style="color:#bbb;font-size:.75em;font-style:italic">원문: {n.get("title_en","")}</div>' if n.get("title_en") else ""
        desc = f'<div style="color:#555;font-size:.83em;margin-top:2px">{n.get("desc","")}</div>' if n.get("desc") else ""
        link = n.get("link","#")
        html += (f'<div style="padding:8px 0;border-bottom:1px solid #f5f5f5">'
                 f'<a href="{link}" style="color:#1a1a2e;font-weight:600;text-decoration:none">{t}{n["title"]}</a>'
                 f'{orig}{desc}</div>')
    return html

cards = ""
for name, d in data.items():
    cards += f"""
    <div style="background:#fff;border-radius:14px;padding:18px;
                box-shadow:0 2px 10px rgba(0,0,0,.07);margin-bottom:16px">
      <div style="font-size:1.1em;font-weight:700;margin-bottom:8px">
        {d['flag']} {name} <span style="color:#aaa;font-size:.8em;font-weight:400">({d['id']})</span>
      </div>
      <div style="padding:8px 0;border-bottom:1px solid #f1f3f5;margin-bottom:10px">
        {price_row(d)}
      </div>
      <div style="font-size:.78em;color:#888;font-weight:600;margin-bottom:6px">📰 뉴스</div>
      {news_rows(d)}
    </div>"""

html_body = f"""
<div style="font-family:-apple-system,sans-serif;background:#f0f2f5;padding:24px;max-width:680px;margin:0 auto">
  <h2 style="text-align:center;margin-bottom:4px">{briefing_emoji} 포트폴리오 {briefing_name}</h2>
  <p style="text-align:center;color:#888;margin-bottom:20px">{TODAY_KR} · {time_note}</p>
  {cards}
  <p style="text-align:center;color:#ccc;font-size:.78em;margin-top:16px">
    GitHub Actions 자동 브리핑 · 국내: 네이버 API · 해외: Yahoo Finance
  </p>
</div>"""

# ── 발송 ──────────────────────────────────────────────────
subject = f"{briefing_emoji} {briefing_name} - {TODAY_KR}"

print("\n📱 카카오톡 전송 중...")
try:
    result = send_kakao(kakao_text)
    print(f"  ✅ 카카오톡 전송 완료: {result}")
except Exception as e:
    print(f"  ❌ 카카오톡 실패: {e}")

print("📧 Gmail 발송 중...")
try:
    send_gmail(subject, html_body)
    print(f"  ✅ Gmail 발송 완료 → {GMAIL_ADDRESS}")
except Exception as e:
    print(f"  ❌ Gmail 실패: {e}")

print(f"\n✅ {briefing_name} 완료")
