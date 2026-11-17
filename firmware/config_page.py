"""The SP103's own web page: http://<the Pico's IP>/ in a browser, to change what the amp's display shows.

The display texts (input names, boot and about screens), the VU meter and the info screens are the SP103's own
extras, outside the DeviceLink contract (device-link docs/contract-v2.md): the app shows the device's state and remote,
never these. This page edits them over the bridge's own routes (settings.py):

    GET   /                  this page (the Wi-Fi setup page instead, while the setup network is open: wifi.py)
    GET   /config            this page, always
    GET   /settings/fields   what the page draws: [{"id", "type", "label", "group", "hint", "when", ...}]
    GET   /settings          the values, {"<id>": value}
    PATCH /settings          only what changed; 1 s after the last edit, since each write goes to flash

The page is one string, sent in chunks (web.reply), about 4 KB.
"""

net = None                      # proxy.py sets it: the setup page goes first while the setup network is open


async def handle(req, writer):
    """Routes / and /config (see web.Publisher)."""
    from web import reply
    if req.path == "/" and net is not None and net.setup_open():
        return await net.page(req, writer)
    if req.path not in ("/", "/config"):
        return await reply(writer, "404 Not Found", "text/plain", b"not found\n")
    name = net.name if net is not None else "SP103"
    await reply(writer, "200 OK", "text/html; charset=utf-8", PAGE.replace("NAME", name).encode())


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>NAME display</title>
<style>
:root{--bg:#fafafa;--fg:#222;--dim:#666;--card:#fff;--line:#ddd;--err:#c62828;--ok:#2e7d32}
@media(prefers-color-scheme:dark){:root{--bg:#121212;--fg:#eee;--dim:#aaa;--card:#1e1e1e;--line:#333;--err:#ef9a9a;--ok:#a5d6a7}}
body{font:16px sans-serif;margin:0 auto;padding:16px;max-width:520px;background:var(--bg);color:var(--fg)}
h1{font-size:20px;margin:0}h2{font-size:15px;margin:0 0 8px;color:var(--dim)}
section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin:12px 0}
label{display:block;margin:10px 0 2px}.row{display:flex;justify-content:space-between;align-items:center;gap:8px}
input[type=text],select{font:inherit;width:100%;box-sizing:border-box;padding:7px;background:var(--bg);color:var(--fg);
border:1px solid var(--line);border-radius:6px}input.lcd{font-family:monospace}input.bad{border-color:var(--err)}
input[type=checkbox]{width:22px;height:22px}input[type=number]{font:inherit;width:80px;padding:6px}
small{display:block;color:var(--dim);font-size:13px;margin-top:2px}#msg{min-height:20px;font-size:14px}
.err{color:var(--err)}.ok{color:var(--ok)}
</style></head><body>
<h1>NAME</h1><small>What the amp's display shows. Changes are saved on the amp a second after you stop typing.</small>
<div id="msg"></div><div id="form">Loading...</div>
<script>
const $=id=>document.getElementById(id);let F=[],V={},P={},T=0;
const lcd=(s,n)=>s.normalize('NFD').split('').filter(c=>c>=' '&&c<='}'&&c!='\\\\').join('').slice(0,n);
const isIp=s=>/^(\\d{1,3})\\.(\\d{1,3})\\.(\\d{1,3})\\.(\\d{1,3})$/.test(s)&&s.split('.').every(p=>+p<256);
const val=id=>id in P?P[id]:V[id];
const esc=s=>String(s).replace(/[&<>"]/g,c=>'&#'+c.charCodeAt(0)+';');
function msg(t,c){$('msg').textContent=t;$('msg').className=c||'';}
function set(id,v){P[id]=v;msg('Saving...');clearTimeout(T);T=setTimeout(save,1000);}
async function save(){const sent=P;P={};
 try{const r=await fetch('/settings',{method:'PATCH',body:JSON.stringify(sent)});const j=await r.json();
  if(!r.ok){msg(j.error,'err');draw();return;}V=j;if(!Object.keys(P).length)msg('Saved','ok');}
 catch(e){P=Object.assign(sent,P);msg('No answer, trying again: '+e,'err');clearTimeout(T);T=setTimeout(save,3000);}}
function field(f){const v=val(f.id),w=document.createElement('div'),L=`<label for="${f.id}">${esc(f.label)}</label>`;let h='';
 if(f.type=='bool')h=`<div class="row">${L}<input type="checkbox" id="${f.id}"${v?' checked':''}></div>`;
 else if(f.type=='enum')h=`${L}<select id="${f.id}">`+f.values.map((x,i)=>
  `<option value="${x}"${x==v?' selected':''}>${esc((f.labels||[])[i]||x)}</option>`).join('')+'</select>';
 else if(f.type=='int')h=`<div class="row">${L}<input type="number" id="${f.id}" min="${f.min}" max="${f.max}" step="${f.step||1}"></div>`;
 else h=`${L}<input type="text" id="${f.id}"${f.charset=='lcd'?' class="lcd"':''}${f.max?` maxlength="${f.max}"`:''} placeholder="${esc(f.placeholder||(f.type=='ip'?'192.168.1.50':''))}">`;
 if(f.hint)h+=`<small>${esc(f.hint)}</small>`;w.innerHTML=h;const e=w.querySelector('input,select');
 if(f.type=='bool')e.onchange=()=>{set(f.id,e.checked);draw();};
 else if(f.type=='enum')e.onchange=()=>{set(f.id,e.value);draw();};
 else if(f.type=='int'){e.value=v;e.onchange=()=>{const n=Math.round(+e.value);if(n>=f.min&&n<=f.max)set(f.id,n);else e.value=val(f.id);};}
 else{e.value=v||'';e.oninput=()=>{let t=e.value;if(f.charset=='lcd'){t=lcd(t,f.max);if(t!=e.value)e.value=t;}
  if(f.type=='ip'){e.classList.toggle('bad',t!=''&&!isIp(t));if(t!=''&&!isIp(t))return;}set(f.id,t);};}
 return w;}
function draw(){const form=$('form'),groups={};form.innerHTML='';
 for(const f of F){if(Object.entries(f.when||{}).some(([k,x])=>val(k)!==x))continue;
  let s=groups[f.group];if(!s){s=groups[f.group]=document.createElement('section');s.innerHTML=`<h2>${esc(f.group)}</h2>`;form.appendChild(s);}
  s.appendChild(field(f));}}
(async()=>{try{F=await (await fetch('/settings/fields')).json();V=await (await fetch('/settings')).json();draw();}
 catch(e){$('form').textContent='The amp did not answer: '+e;}})();
</script></body></html>"""
