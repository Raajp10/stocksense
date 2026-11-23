"""Store-scoped read tools and verified answers for the owner assistant."""
from datetime import datetime,timedelta,date
import re
from zoneinfo import ZoneInfo
from sqlalchemy import select,func
from ..extensions import db
from ..models import Store,Product,StockBalance,Location,Sale
from .common import DomainError
from .reorder import recommendations,utc_bounds
from .inventory import quantity
from .ask_provider import model_plan,ProviderError,TOOLS,PERIODS

EXAMPLES=('What should I reorder?', 'What will run out in the next 7 days?',
          'What were my top 5 sellers last month?', 'Where is Oat milk stored?',
          'How much stock value do I have?', 'Show low stock')
WRITE=re.compile(r'\b(delete|remove|update|change|set|insert|drop|truncate|approve|cancel|receive|sell|transfer|adjust|create|place an order|send|email|passwords?|secrets?|api.keys?|sql|another store|other store|all stores)\b',re.I)


def validate_plan(plan):
    if not isinstance(plan,dict) or set(plan)-{'tool','product','period','start','end','limit','horizon'}: raise ProviderError('Invalid query fields.')
    result={'tool':'help','product':'','period':'last_30_days','start':'','end':'','limit':5,'horizon':7,**plan}
    if result['tool'] not in TOOLS or result['period'] not in PERIODS: raise ProviderError('Unknown query.')
    for name in ['product','start','end']:
        if not isinstance(result[name],str) or len(result[name])>(120 if name=='product' else 10): raise ProviderError('Invalid query text.')
    for name,maximum in [('limit',20),('horizon',90)]:
        if type(result[name]) is not int or not 1<=result[name]<=maximum: raise ProviderError('Invalid query limit.')
    return result


def local_plan(question,context=None):
    """Transparent offline fallback for common questions; this is not an LLM."""
    q=question.casefold();plan={'tool':'help','product':'','period':'last_30_days','limit':5,'horizon':7}
    if WRITE.search(q): return validate_plan(plan)
    if re.search(r'\b(reorder|order|purchase|restock|buy|buying|formula|recommend)\b',q): plan['tool']='reorder'
    elif re.search(r'run.?out|stockout|out of stock|this week|next week',q): plan['tool']='runout'
    elif re.search(r'low.stock|below|threshold|running low',q): plan['tool']='low_stock'
    elif re.search(r'where|location|stored|shelf|backroom',q): plan['tool']='locations'
    elif re.search(r'top|best|fastest|most popular|most sold',q): plan['tool']='top_sellers'
    elif re.search(r'slow|least|worst',q): plan['tool']='slow_sellers'
    elif re.search(r'revenue|sales|sold|stock value|inventory value|worth',q): plan['tool']='sales'
    elif re.search(r'stock|inventory|how many|on hand',q): plan['tool']='stock'
    elif context and re.search(r'last month|this month|yesterday|today|last \d+ days|why|and |what about|how about',q):
        plan.update({k:v for k,v in context.items() if k in plan or k in ('start','end')})
    if 'last month' in q: plan['period']='last_month'
    elif 'this month' in q: plan['period']='this_month'
    elif 'yesterday' in q: plan['period']='yesterday'
    elif 'today' in q: plan['period']='today'
    elif re.search(r'last (?:7|seven) days|this week',q): plan['period']='last_7_days'
    dates=re.findall(r'\b\d{4}-\d{2}-\d{2}\b',q)
    if len(dates)==2: plan.update(period='custom',start=dates[0],end=dates[1])
    limit=re.search(r'(?:top|bottom|first)\s+(\d+)\b',q)
    if limit: plan['limit']=max(1,min(20,int(limit.group(1))))
    horizon=re.search(r'(?:next|within|in)\s+(\d+)\s+days?',q)
    if horizon: plan['horizon']=max(1,min(90,int(horizon.group(1))))
    # Preserve an explicit product phrase without giving a language model catalog data.
    phrase=re.search(r'(?:where (?:is|are)|stock (?:of|for)|reorder (?:for)|why (?:should i )?reorder)\s+(.+?)(?:\s+(?:stored|located)\??$|[?]|$)',question,re.I)
    if phrase: plan['product']=phrase.group(1).strip()
    return validate_plan(plan)


def date_range(plan,today):
    period=plan['period']
    if period=='today': return today,today
    if period=='yesterday': return today-timedelta(days=1),today-timedelta(days=1)
    if period=='last_7_days': return today-timedelta(days=6),today
    if period=='last_30_days': return today-timedelta(days=29),today
    if period=='this_month': return today.replace(day=1),today
    if period=='last_month':
        end=today.replace(day=1)-timedelta(days=1)
        return end.replace(day=1),end
    try: start,end=date.fromisoformat(plan['start']),date.fromisoformat(plan['end'])
    except (ValueError,TypeError) as exc: raise DomainError('Use two valid dates, for example 2026-10-01 to 2026-10-31.') from exc
    if end==date.max or end<start or (end-start).days>366: raise DomainError('Ask for a date range of at most 367 days, with the start date first.')
    return start,end


