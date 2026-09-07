/** Compare supported aware timestamps without losing retained microseconds. */
export function restorationInstant(value:unknown):string|null {
 if(typeof value!=="string")return null;
 const parts=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
 if(!parts)return null;
 const [year,month,day,hour,minute,second]=parts.slice(1,7).map(Number);
 const days=[31,year%4===0&&(year%100!==0||year%400===0)?29:28,31,30,31,30,31,31,30,31,30,31];
 const offset=parts[8]==="Z"?[0,0]:parts[8].slice(1).split(":").map(Number);
 if(year<1||month<1||month>12||day<1||day>days[month-1]||hour>23||minute>59||second>59||offset[0]>23||offset[1]>59)return null;
 const whole=new Date(`${parts[1]}-${parts[2]}-${parts[3]}T${parts[4]}:${parts[5]}:${parts[6]}${parts[8]}`);
 if(!Number.isFinite(whole.valueOf()))return null;
 const utc=whole.toISOString();
 if(!/^\d{4}-/.test(utc)||utc.startsWith("0000-"))return null;
 return `${utc.slice(0,19)}.${(parts[7]??"").padEnd(6,"0")}Z`;
}
