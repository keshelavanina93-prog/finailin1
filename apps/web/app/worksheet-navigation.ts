/** Pixel geometry only: reveal a cell inside the area not covered by frozen headers. */
export function worksheetReveal(input:{left:number;top:number;width:number;height:number;stickyWidth:number;headerHeight:number;cellLeft:number;cellTop:number;cellWidth:number;cellHeight:number;pinned:boolean}):{left:number;top:number} {
 let {left,top}=input;
 const width=Math.max(0,input.width-input.stickyWidth),height=Math.max(0,input.height-input.headerHeight);
 if(!input.pinned&&width>0){
  if(input.cellLeft<left+input.stickyWidth||input.cellWidth>width)left=input.cellLeft-input.stickyWidth;
  else if(input.cellLeft+input.cellWidth>left+input.width)left=input.cellLeft+input.cellWidth-input.width;
 }
 if(height>0){
  if(input.cellTop<top+input.headerHeight||input.cellHeight>height)top=input.cellTop-input.headerHeight;
  else if(input.cellTop+input.cellHeight>top+input.height)top=input.cellTop+input.cellHeight-input.height;
 }
 return {left:Math.max(0,left),top:Math.max(0,top)};
}
/** A superseded callback cannot move focus even when its canceled frame is delivered. */
export function worksheetFocusScheduler(schedule:(callback:()=>void)=>number,cancelFrame:(frame:number)=>void){
 let frame:number|null=null,generation=0;
 function cancel(){generation++;if(frame!==null)cancelFrame(frame);frame=null;}
 return {cancel,schedule(callback:()=>void){cancel();const current=generation;frame=schedule(()=>{if(current!==generation)return;frame=null;callback();});}};
}