def money(cents): return f'${cents/100:,.2f}'


def answer(actor,question,context=None):
    if not actor.active or actor.role!='owner': raise DomainError('Ask StockSense is available to store owners.')
    if not isinstance(question,str) or not 1<=len(question.strip())<=500: raise DomainError('Ask a question using 1–500 characters.')
    question=question.strip()
    followup=bool(re.search(r'^(?:and\b|what about\b|how about\b|why\b|what if\b)|\b(it|that|those|them|same)\b',question,re.I))
    context=context if followup else None
    store=db.session.get(Store,actor.store_id)
    today=datetime.now(ZoneInfo(store.timezone)).date()
    fallback='';engine='Built-in interpreter'
    if WRITE.search(question):
        plan=validate_plan({'tool':'help'})
    else:
        try:
            from flask import current_app
            if current_app.config['ASK_PROVIDER']=='builtin': raise ProviderError('Built-in mode')
            raw,engine=model_plan(question,context,today)
            plan=validate_plan(raw)
            defaults=local_plan(question,context)
            if not re.search(r'\b(?:top|bottom|first|show)\s+\d+',question,re.I): plan['limit']=5
            if not re.search(r'\b(?:next|within|in)\s+\d+\s+days?',question,re.I): plan['horizon']=7
            if defaults['period']!='last_30_days':
                plan.update({k:defaults[k] for k in ('period','start','end')})
            elif plan['tool'] in ('sales','top_sellers','slow_sellers') and not re.search(r'today|yesterday|month|week|day|year|since|between|from|\d{4}-',question,re.I):
                plan.update(period='last_30_days',start='',end='')
        except ProviderError:
            from flask import current_app
            plan=local_plan(question,context);engine='Built-in interpreter'
            if current_app.config['ASK_PROVIDER']!='builtin': fallback='The AI model could not answer this time. Using the built-in interpreter for this question.'
    # A model cannot silently narrow a new question to an unstated product.
    if plan['product'] and plan['product'].casefold() not in question.casefold() and not (context and plan['product']==context.get('product')):
        plan['product']=''
    # Match only products from this account, even when the model guesses a name/ID.
    products=db.session.scalars(select(Product).where(Product.store_id==actor.store_id,Product.archived.is_(False)).order_by(Product.name)).all()
    mentioned=[p for p in products if re.search(r'(?<!\w)'+re.escape(p.sku)+r'(?!\w)',question,re.I) or p.name.casefold() in question.casefold()]
    if mentioned: plan['product']=mentioned[0].sku if len(mentioned)==1 else ''
    query=plan['product'].strip().casefold()
    selected=mentioned if len(mentioned)>1 else [p for p in products if not query or query in p.name.casefold() or query==p.sku.casefold()]
    ids={p.id for p in selected}
    result=dict(title='',summary='',headers=[],rows=[],notes=[],engine=engine,fallback=fallback,
                checked=datetime.now(ZoneInfo(store.timezone)).strftime('%Y-%m-%d %H:%M'),timezone=store.timezone,
                context=plan,links=[],total=0)
    tool=plan['tool']
    if tool=='help':
        result.update(title='Ask about your store',summary='I can look up stock, product locations, low-stock items, reorder quantities, sales and best or slowest sellers. I cannot change stock, place orders or access another store.',notes=['Try one question at a time. For dates, use “last month”, “today”, or two YYYY-MM-DD dates.'])
        return result
    if query and not selected:
        result.update(title='Product not found',summary=f'No active product matches “{plan["product"]}” in your store. Try its full name or SKU.')
        return result
    if tool in ('low_stock','runout','reorder'):
        recs=[r for r in recommendations(actor.store_id,today) if r['product'].id in ids]
        if tool=='low_stock': recs=[r for r in recs if r['low']]
        if tool=='runout': recs=[r for r in recs if r['stock']==0 or (r['days_remaining'] is not None and r['days_remaining']<=plan['horizon'])]
        if tool=='reorder' and not query: recs=[r for r in recs if r['suggested']>0]
        recs.sort(key=lambda r:(r['days_remaining'] if r['days_remaining'] is not None else float('inf'),r['product'].name))
        titles={'low_stock':'Items at or below reorder level','runout':f'Possible stockouts within {plan["horizon"]} days','reorder':'Your reorder recommendations'}
        result.update(title=titles[tool],summary=f'{len(recs)} matching products based on current stock and recorded sales.',headers=['Product','On hand','Avg / day','Days left','Approved incoming','Suggested order','Supplier'],total=len(recs))
        for r in recs[:plan['limit']]:
            result['rows'].append([r['product'].name,str(r['stock'])+' '+r['product'].unit,f'{r["average"]:.2f}',f'{r["days_remaining"]:.1f}' if r['days_remaining'] is not None else 'No sales estimate',str(r['incoming']),str(r['suggested']),r['supplier'].name])
            if query:
                result['notes'].append(f'{r["product"].name}: {r["sold"]} units / {r["days"]} completed days; coverage {r["coverage"]} days. Target = max(threshold {r["threshold"]}, rounded-up sales forecast {r["forecast"]}) = {r["target"]}. Order = max(0, {r["target"]} − {r["stock"]} on hand − {r["incoming"]} approved incoming) = {r["suggested"]}.')
        result['notes'].append('Sales average uses up to 14 completed store-calendar days, excluding today. No recent sales means no depletion estimate; stockouts are estimates, not guarantees. Approved incoming stock reduces suggested orders but has no arrival-date forecast.')
        result['links']=[('Review reorder list','/reorder')]
    elif tool=='stock':
        result.update(title='Stock on hand',summary=f'{len(selected)} matching products in your store.',headers=['Product','SKU','Category','On hand','Reorder level'],total=len(selected))
        result['rows']=[[p.name,p.sku,p.category,str(quantity(actor.store_id,p.id))+' '+p.unit,str(p.reorder_level)] for p in selected[:plan['limit']]]
        result['links']=[('Open products','/products')]
    elif tool=='locations':
        rows=db.session.execute(select(Product.name,Location.code,Location.name,StockBalance.quantity,Product.unit).join(StockBalance,(StockBalance.product_id==Product.id)&(StockBalance.store_id==Product.store_id)).join(Location,(Location.id==StockBalance.location_id)&(Location.store_id==StockBalance.store_id)).where(Product.store_id==actor.store_id,Product.id.in_(ids),StockBalance.quantity>0).order_by(Product.name,Location.code)).all()
        result.update(title='Where your stock is stored',summary=f'{len(rows)} product/location balances with stock available.',headers=['Product','Location','Description','Quantity','Unit'],rows=[list(r) for r in rows[:plan['limit']]],total=len(rows),links=[('Open stock locations','/locations')])
    else:
        start,end=date_range(plan,today);lo,hi=utc_bounds(start,end+timedelta(days=1),store.timezone)
        sold=db.session.execute(select(Sale.product_id,func.sum(Sale.quantity),func.sum(Sale.quantity*Sale.price_cents)).where(Sale.store_id==actor.store_id,Sale.effective_at>=lo,Sale.effective_at<hi).group_by(Sale.product_id)).all()
        totals={pid:(int(units),int(revenue)) for pid,units,revenue in sold}
        # Include archived products with historical sales; they still count toward recorded revenue.
        historical=db.session.scalars(select(Product).where(Product.store_id==actor.store_id)).all()
        ranked=[(p,*totals.get(p.id,(0,0))) for p in historical if (not query or query in p.name.casefold() or query==p.sku.casefold()) and (len(mentioned)<=1 or p.id in ids) and (not p.archived or p.id in totals)]
        ranked.sort(key=lambda row:((-row[1] if tool!='slow_sellers' else row[1]),row[0].name))
        label=f'{start.isoformat()} through {end.isoformat()} ({store.timezone})'
        if tool=='sales':
            units=sum(r[1] for r in ranked);revenue=sum(r[2] for r in ranked)
            value=sum(quantity(actor.store_id,p.id)*p.cost_cents for p in historical if not query or query in p.name.casefold() or query==p.sku.casefold())
            result.update(title='Sales and stock value',summary=f'{units} units sold; recorded revenue {money(revenue)}. Current stock value at catalog cost: {money(value)}.',headers=['Measure','Value'],rows=[['Units sold',str(units)],['Recorded revenue',money(revenue)],['Current stock value at cost',money(value)]],total=3)
            result['notes'].append('Revenue uses saved sale prices. Stock value uses current catalog costs. These figures are not profit; unrecorded sales are not included.')
        else:
            if tool=='top_sellers': ranked=[r for r in ranked if r[1]>0]
            result.update(title='Top sellers' if tool=='top_sellers' else 'Slowest sellers',summary=f'{len(ranked)} matching products. Ranked by recorded units sold.',headers=['Product','SKU','Units sold','Recorded revenue'],rows=[[p.name,p.sku,str(units),money(revenue)] for p,units,revenue in ranked[:plan['limit']]],total=len(ranked))
        result['notes'].insert(0,label)
        result['links']=[('Open dashboard','/?start='+start.isoformat()+'&end='+end.isoformat())]
    if result['total']>len(result['rows']): result['notes'].append(f'Showing {len(result["rows"])} of {result["total"]} matches. Ask for up to 20 or specify a product.')
    if not result['rows']: result['notes'].append('No matching records were found. This does not prove there were no unrecorded sales or deliveries.')
    return result
