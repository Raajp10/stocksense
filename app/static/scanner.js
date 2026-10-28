'use strict';
(()=>{
const video=document.getElementById('camera'),canvas=document.getElementById('scan-canvas'),
start=document.getElementById('start-camera'),stopButton=document.getElementById('stop-camera'),
status=document.getElementById('camera-status'),placeholder=document.getElementById('camera-placeholder'),
code=document.getElementById('scan-code'),form=document.getElementById('scan-form');
if(!video)return;
let stream=null,running=false,recognized=false,pending=false,generation=0;
function stop(){generation++;running=false;if(stream)stream.getTracks().forEach(t=>t.stop());stream=null;video.srcObject=null;start.hidden=false;start.disabled=false;stopButton.hidden=true;placeholder.hidden=false;}
function accept(value){if(recognized||!value)return;recognized=true;stop();code.value=value;status.textContent='Product code found. Opening review…';form.requestSubmit();}
async function frame(){
 if(!running)return;
 if(video.readyState>=2){
  const scale=Math.min(1,640/video.videoWidth);
  canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);
  const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(video,0,0,canvas.width,canvas.height);
  const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);
  const result=window.jsQR(pixels.data,pixels.width,pixels.height,{inversionAttempts:'dontInvert'});
  if(result){accept(result.data);return;}
 }
 if(running)requestAnimationFrame(frame);
}
start.addEventListener('click',async()=>{
 if(pending||running)return;pending=true;start.disabled=true;recognized=false;const current=++generation;
 try{
  if(!navigator.mediaDevices?.getUserMedia)throw Error('Camera unavailable. Use HTTPS or localhost, or enter the SKU manually.');
  const capture=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1280}},audio:false});
  if(current!==generation){capture.getTracks().forEach(t=>t.stop());return;}
  stream=capture;video.srcObject=stream;await video.play();
  if(current!==generation){stop();return;}
  running=true;placeholder.hidden=true;start.hidden=true;stopButton.hidden=false;
  status.textContent='Point at a StockSense QR label. Scanning pauses after the first code.';frame();
 }catch(error){stop();status.textContent=error.name==='NotAllowedError'?'Camera permission was denied. Enter the SKU or code manually.':error.message;}
 finally{pending=false;start.disabled=false;}
});
stopButton.addEventListener('click',()=>{stop();status.textContent='Camera stopped. Manual code entry is available.';});
window.addEventListener('pagehide',stop);document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
form.addEventListener('submit',stop);
})();
