import type {WorkRun} from "./action-model";

export function processLayout(run:WorkRun) {
  const nodes=run.definition.nodes??[];
  if(nodes.length>200)return {error:"This process exceeds the 200-step canvas limit.",nodes:[],edges:[]};
  const index=new Map(nodes.map(n=>[n.id,n]));
  if(index.size!==nodes.length)return {error:"The recorded definition contains duplicate step identities.",nodes:[],edges:[]};
  const depth=new Map<string,number>();const edges:{source:string;target:string}[]=[];
  for(const node of nodes)for(const dep of node.depends_on){if(!index.has(dep))return {error:"A recorded dependency is unavailable; the graph is incomplete.",nodes:[],edges:[]};edges.push({source:dep,target:node.id});}
  if(edges.length>1000)return {error:"This process exceeds the 1,000-connection canvas limit.",nodes:[],edges:[]};
  let pending=[...nodes];
  while(pending.length){const ready=pending.filter(n=>n.depends_on.every(id=>depth.has(id)));if(!ready.length)return {error:"This definition contains a loop; use its recorded event history instead of a DAG view.",nodes:[],edges:[]};for(const node of ready)depth.set(node.id,Math.max(-1,...node.depends_on.map(id=>depth.get(id)!))+1);pending=pending.filter(n=>!depth.has(n.id));}
  const levels=new Map<number,number>();
  return {error:"",edges,nodes:nodes.map(node=>{const level=depth.get(node.id)!;const slot=levels.get(level)??0;levels.set(level,slot+1);
    return {...node,x:24+level*270,y:24+slot*112};})};
}
