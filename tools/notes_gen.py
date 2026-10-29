# tools/notes_gen.py — script.json → printable Marathi PDF notes (Devanagari TTF embedded)
import json, os, sys
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, "assets", "fonts", "NotoSansDevanagari-Bold.ttf")
NAVY, GOLD, MUTE = HexColor("#0a122c"), HexColor("#b8860b"), HexColor("#44506b")

def main(script_path, out_pdf):
    sc = json.load(open(script_path))
    pdfmetrics.registerFont(TTFont("NDB", FONT))
    c = canvas.Canvas(out_pdf, pagesize=A4)
    W, H = A4
    def head(t, y):
        c.setFillColor(NAVY); c.rect(0, y - 6*mm, W, 12*mm, stroke=0, fill=1)
        c.setFillColor(HexColor("#ffffff")); c.setFont("NDB", 13); c.drawString(16*mm, y - 2*mm, t)
        return y - 14*mm
    y = head("Mmindpower नोट्स — " + sc["title"], H - 18*mm)
    c.setFillColor(MUTE); c.setFont("NDB", 9)
    c.drawString(16*mm, y, "उगम: Wikipedia + AI-संस्क्लेषण · टेलिग्राम @mmindpower_1"); y -= 10*mm
    c.setFillColor(NAVY); c.setFont("NDB", 11)
    def para(txt, size=11, lead=6.4*mm, indent=0, color=NAVY):
        nonlocal y
        c.setFillColor(color); c.setFont("NDB", size)
        words, line = txt.split(), ""
        for w in words:
            t = (line + " " + w).strip()
            if c.stringWidth(t, "NDB", size) > W - (32*mm + indent):
                c.drawString(16*mm + indent, y, line); y -= lead; line = w
                if y < 20*mm:
                    c.showPage(); y = head("Mmindpower नोट्स — " + sc["title"], H - 18*mm)
                    c.setFillColor(color); c.setFont("NDB", size)
            else:
                line = t
        if line:
            c.drawString(16*mm + indent, y, line); y -= lead
        y -= 2*mm
    if sc.get("hook"): para("✦ " + sc["hook"], size=10, color=MUTE)
    for i, ch in enumerate(sc["chapters"], 1):
        if y < 40*mm: c.showPage(); y = head("Mmindpower नोट्स — " + sc["title"], H - 18*mm)
        c.setFillColor(GOLD); c.setFont("NDB", 12)
        c.drawString(16*mm, y, f"{i}. {ch['heading']}"); y -= 8*mm
        para(ch.get("narration", ""))
        for b in ch.get("bullets", [])[:4]:
            para("• " + b, size=10, indent=4*mm)
    if sc.get("recap"): para("सारांश: " + sc["recap"], size=10, color=MUTE)
    c.setFillColor(HexColor("#ffffff")); c.setFillColor(MUTE); c.setFont("NDB", 8)
    c.drawString(16*mm, 12*mm, "Mmindpower — मराठी परीक्षा-तयारी · नोट्स PDF (स्वयंचलित)")
    c.save()
    print("notes →", out_pdf)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
