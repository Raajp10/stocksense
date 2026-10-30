"""CPU-only PP-OCRv4 inference with spatial form/table reconstruction.

RapidOCR's bundled ONNX weights keep inference offline. Document bytes are never
sent to a model service. Geometry is retained until fields/columns are resolved.
"""
from dataclasses import dataclass
from functools import lru_cache
from statistics import median
import re
import math
import threading
import time
import numpy as np
from PIL import ImageOps
from .common import DomainError

OCR_LOCK = threading.Lock()
LABELS = {
    'supplier':'Supplier','vendor':'Supplier','sold by':'Supplier','from':'Supplier',
    'invoice':'Invoice','invoice no':'Invoice','invoice number':'Invoice','invoice #':'Invoice',
    'receipt':'Invoice','receipt no':'Invoice','order':'Invoice','order number':'Invoice',
    'purchase order':'Invoice','date':'Date','invoice date':'Date','order date':'Date',
    'email':'Email','phone':'Phone','tel':'Phone','address':'Address',
    'subtotal':'Subtotal','sub total':'Subtotal','tax':'Tax','sales tax':'Tax','vat':'Tax',
    'shipping':'Shipping','delivery':'Shipping','delivery fee':'Shipping','discount':'Discount',
    'total':'Total','grand total':'Total','amount due':'Total','total due':'Total',
    'bill to':'Bill to','ship to':'Ship to',
}
FINANCIAL = {'Subtotal','Tax','Shipping','Discount','Total'}
HEADERS = {'sku':'sku','itemcode':'sku','productcode':'sku','code':'sku',
    'description':'name','product':'name','productname':'name','item':'name','itemname':'name','name':'name',
    'qty':'quantity','quantity':'quantity','units':'quantity',
    'unitcost':'cost','unitprice':'cost','price':'cost','cost':'cost','rate':'cost',
    'linetotal':'total','amount':'total','total':'total','unit':'unit','category':'category'}


class DocumentText(str):
    def __new__(cls,text,extraction=None):
        obj=super().__new__(cls,text)
        obj.extraction=extraction or {}
        return obj


@dataclass(frozen=True)
class Cell:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    score: float = 1.0

    @property
    def cx(self): return (self.x0+self.x1)/2
    @property
    def cy(self): return (self.y0+self.y1)/2
    @property
    def height(self): return max(0.1,self.y1-self.y0)


def label(cell):
    text=cell.text.strip()
    if ':' in text:
        key,value=text.split(':',1)
        key=re.sub(r'\s+',' ',key.casefold()).strip().rstrip('.')
        if key in LABELS: return LABELS[key],value.strip()
    key=re.sub(r'\s+',' ',text.casefold()).strip().rstrip('.')
    if key in LABELS: return LABELS[key],''
    return None


def group_rows(cells):
    rows=[]
    for cell in sorted(cells,key=lambda c:(c.cy,c.x0)):
        candidates=[row for row in rows if abs(median(c.cy for c in row)-cell.cy)<=min(median(c.height for c in row),cell.height)*.55]
        if candidates:
            row=min(candidates,key=lambda row:abs(median(c.cy for c in row)-cell.cy))
            row.append(cell)
        else: rows.append([cell])
    return [sorted(row,key=lambda c:c.x0) for row in sorted(rows,key=lambda row:median(c.cy for c in row))]


def field_value(cell,cells,kind):
    inline=label(cell)[1]
    if inline: return inline
    # A value beside the label must be on its row and before the next label.
    right=sorted((c for c in cells if c.x0>=cell.x1 and abs(c.cy-cell.cy)<min(c.height,cell.height)*.55),key=lambda c:c.x0)
    found=[]
    for candidate in right:
        if label(candidate): break
        found.append(candidate.text)
    if found: return ' '.join(found)
    if kind in FINANCIAL: return ''
    # Otherwise look underneath in the same column, not in a neighbouring field.
    below=[c for c in cells if 0<c.cy-cell.cy<=cell.height*4.5 and
        abs(c.x0-cell.x0)<=max(cell.height*1.5,(cell.x1-cell.x0)*.65) and not label(c)]
    if below:
        candidate=min(below,key=lambda c:(c.cy-cell.cy,abs(c.x0-cell.x0)))
        return candidate.text
    return ''


