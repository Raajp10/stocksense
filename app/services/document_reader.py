"""Local document text/OCR extraction and conservative, editable line suggestions."""
import csv
from decimal import Decimal, InvalidOperation
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser
from io import BytesIO, StringIO
import re
import threading
from pathlib import Path
import warnings
from PIL import Image, ImageOps
from pypdf import PdfReader
from .common import DomainError

PDF_LOCK = threading.Lock()  # PDFium is not thread-safe within one process.
MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 100_000
MONEY = r'\$?\s*\d[\d,]*\.\d{2}'


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.hidden=0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'): self.hidden+=1
        if tag in ('br','p','div','tr','table'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script','style'): self.hidden=max(0,self.hidden-1)
        if tag in ('td','th'): self.parts.append('\t')
        if tag in ('p','div','tr'): self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def ocr_image(image):
    from .local_ocr import read_image
    return read_image(image)


def extract_document(data, filename):
    if not data or len(data)>MAX_BYTES:
        raise DomainError('Choose a document no larger than 10 MB.')
    extension=Path(filename).suffix.lower()
    if data.startswith(b'%PDF'):
        try:
            reader=PdfReader(BytesIO(data))
            if reader.is_encrypted or not 1<=len(reader.pages)<=5:
                raise DomainError('Choose an unencrypted PDF with 1–5 pages.')
            parts=[]
            for i,page in enumerate(reader.pages):
                content=page.get_contents()
                if content and len(content.get_data())>8*1024*1024:
                    raise DomainError('PDF page is too complex. Upload a simpler document.')
                text=page.extract_text(extraction_mode='layout') or ''
                if len(text.strip())<25:
                    import pypdfium2 as pdfium
                    with PDF_LOCK:
                        pdf=pdfium.PdfDocument(data)
                        try:
                            rendered=pdf[i]
                            width,height=rendered.get_size()
                            scale=min(2,2400/max(width,1),3200/max(height,1))
                            bitmap=rendered.render(scale=scale)
                            try: text=ocr_image(bitmap.to_pil())
                            finally: bitmap.close();rendered.close()
                        finally: pdf.close()
                if not hasattr(text,'extraction'):
                    from .local_ocr import normalize_pdf_layout
                    text=normalize_pdf_layout(text)
                parts.append(text)
            from .local_ocr import DocumentText
            return DocumentText('\n'.join(parts)[:MAX_TEXT],{'engine':'PDF pages','pages':[getattr(part,'extraction',{}) for part in parts]})
        except DomainError: raise
        except Exception as exc:
            raise DomainError('This PDF could not be read. Try a photo or paste the text.') from exc
    if extension in ('.eml',):
        try:
            message=BytesParser(policy=policy.default).parsebytes(data)
            body=message.get_body(preferencelist=('plain','html')) if message.is_multipart() else message
            content=body.get_content() if body else ''
            if body and body.get_content_type()=='text/html':
                parser=PlainHTML();parser.feed(str(content));content=''.join(parser.parts)
            name,address=parseaddr(str(message.get('From','')))
            return f'Supplier: {name or address}\nEmail: {address}\nSubject: {message.get("Subject", "")}\n{content}'[:MAX_TEXT]
        except Exception as exc:
            raise DomainError('Email file could not be read. Paste the message text instead.') from exc
    if extension in ('.txt','.csv','.html','.htm'):
        text=data.decode('utf-8-sig',errors='replace')
        if extension in ('.html','.htm'):
            parser=PlainHTML();parser.feed(text);text=''.join(parser.parts)
        return text[:MAX_TEXT]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in ('JPEG','PNG','WEBP'):
                    raise DomainError('Use a JPEG/PNG/WebP photo, PDF, CSV, text or .eml email.')
                return ocr_image(image)
    except DomainError: raise
    except (OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
        raise DomainError('Choose a valid receipt photo, PDF, CSV, text or .eml email.') from exc


def amount(value):
    try:
        number=Decimal(re.sub(r'[$,\s]','',str(value)))
        if number.is_finite() and 0<=number<=Decimal('10000000'):
            return format(number.quantize(Decimal('.01')),'f')
    except (InvalidOperation,ValueError): pass
    return ''


def suggested_category(name):
    name=name.lower()
    for category,words in [('Dairy alternatives',('milk','cream','cheese','yogurt')),
        ('Supplies',('cup','lid','napkin','bag','straw','packaging')),
        ('Bakery',('bread','croissant','muffin','bagel','cake')),
        ('Beverages',('water','juice','soda','tea','coffee','syrup'))]:
        if any(word in name for word in words): return category
    return 'General'


def line_item(name,qty='',cost='',sku='',warning=''):
    name=re.sub(r'\s+',' ',name).strip(' |\t-')[:120]
    return dict(name=name,quantity=str(qty).strip(),cost=amount(cost),sku=sku[:60],
        category=suggested_category(name),unit='unit',price='',product_id='',location_id='',warning=warning)


def parse_text(text):
    extraction=getattr(text,'extraction',{})
    text=text.replace('\r','')[:MAX_TEXT]
    lines=[line.strip() for line in text.split('\n') if line.strip()]
    metadata={key:'' for key in ('supplier_name','email','phone','address','reference','document_date','subtotal','tax','shipping','discount','total','notes','non_stock','non_stock_reason')}
    metadata['currency']='USD'
    for key,pattern in {
        'supplier_name':r'^(?:supplier|vendor|sold by|from)[ \t]*:[ \t]*([^\n]+)',
        'reference':r'(?:invoice|receipt|purchase order|order)\s*(?:number|no\.?|#|ref(?:erence)?)?[ \t]*[:#-][ \t]*([\w./-]+)',
        'phone':r'(?:phone|tel(?:ephone)?)\s*[:.]?\s*([+()\d][+()\d .-]{6,40})',
        'address':r'^address\s*:\s*([^\n]+)',
        'document_date':r'(?:invoice date|order date|date)\s*:\s*([^\n]+)',
    }.items():
        match=re.search(pattern,text,re.I|re.M)
        if match: metadata[key]=match.group(1).strip()[:500]
    match=re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',text)
    if match: metadata['email']=match.group(0)[:150]
    if not metadata['phone']:
        match=re.search(r'(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}',text)
        if match: metadata['phone']=match.group(0)
    if not metadata['address']:
        match=re.search(r'^\d+\s+[\w .,-]+(?:street|st\.?|road|rd\.?|avenue|ave\.?|drive|dr\.?|blvd|lane|ln\.?)\b[^\n]*',text,re.I|re.M)
        if match: metadata['address']=match.group(0)[:500]
    for key,labels in [('subtotal','subtotal|sub total'),('tax','tax|sales tax|vat'),('shipping','shipping|delivery|delivery fee'),('discount','discount'),('total','grand total|amount due|total due|total')]:
        matches=re.findall(r'^\s*(?:'+labels+r')\s*[:$ ]+('+MONEY+r')\s*$',text,re.I|re.M)
        if matches: metadata[key]=amount(matches[-1])
    match=re.search(r'\b(USD|CAD|EUR|GBP|INR)\b',text)
    if match: metadata['currency']=match.group(1)
    if not metadata['supplier_name']:
        for line in lines[:8]:
            if not re.search(r'@|invoice|receipt|order|date|qty|quantity|description|^\d|^subject:|^email:',line,re.I) and len(line)<100:
                metadata['supplier_name']=line;break
    items=[];unparsed=[];header=None;delimiter=None
    aliases={'qty':'quantity','quantity':'quantity','units':'quantity','item':'name','description':'name','product':'name','name':'name','sku':'sku','itemcode':'sku','code':'sku','unitprice':'cost','unitcost':'cost','price':'cost','cost':'cost','amount':'total','linetotal':'total','total':'total','category':'category','unit':'unit'}
    for raw in lines:
        separated=bool(re.search(r'[,|\t;]',raw))
        if separated:
            candidate=max((',','|','\t',';'),key=raw.count)
            cells=next(csv.reader([raw],delimiter=candidate))
        else:
            cells=re.split(r'\s{2,}',raw)
            candidate='spaces'
        keys=[aliases.get(re.sub(r'[^a-z]','',cell.lower()),'') for cell in cells]
        if 'name' in keys and 'quantity' in keys:
            header=keys;delimiter=candidate;continue
        if header:
            cells=re.split(r'\s{2,}',raw) if delimiter=='spaces' else next(csv.reader([raw],delimiter=delimiter))
            values={k:v.strip() for k,v in zip(header,cells) if k}
            if values.get('name') and re.fullmatch(r'\d+',values.get('quantity','')):
                cost=amount(values.get('cost',''))
                if not cost and values.get('total') and int(values['quantity']):
                    total=amount(values['total'])
                    if total: cost=amount(Decimal(total)/int(values['quantity']))
                if re.fullmatch(r'(?:subtotal|total|tax|shipping|delivery|discount|delivery fee)',values['name'].strip().rstrip(':'),re.I): continue
                item=line_item(values['name'],values['quantity'],cost,values.get('sku',''))
                item['source_total']=amount(values.get('total',''))
                for k in ('category','unit'):
                    if values.get(k): item[k]=values[k][:60 if k=='category' else 30]
                items.append(item);continue
        if re.match(r'^(?:sub\s*total|total|tax|vat|shipping|discount|balance|amount due|payment|cash|change|delivery|phone|tel|email|address|date|invoice|receipt|order|supplier|vendor|subject|thank|www\.)\b',raw,re.I) or re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',raw):
            continue
        match=re.match(r'^\s*(\d+)\s*[x×]\s+(.+?)\s*(?:@|at)\s*('+MONEY+r')',raw,re.I)
        if match:
            items.append(line_item(match.group(2),match.group(1),match.group(3)));continue
        match=re.match(r'^(\d+)\s*[x×@]\s*('+MONEY+r')\s*$',raw)
        if match and unparsed:
            previous=unparsed[-1]
            if re.search(r'[A-Za-z]',previous) and not re.match(r'^\d',previous):
                unparsed.pop();items.append(line_item(previous,match.group(1),match.group(2)));continue
        match=re.match(r'^(\d+)\s+(.+?)\s+('+MONEY+r')(?:\s+('+MONEY+r'))?\s*$',raw)
        if match:
            items.append(line_item(match.group(2),match.group(1),match.group(3)));continue
        match=re.match(r'^(.+?)\s+(\d+)\s*(?:[x×@]\s*)?('+MONEY+r')(?:\s+('+MONEY+r'))?\s*$',raw)
        if match:
            name=match.group(1);sku=''
            first=name.split()[0]
            if re.fullmatch(r'[A-Z0-9]+[-_.][A-Z0-9_.-]+',first):
                sku=first;name=name[len(first):].strip()
            items.append(line_item(name,match.group(2),match.group(3),sku));continue
        match=re.match(r'^(.+?)\s+('+MONEY+r')\s*$',raw)
        if match and not re.match(r'^\d|^\$',match.group(1)):
            items.append(line_item(match.group(1),'',match.group(2),warning='Quantity was not detected. Check the original document.'));continue
        match=re.match(r'^([A-Za-z][A-Za-z0-9 ()./-]+?)\s+(\d{1,6})$',raw)
        if match:
            items.append(line_item(match.group(1),match.group(2),'',warning='Unit cost was not detected. Check the supplier document.'));continue
        if raw!=metadata['supplier_name']: unparsed.append(raw)
    if len(items)>100:
        raise DomainError('More than 100 product rows were detected. Split this document into smaller lists so no items are omitted.')
    unique=[]
    for item in items:
        if item['name']: unique.append(item)
    from .document_checks import inspect_document
    return {'validation':inspect_document(metadata,unique),'metadata':metadata,'lines':unique,'unparsed':unparsed[:100],
        'extraction':extraction,
        'warnings':['Recognition is a suggestion. Check every quantity, unit, cost and product match against the original.','Tax, shipping and discount are retained as document details; they are not inventory units.']}
