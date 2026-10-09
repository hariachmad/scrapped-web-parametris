import hashlib, os, re
from pathlib import Path
from urllib.parse import urlparse, urljoin, unquote, quote
from playwright.sync_api import sync_playwright

URL = "https://www.parametris.com/kontak/"
OUT = Path("parametris.com/pages/kontak")
ASSETS = OUT / "assets"
OUT.mkdir(exist_ok=True)

saved = {}  
KEEP = {"stylesheet", "script", "image", "font", "media"}


def safe(part):
    return re.sub(r'[<>:"|?*\\]', "_", part)


def local_path(url):
    p = urlparse(url)
    path = unquote(p.path)
    if not path or path.endswith("/"):
        path += "index"
    parts = [safe(x) for x in path.strip("/").split("/")]
    local = ASSETS / safe(p.netloc) / Path(*parts)
    if p.query:
        h = hashlib.md5(p.query.encode()).hexdigest()[:8]
        local = local.with_name(f"{local.stem}_{h}{local.suffix}")
    return local


def save(url, body):
    if url in saved or url.startswith("data:"):
        return
    f = local_path(url)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(body)
    saved[url] = f


def rel(from_file, to_file):
    r = os.path.relpath(to_file, from_file.parent).replace(os.sep, "/")
    return quote(r)


def on_response(resp):
    try:
        if resp.request.resource_type in KEEP and resp.status == 200:
            save(resp.url, resp.body())
    except Exception:
        pass


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1366, "height": 768})
    page.on("response", on_response)

    page.goto(URL, wait_until="load", timeout=60000)
    page.wait_for_load_state("networkidle")

    last = 0
    while True:
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(1000)
        h = page.evaluate("document.body.scrollHeight")
        if h == last:
            break
        last = h
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    lazy = page.evaluate("""() => {
        const attrs = ['data-lazyload','data-src','data-src-rs-ref','data-thumb'];
        const out = new Set();
        document.querySelectorAll('*').forEach(el =>
            attrs.forEach(a => { const v = el.getAttribute(a); if (v) out.add(v); }));
        return [...out];
    }""")
    for v in lazy:
        u = urljoin(page.url, v)
        if u.startswith("http") and u not in saved:
            try:
                r = page.request.get(u)
                if r.ok:
                    save(u, r.body())
            except Exception as e:
                print("gagal:", u, e)

    html = page.content()
    base_url = page.url
    browser.close()

for url, f in list(saved.items()):
    if f.suffix.lower() != ".css":
        continue
    css = f.read_text(encoding="utf-8", errors="ignore")

    def fix(m):
        ref = m.group(2).strip()
        if ref.startswith(("data:", "#")):
            return m.group(0)
        target = urljoin(url, ref)
        if target in saved:
            return f"{m.group(1)}{rel(f, saved[target])}{m.group(3)}"
        return m.group(0)

    css = re.sub(r"""(url\(\s*['"]?)([^'")]+)(['"]?\s*\))""", fix, css)
    css = re.sub(r"""(@import\s+['"])([^'"]+)(['"])""", fix, css)
    f.write_text(css, encoding="utf-8")

index = OUT / "index.html"
mapping = {}
for url, f in saved.items():
    r = rel(index, f)
    no_scheme = re.sub(r"^https?:", "", url)
    for v in {url, no_scheme}:
        mapping[v] = r
        mapping[v.replace("&", "&amp;")] = r
        mapping[v.replace("/", "\\/")] = r  

pattern = re.compile("|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
html = pattern.sub(lambda m: mapping[m.group(0)], html)

origin_host = urlparse(base_url).netloc
for url, f in saved.items():
    pu = urlparse(url)
    if pu.netloc == origin_host:
        path = pu.path + (f"?{pu.query}" if pu.query else "")
        html = re.sub(r"""(?<=["'(,=\s])""" + re.escape(path), rel(index, f), html)

html = re.sub(r'\s(integrity|crossorigin)="[^"]*"', "", html)

index.write_text(html, encoding="utf-8")
print(f"Selesai. {len(saved)} aset disimpan. Buka: {index.resolve()}")