def reconstruct(cells):
    if not cells: raise DomainError('No readable text was found. Try a sharper, straight-on image.')
    rows=group_rows(cells)
    fields={}
    for cell in cells:
        match=label(cell)
        if match and match[0] not in ('Bill to','Ship to'):
            value=field_value(cell,cells,match[0])
            if value: fields[match[0]]=value
    output=[f'{key}: {value}' for key,value in fields.items()]
    header_index=None;columns=[]
    for index,row in enumerate(rows):
        recognized=[]
        for cell in row:
            key=HEADERS.get(re.sub(r'[^a-z]','',cell.text.casefold()))
            if key: recognized.append((cell,key))
        keys={key for _,key in recognized}
        if 'name' in keys and 'quantity' in keys:
            header_index=index;columns=recognized;break
    if header_index is not None:
        # Labels define column positions; each data cell is assigned geometrically.
        output.append('\t'.join({'name':'Description','quantity':'Qty','cost':'Unit cost','total':'Line total'}.get(key,key.upper()) for _,key in columns))
        previous=None;previous_y=None
        for row in rows[header_index+1:]:
            if any(label(c) and label(c)[0] in FINANCIAL for c in row): break
            values={key:[] for _,key in columns}
            for cell in row:
                _,key=min(columns,key=lambda col:abs(col[0].cx-cell.cx))
                values[key].append(cell.text)
            merged={key:' '.join(parts) for key,parts in values.items()}
            has_numbers=bool(merged.get('quantity') or merged.get('cost') or merged.get('total'))
            if not has_numbers and merged.get('name') and previous is not None and median(c.cy for c in row)-previous_y<median(c.height for c in row)*1.8:
                previous['name']+=' '+merged['name']
                output[-1]='\t'.join(previous.get(key,'') for _,key in columns)
            elif has_numbers:
                output.append('\t'.join(merged.get(key,'') for _,key in columns))
                previous=merged;previous_y=median(c.cy for c in row)
    else:
        for row in rows:
            if any(label(c) for c in row): continue
            output.append('\t'.join(c.text for c in row))
    return '\n'.join(output),header_index is not None


def normalize_pdf_layout(text):
    """Use positional whitespace from a native PDF's layout-preserving extraction."""
    cells=[]
    for y,line in enumerate(text.splitlines()):
        for match in re.finditer(r'\S(?:.*?\S)?(?=\s{2,}|$)',line):
            cells.append(Cell(match.start(),y,match.end(),y+1,match.group()))
    if not cells: return text
    normalized,table=reconstruct(cells)
    return DocumentText(normalized,{'engine':'PDF text layout','table_detected':table})


@lru_cache(maxsize=1)
def engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)


def read_image(image):
    if image.width*image.height>16_000_000:
        raise DomainError('Document image exceeds 16 megapixels.')
    image=ImageOps.exif_transpose(image).convert('RGB')
    image.thumbnail((2200,2800))
    pixels=np.asarray(image)[:,:,::-1].copy()  # RapidOCR arrays use OpenCV BGR order.
    started=time.perf_counter()
    try:
        with OCR_LOCK:
            result,_=engine()(pixels)
    except Exception as exc:
        raise DomainError('Local ML text recognition could not finish. Try a clearer photo or an original PDF/CSV.') from exc
    cells=[]
    angles=[math.atan2(box[1][1]-box[0][1],box[1][0]-box[0][0]) for box,text,score in result or [] if len(text)>=3]
    angles=[angle for angle in angles if abs(angle)<math.radians(15)]
    angle=median(angles) if angles else 0
    for box,text,score in result or []:
        # Align coordinates, not pixels/text, so mildly tilted tables still form rows.
        points=[(math.cos(angle)*x+math.sin(angle)*y,-math.sin(angle)*x+math.cos(angle)*y) for x,y in box]
        xs=[p[0] for p in points];ys=[p[1] for p in points]
        cells.append(Cell(min(xs),min(ys),max(xs),max(ys),text,float(score)))
    text,table=reconstruct(cells)
    return DocumentText(text,{'engine':'RapidOCR PP-OCRv4 / ONNX CPU','table_detected':table,
        'seconds':round(time.perf_counter()-started,3),'regions':len(cells),
        'low_confidence_regions':sum(c.score<.85 for c in cells),
        'minimum_confidence':round(min(c.score for c in cells),3),'deskew_degrees':round(math.degrees(angle),2)})
