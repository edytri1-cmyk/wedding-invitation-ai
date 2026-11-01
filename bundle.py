# bundle.py - JADIKAN FORMAL_KANTOR_01 JADI 1 FILE HTML
from pathlib import Path
import base64
import re

tpl_dir = Path("templates/FORMAL_KANTOR_01")
index_path = tpl_dir / "index.html"
html = index_path.read_text(encoding='utf-8', errors='ignore')

# 1. INLINE SEMUA CSS
# Cari <link href="./css/xxx.css">
for link in re.findall(r'<link.*?href="\./css/(.*?)".*?>', html):
    css_path = tpl_dir / "css" / link
    if css_path.exists():
        css_content = css_path.read_text(encoding='utf-8', errors='ignore')
        html = html.replace(f'<link rel="stylesheet" href="./css/{link}">', f"<style>\n/* {link} */\n{css_content}\n</style>", 1)
        # handle variasi tanpa rel
        html = re.sub(rf'<link[^>]*{re.escape(link)}[^>]*>', f"<style>\n{css_content}\n</style>", html, count=1)

# 2. INLINE SEMUA JS (auto-detect file apapun di js/ )
js_dir = tpl_dir / "js"
combined_js = ""
if js_dir.exists():
    for js_file in sorted(js_dir.rglob("*.js"), key=lambda x: x.stat().st_size):
        combined_js += f"\n// {js_file.name}\n" + js_file.read_text(encoding='utf-8', errors='ignore') + "\n"

if combined_js:
    # hapus semua <script src="./js/...">
    html = re.sub(r'<script\s+src="\./js/.*?\.js"></script>', '', html)
    html = re.sub(r'<script\s+src="\./dist/.*?\.js"></script>', '', html)
    html = html.replace("</body>", f"<script>\n{combined_js}\n</script>\n</body>")

# 3. FIX PLACEHOLDER IMAGE jadi base64 biar gak 404
# Kalau ada file placeholder.webp, jadiin base64
placeholder_path = tpl_dir / "assets" / "images" / "placeholder.webp"
if placeholder_path.exists():
    b64 = base64.b64encode(placeholder_path.read_bytes()).decode()
    data_uri = f"data:image/webp;base64,{b64}"
    html = html.replace("./assets/images/placeholder.webp", data_uri)

# 4. HAPUS LOADING SCREEN YANG BIKIN PUTIH
html = html.replace('id="loading-screen"', 'id="loading-screen" style="display:none!important;"')

# 5. SAVE JADI SINGLE FILE
output = tpl_dir / "index.single.html"
output.write_text(html, encoding='utf-8')
print(f"✅ Selesai! File single: {output} - Size: {len(html)//1024} KB")

# Juga overwrite index.html biar preview langsung pakai yang single
index_path.write_text(html, encoding='utf-8')
print("✅ index.html sudah di-overwrite jadi versi single file anti-putih")