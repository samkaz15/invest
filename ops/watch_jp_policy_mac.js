// Script Editor: JavaScript. Save as Application with "Stay open after run handler".
const api = "https://api.github.com/repos/samkaz15/invest/contents/data/knowledge/jp?ref=main";
const raw = "https://raw.githubusercontent.com/samkaz15/invest/main/data/knowledge/jp/";
const state = '$HOME/Library/Application Support/invest-jp-notify/seen.json';
function shellQuote(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'"; }
function curl(app, url) { return app.doShellScript("/usr/bin/curl --disable --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 8 --max-time 25 " + shellQuote(url), {alteringLineEndings:false}); }
function save(app, ids) { const json=JSON.stringify(ids); app.doShellScript('/bin/mkdir -p "$HOME/Library/Application Support/invest-jp-notify"; /usr/bin/printf %s ' + shellQuote(json) + ' > "' + state + '.tmp"; /bin/mv "' + state + '.tmp" "' + state + '"'); }
function scan() {
  const app=Application.currentApplication(); app.includeStandardAdditions=true;
  const files=JSON.parse(curl(app,api));
  if(!Array.isArray(files)) throw Error("資料一覧が不正です");
  let seen=[]; let first=false;
  try { seen=JSON.parse(app.doShellScript('/bin/cat "' + state + '"')); if(!Array.isArray(seen)) throw Error("invalid"); }
  catch(e) { if(String(e).includes("No such file")) first=true; else throw e; }
  const names=files.map(f=>f.name).filter(n=>/^[a-z0-9][a-z0-9_-]*\.json$/.test(n)).sort();
  if(first && names.length) { seen=names.slice(0,-1); save(app,seen); }
  for(const name of names) {
    if(seen.includes(name)) continue;
    const d=JSON.parse(curl(app,raw+name));
    if(d.notification_eligible===true && typeof d.summary_ja==="string" && d.summary_ja.length) {
      app.displayNotification(d.summary_ja,{withTitle:"日銀・日本市場情報",subtitle:d.title_ja||"",soundName:"Glass"});
    }
    seen.push(name); save(app,seen);
  }
}
function run() { try { scan(); } catch(e) { console.log("取得失敗・次回再試行: "+e); } }
function idle() { run(); return 60; }
