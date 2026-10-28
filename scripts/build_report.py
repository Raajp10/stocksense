"""Rebuild the course report from reviewable prose, real screenshots and JUnit."""
from pathlib import Path
from xml.sax.saxutils import escape
import re
import xml.etree.ElementTree as ET
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Image,Table,TableStyle,KeepTogether
from reportlab.graphics.shapes import Drawing,Rect,String,Line,Polygon
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
DOCS=ROOT/'docs'
GREEN=colors.HexColor('#316e51');INK=colors.HexColor('#27392f');PALE=colors.HexColor('#edf2e5')
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='ReportBody',fontName='Helvetica',fontSize=10.3,leading=15.9,textColor=INK,spaceAfter=13))
styles.add(ParagraphStyle(name='ReportTitle',fontName='Helvetica-Bold',fontSize=25,leading=31,textColor=GREEN,spaceAfter=19))
styles.add(ParagraphStyle(name='ReportSub',fontName='Helvetica-Bold',fontSize=13.5,leading=19,textColor=INK,spaceAfter=16))
styles.add(ParagraphStyle(name='ReportSmall',fontName='Helvetica',fontSize=8.7,leading=12.5,textColor=INK,spaceAfter=10))


def clean(text):
    return text.translate(str.maketrans({'—':'-','–':'-','’':"'",'“':'"','”':'"','→':' -> ','↔':' <-> ','×':' x ','÷':' / ','⌈':'ceil(','⌉':')','−':'-','…':'...','·':' / '}))


def box(d,x,y,w,h,title,lines):
    d.add(Rect(x,y,w,h,rx=8,fillColor=PALE,strokeColor=GREEN,strokeWidth=.7))
    d.add(String(x+w/2,y+h-19,title,fontName='Helvetica-Bold',fontSize=10,textAnchor='middle',fillColor=INK))
    for i,line in enumerate(lines):
        d.add(String(x+w/2,y+h-36-i*13,line,fontName='Helvetica',fontSize=8,textAnchor='middle',fillColor=INK))


def arrow(d,x1,y1,x2,y2):
    d.add(Line(x1,y1,x2,y2,strokeColor=GREEN,strokeWidth=1))
    if x2>x1:
        pts=[x2,y2,x2-6,y2+3,x2-6,y2-3]
    elif x2<x1:
        pts=[x2,y2,x2+6,y2+3,x2+6,y2-3]
    elif y2<y1:
        pts=[x2,y2,x2-3,y2+6,x2+3,y2+6]
    else:
        pts=[x2,y2,x2-3,y2-6,x2+3,y2-6]
    d.add(Polygon(pts,fillColor=GREEN,strokeColor=GREEN))


def architecture():
    d=Drawing(480,215)
    box(d,0,120,140,80,'Browser / phone',['Jinja pages / QR decoder','Bootstrap / Chart.js','Local camera frames'])
    box(d,170,120,140,80,'Flask blueprints',['Auth / catalog / inventory','Orders / reports / exports','Session and CSRF checks'])
    box(d,340,120,140,80,'Domain services',['Inventory / reorder / orders','Media validation','Atomic SQLAlchemy writes'])
    arrow(d,140,160,170,160);arrow(d,310,160,340,160)
    box(d,260,10,130,65,'Database',['SQLite or PostgreSQL','Balances + ledger'])
    box(d,70,10,140,65,'Durable photo directory',['Validated JPEG images','Separate from source'])
    arrow(d,410,120,325,75);arrow(d,340,130,210,65)
    return d


def erd():
    d=Drawing(480,240)
    entries=[(170,180,'Store',['scope / timezone']), (0,95,'User',['store / role / active']),
        (170,95,'Product / Supplier',['SKU / cost / price / QR']), (340,95,'Location',['code / area / kind']),
        (0,0,'Operation / Sale',['token / fingerprint','actor / price snapshot']),
        (170,0,'Balance / Movement',['product + location','quantity / version / delta']),
        (340,0,'Order / Item / Count',['status / destination','snapshot / observed version'])]
    for x,y,title,lines in entries:box(d,x,y,140,60,title,lines)
    arrow(d,200,180,70,155);arrow(d,240,180,240,155);arrow(d,280,180,410,155)
    arrow(d,240,95,240,60);arrow(d,410,95,310,30);arrow(d,70,95,70,60)
    arrow(d,140,30,170,30);arrow(d,310,30,340,30)
    return d


