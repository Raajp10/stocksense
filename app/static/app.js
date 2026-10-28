'use strict';
document.addEventListener('DOMContentLoaded',()=>{
document.querySelectorAll('[data-print]').forEach(button=>button.addEventListener('click',()=>window.print()));
document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',event=>{
  const button=event.submitter;
  if(button){setTimeout(()=>{button.disabled=true;button.dataset.original=button.textContent;button.textContent='Saving…';},0);}
}));
window.addEventListener('pageshow',()=>document.querySelectorAll('button[data-original]').forEach(b=>{b.disabled=false;b.textContent=b.dataset.original;}));
const chartElement=document.getElementById('sales-chart');
if(chartElement && window.Chart){
 const data=JSON.parse(document.getElementById('chart-data').textContent);
 new Chart(chartElement,{type:'line',data:{labels:data.labels,datasets:[{data:data.values,borderColor:'#718b51',backgroundColor:'#edf1e0',fill:true,tension:.3,pointRadius:2,borderWidth:2}]},options:{maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{maxTicksLimit:7,color:'#a0a795',font:{size:9},callback:function(v){return this.getLabelForValue(v).slice(5);}}},y:{beginAtZero:true,ticks:{precision:0,color:'#a0a795',font:{size:9}},grid:{color:'#f0f2ea'}}}}});
}

});
