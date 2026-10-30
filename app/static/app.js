'use strict';
document.addEventListener('DOMContentLoaded',()=>{
document.querySelectorAll('[data-print]').forEach(button=>button.addEventListener('click',()=>window.print()));
document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',event=>{
  if(event.defaultPrevented)return;
  if(form.dataset.busy==='true'){event.preventDefault();return;}
  form.dataset.busy='true';
  const button=event.submitter;
  // Keep the submitter enabled so its action/value is included in the POST.
  // aria-disabled + the form guard prevent repeats without dropping form fields.
  setTimeout(()=>{
    if(event.defaultPrevented){delete form.dataset.busy;return;}
    if(button){button.dataset.original=button.textContent;button.setAttribute('aria-disabled','true');button.classList.add('is-busy');button.textContent=form.dataset.busyLabel || (form.method==='get'?'Loading…':'Saving…');}
  },0);
}));
window.addEventListener('pageshow',()=>{
 document.querySelectorAll('form').forEach(f=>delete f.dataset.busy);
 document.querySelectorAll('button[data-original]').forEach(b=>{b.disabled=false;b.removeAttribute('aria-disabled');b.classList.remove('is-busy');b.textContent=b.dataset.original;});
});
const importLines=document.getElementById('import-lines');
if(importLines){
 let nextIndex=1000;
 const defaultLocation=document.getElementById('import-default-location');
 const supplierSelect=document.getElementById('import-supplier');
 supplierSelect?.addEventListener('change',()=>{
   const option=supplierSelect.selectedOptions[0];if(!supplierSelect.value)return;
   const name=document.querySelector('input[name=supplier_name]');name.value=option.dataset.name;
   ['email','phone','address'].forEach(key=>{const field=document.querySelector('input[name="'+key+'"]');if(!field.value)field.value=option.dataset[key]||'';});
 });
 const wireLine=line=>{
   const match=line.querySelector('[data-product-match]');
   const update=()=>{
     const isNew=!match.value;
     const details=line.querySelector('[data-new-product-details]');
     details.hidden=!isNew;if(isNew)details.open=true;
     line.querySelectorAll('[data-new-required]').forEach(input=>input.required=isNew);
   };
   match.addEventListener('change',update);update();
   line.querySelector('[data-remove-line]').addEventListener('click',()=>{
     line.remove();importLines.querySelectorAll('[data-line-number]').forEach((n,i)=>n.textContent=i+1);
   });
 };
 importLines.querySelectorAll('[data-import-line]').forEach(wireLine);
 document.getElementById('add-import-line').addEventListener('click',()=>{
   const html=document.getElementById('import-line-template').innerHTML.replaceAll('__index__',String(nextIndex++));
   importLines.insertAdjacentHTML('beforeend',html);
   const line=importLines.lastElementChild;wireLine(line);
   line.querySelector('input[name$="_sku"]').value='IMP-'+crypto.randomUUID().slice(0,8).toUpperCase();
   line.querySelector('[data-line-location]').value=defaultLocation.value;
   importLines.querySelectorAll('[data-line-number]').forEach((n,i)=>n.textContent=i+1);
   line.querySelector('input[name$="_name"]').focus();
 });
 document.getElementById('apply-import-location').addEventListener('click',()=>{
   if(!defaultLocation.value){defaultLocation.focus();defaultLocation.setCustomValidity('Choose a destination first.');defaultLocation.reportValidity();return;}
   defaultLocation.setCustomValidity('');
   importLines.querySelectorAll('[data-line-location]').forEach(select=>select.value=defaultLocation.value);
 });
 defaultLocation.addEventListener('change',()=>defaultLocation.setCustomValidity(''));
 if(!importLines.children.length)document.getElementById('add-import-line').click();
}
document.querySelectorAll('[data-selection-form]').forEach(form=>{
 const items=[...form.querySelectorAll('[data-selection-item]')];
 const search=form.querySelector('[data-selection-search]'),category=form.querySelector('[data-selection-category]');
 const summary=form.querySelector('[data-selection-summary]');
 const update=()=>{
   const products=form.querySelectorAll('input[name="product_ids"]:checked').length;
   const locations=form.querySelectorAll('input[name="location_ids"]:checked').length;
   summary.textContent=products+' products × '+locations+' locations = '+products*locations+' count rows';
 };
 const filter=()=>{
   const term=search.value.toLowerCase().trim();
   items.forEach(item=>item.hidden=!(item.dataset.search.includes(term)&&(!category.value||item.dataset.category===category.value)));
 };
 search.addEventListener('input',filter);category.addEventListener('change',filter);
 form.querySelectorAll('[data-select-all]').forEach(button=>button.addEventListener('click',()=>{
   form.querySelectorAll('input[name="'+button.dataset.selectAll+'"]').forEach(input=>{if(!input.closest('[data-selection-item]')?.hidden)input.checked=true;});update();
 }));
 form.querySelectorAll('[data-clear-selection]').forEach(button=>button.addEventListener('click',()=>{
   form.querySelectorAll('input[name="'+button.dataset.clearSelection+'"]').forEach(input=>input.checked=false);update();
 }));
 form.addEventListener('change',update);update();
});
const chartElement=document.getElementById('sales-chart');
if(chartElement && window.Chart){
 const data=JSON.parse(document.getElementById('chart-data').textContent);
 new Chart(chartElement,{type:'line',data:{labels:data.labels,datasets:[{data:data.values,borderColor:'#718b51',backgroundColor:'#edf1e0',fill:true,tension:.3,pointRadius:2,borderWidth:2}]},options:{maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{maxTicksLimit:7,color:'#a0a795',font:{size:9},callback:function(v){return this.getLabelForValue(v).slice(5);}}},y:{beginAtZero:true,ticks:{precision:0,color:'#a0a795',font:{size:9}},grid:{color:'#f0f2ea'}}}}});
}

});