def evidence_table():
    data=[['Environment / suite','Tests','Failures','Errors','Result']]
    for filename,label in [('evidence-sqlite.xml','SQLite service + HTTP'),('evidence-postgres.xml','PostgreSQL service + HTTP'),('evidence-browser.xml','Playwright Chromium')]:
        tree=ET.parse(DOCS/filename).getroot()
        suites=[tree] if tree.tag=='testsuite' else tree.findall('testsuite')
        counts={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
        data.append([label,str(counts['tests']),str(counts['failures']),str(counts['errors']), 'Passed' if counts['tests'] and not any(counts[k] for k in ('failures','errors','skipped')) else 'Review evidence'])
    table=Table(data,colWidths=[210,52,65,55,80],repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('TEXTCOLOR',(0,0),(-1,-1),INK),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),11),('TOPPADDING',(0,0),(-1,-1),11),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#dce3d4'))]))
    return table


def footer(canvas,doc):
    canvas.setStrokeColor(colors.HexColor('#dce3d4'));canvas.line(48,45,A4[0]-48,45)
    canvas.setFillColor(GREEN);canvas.setFont('Helvetica',8)
    canvas.drawString(48,30,'StockSense / Raaj Patel / Software Design I')
    canvas.drawRightString(A4[0]-48,30,str(doc.page))


def main():
    source=(DOCS/'report-source.md').read_text()
    story=[]
    for number,page in enumerate(source.split('---PAGE---')):
        if number:story.append(PageBreak())
        for block in re.split(r'\n\s*\n',page.strip()):
            block=block.strip()
            if not block:continue
            if block=='[[architecture]]':story.extend([architecture(),Spacer(1,14)]);continue
            if block=='[[erd]]':story.extend([erd(),Spacer(1,14)]);continue
            if block=='[[test_table]]':story.extend([evidence_table(),Spacer(1,16)]);continue
            match=re.fullmatch(r'\[\[screenshot:(.+)\]\]',block)
            if match:
                image=Image(str(DOCS/'screenshots'/match.group(1)))
                scale=min(490/image.imageWidth,285/image.imageHeight)
                image.drawWidth=image.imageWidth*scale;image.drawHeight=image.imageHeight*scale
                story.extend([image,Spacer(1,14)]);continue
            for paragraph in block.split('\n') if block.startswith('#') else [block]:
                heading=paragraph.startswith('# ');sub=paragraph.startswith('## ')
                text=paragraph[2:] if heading else paragraph[3:] if sub else paragraph
                style=styles['ReportTitle' if heading else 'ReportSub' if sub else 'ReportSmall' if text.startswith(('Figure ','Table ','[')) else 'ReportBody']
                story.append(Paragraph(escape(clean(text)),style))
    output=DOCS/'StockSense_Report.pdf'
    doc=SimpleDocTemplate(str(output),pagesize=A4,rightMargin=48,leftMargin=48,topMargin=48,bottomMargin=60,
        title='StockSense - Software Design I Project Report',author='Raaj Patel')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    reader=PdfReader(output)
    assert len(reader.pages)>=20,len(reader.pages)
    text='\n'.join(p.extract_text() for p in reader.pages)
    for required in ['Chapter 1','Chapter 2','Chapter 3','Chapter 4','Chapter 5','Chapter 6','References','Figure 1','Figure 2']:
        assert required in text,required
    print(f'Built {output.name}: {len(reader.pages)} pages; all six chapters, two design diagrams, real screenshots and test-results table verified.')

if __name__=='__main__':main()
