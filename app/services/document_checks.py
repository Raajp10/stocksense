"""Exact money checks shared by extraction review and stock finalization."""
from decimal import Decimal,InvalidOperation
import re


def cents(value):
    try:
        number=Decimal(str(value).replace('$','').replace(',','').strip())
        if not number.is_finite() or number<0 or number!=number.quantize(Decimal('.01')): return None
        return int(number*100)
    except (InvalidOperation,ValueError): return None


def inspect_document(metadata,lines):
    errors=[];warnings=[];items=0;complete=True
    for number,line in enumerate(lines,1):
        qty=str(line.get('quantity',''))
        cost=line.get('cost_cents') if 'cost_cents' in line else cents(line.get('cost',''))
        if not qty.isascii() or not qty.isdigit() or int(qty)<=0 or cost is None:
            complete=False;errors.append(f'Item {number} needs a positive whole quantity and a valid unit cost.');continue
        value=int(qty)*cost;items+=value
        source_total=cents(line.get('source_total',''))
        if source_total is not None and source_total!=value:
            errors.append(f'Item {number}: quantity × unit cost is ${value/100:.2f}, but the printed line total is ${source_total/100:.2f}.')
    if not lines: errors.append('No product rows were recognized. Review the image or upload an original PDF/CSV.')
    non_stock=cents(metadata.get('non_stock','')) or 0
    subtotal=cents(metadata.get('subtotal',''))
    total=cents(metadata.get('total',''))
    calculated_total=items+non_stock+(cents(metadata.get('tax','')) or 0)+(cents(metadata.get('shipping','')) or 0)-(cents(metadata.get('discount','')) or 0)
    if complete and subtotal is not None and items+non_stock!=subtotal:
        errors.append(f'Item subtotal ${items/100:.2f} + reviewed non-stock amount ${non_stock/100:.2f} does not match document subtotal ${subtotal/100:.2f}. Check for missing/misread items.')
    if complete and total is not None and calculated_total!=total:
        errors.append(f'Reviewed items, non-stock amount, tax, delivery and discount give ${calculated_total/100:.2f}, not document total ${total/100:.2f}.')
    if total is None: warnings.append('No document total was recognized. Compare every row with the source.')
    if non_stock and not str(metadata.get('non_stock_reason','')).strip():
        errors.append('Explain the non-stock/services amount before excluding it from inventory.')
    name=str(metadata.get('supplier_name','')).strip().rstrip(':').casefold()
    if name in ('invoice','receipt','date','total','delivery','bill to','shipping') or (name=='supplier' and str(metadata.get('supplier_name','')).strip().endswith(':')):
        errors.append('Supplier name is a document label. Correct it before continuing.')
    return {'errors':errors,'warnings':warnings,'items_cents':items,'non_stock_cents':non_stock,
        'document_subtotal_cents':subtotal,'document_total_cents':total,'calculated_total_cents':calculated_total,
        'balanced':complete and not errors and total is not None}
