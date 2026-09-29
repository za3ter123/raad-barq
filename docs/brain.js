/* Ra'ad on GitHub Pages: a browser port of server.py's /voice pipeline.
   Wraps window.fetch so voice.html's POST /voice runs here instead of on a server:
   Groq Whisper (STT) -> DeepSeek (brain, with the rulebook tool) -> ElevenLabs (voice).
   Keys come from the login vault (sessionStorage). prompt.json and rules.json are generated
   from server.py by tools/build_pages.py, so the prompt and the rule data have one source.
   The strings copied from inside stt_groq() and answer() below must match server.py. */
(function(){
'use strict';
const KEYS='raad_keys';
const _fetch=window.fetch.bind(window);
const GROQ_STT='https://api.groq.com/openai/v1/audio/transcriptions';
const DEEPSEEK='https://api.deepseek.com/chat/completions';
const ELEVEN='https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128';
const MAX_BODY=15*1024*1024;
// same as stt_groq: a fake preceding transcript in Kuwaiti register biases Whisper's decoding
const STT_PROMPT='هلا، شلونك؟ شنو هذا؟ چم صار وقتها؟ وايد حلو ماشاءالله! أكو سباق اليوم. '+
                 'سيارة BOLT من فريق Barq Racing، رعد، F1 in Schools، STEM Racing.';

function keys(){try{return JSON.parse(sessionStorage.getItem(KEYS)||'null');}catch(e){return null;}}
if(!keys())location.replace('./');   // no session: back to the login page

/* ---------- small helpers (Python indexes strings by code point, JS by UTF-16 unit) ---------- */
const cp=s=>Array.from(s);
const count=(h,n)=>h.split(n).length-1;              // == Python str.count (non-overlapping)
const escRe=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
function stripChars(s,chars){let a=0,b=s.length;
  while(a<b&&chars.includes(s[a]))a++;while(b>a&&chars.includes(s[b-1]))b--;return s.slice(a,b);}
function b64(buf){const u8=new Uint8Array(buf);let s='';
  for(let i=0;i<u8.length;i+=0x8000)s+=String.fromCharCode.apply(null,u8.subarray(i,i+0x8000));return btoa(s);}
const tmo=ms=>(window.AbortSignal&&AbortSignal.timeout)?AbortSignal.timeout(ms):undefined;
async function ok(r){if(!r.ok)throw new Error('HTTP Error '+r.status+': '+r.statusText);return r;}   // like urllib
const json=(status,obj)=>new Response(JSON.stringify(obj),{status,headers:{'Content-Type':'application/json'}});

let DATA=null;
function data(){
  return DATA||(DATA=Promise.all([_fetch('prompt.json').then(ok).then(r=>r.json()),
                                  _fetch('rules.json').then(ok).then(r=>r.json())])
    .then(([p,rules])=>Object.assign(p,{rules,trigRe:new RegExp(p.trig,'i'),stopSet:new Set(p.stop)}))
    .catch(e=>{DATA=null;throw e;}));
}

/* ---------- STT: Groq Whisper, same fields and language normalisation as stt_groq ---------- */
// same as audio_ext: Groq picks the decoder from the filename; Safari records audio/mp4 (AAC)
function audioExt(mime){const m=mime.toLowerCase();
  return m.includes('webm')?'webm':m.includes('ogg')?'ogg'
    :(m.includes('mp4')||m.includes('m4a')||m.includes('aac'))?'m4a'
    :(m.includes('mpeg')||m.includes('mp3'))?'mp3':'wav';}
async function sttGroq(blob,mime,k){
  if(!k.groq)throw new Error('no Groq API key set (config.json or GROQ_API_KEY)');
  const ext=audioExt(mime);
  const fd=new FormData();
  fd.append('model','whisper-large-v3');fd.append('response_format','verbose_json');fd.append('prompt',STT_PROMPT);
  fd.append('file',new Blob([blob],{type:mime}),'a.'+ext);
  const r=await ok(await _fetch(GROQ_STT,{method:'POST',headers:{Authorization:'Bearer '+k.groq},body:fd,signal:tmo(60000)}));
  const out=await r.json();
  const lang=String(out.language||'en').toLowerCase();   // comes back as "english"/"arabic"
  return [String(out.text||'').trim(),lang.startsWith('ar')?'ar':'en'];
}

/* ---------- STT fallback: ElevenLabs Scribe, same as stt_scribe / stt ---------- */
const SCRIBE='https://api.elevenlabs.io/v1/speech-to-text';
async function sttScribe(blob,mime,k){
  const ext=audioExt(mime);
  const fd=new FormData();
  fd.append('model_id','scribe_v2');fd.append('tag_audio_events','false');
  fd.append('file',new Blob([blob],{type:mime}),'a.'+ext);
  const r=await ok(await _fetch(SCRIBE,{method:'POST',headers:{'xi-api-key':k.elevenlabs},body:fd,signal:tmo(60000)}));
  const out=await r.json();
  const lang=String(out.language_code||'en').toLowerCase();   // "en"/"ar" or "eng"/"ara"
  return [String(out.text||'').trim(),lang.startsWith('ar')?'ar':'en'];
}
// Groq first; on ANY Groq failure try Scribe once (never both at once). No ElevenLabs key: Groq's error stands.
async function stt(blob,mime,k){
  let groqErr;
  try{return await sttGroq(blob,mime,k);}catch(e){if(!k.elevenlabs)throw e;groqErr=e;}
  try{return await sttScribe(blob,mime,k);}
  catch(e){throw new Error('groq: '+groqErr.message+'; scribe: '+e.message);}
}

/* ---------- LLM: DeepSeek, same model and params as llm_chat ---------- */
async function llmChat(messages,k){
  if(!k.deepseek)throw new Error('no DeepSeek API key (the local Ollama fallback needs the Python server)');
  const r=await ok(await _fetch(DEEPSEEK,{method:'POST',signal:tmo(60000),
    headers:{'Content-Type':'application/json',Authorization:'Bearer '+k.deepseek},
    body:JSON.stringify({model:'deepseek-chat',messages,max_tokens:200,temperature:0.7})}));
  return (await r.json()).choices[0].message.content.trim();
}

/* ---------- TTS: ElevenLabs, same model and voices as tts_eleven / tts ---------- */
async function tts(text,lang,k,D){
  if(lang!=='ar')text=text.replace(/\bra'?ad\b/gi,'رعد');   // English TTS butchers "Ra'ad"
  // no Edge voices in a browser: without ElevenLabs the page speaks with speechSynthesis
  if(!k.elevenlabs)throw new Error('no ElevenLabs key, the browser voice speaks instead');
  const v=(lang==='ar'?D.voices.ar:D.voices.en)||D.voices.default;
  const r=await ok(await _fetch(ELEVEN.replace('%s',v),{method:'POST',signal:tmo(30000),
    headers:{'Content-Type':'application/json','xi-api-key':k.elevenlabs},
    body:JSON.stringify({text,model_id:'eleven_flash_v2_5'})}));
  return r.arrayBuffer();
}

/* ---------- wake word: same as strip_punct / wake_check ---------- */
const stripPunct=s=>s.toLowerCase().replace(/[^\p{L}\p{N}_؀-ۿ' ]+/gu,' ').trim();
function wakeCheck(transcript,D){
  const clean=stripPunct(transcript),head=cp(clean).slice(0,40).join('');
  for(let w of D.wake_words){
    w=stripPunct(w);
    const m=new RegExp('(?:^|\\s)'+escRe(w)+'(?:$|\\s)','u').exec(head);
    if(m){const rest=stripChars(clean.slice(m.index+m[0].length),' ,._-؟?!');
      return rest||transcript;}   // woken with no question -> greet
  }
  return null;
}

/* ---------- rulebook brain: same scoring as rules_lookup ---------- */
function rulesLookup(query,D){
  const words=(query.toLowerCase().match(/[a-z0-9.]+/g)||[]).filter(w=>!D.stopSet.has(w));
  if(!words.length)return '(no query terms)';
  const bigrams=words.slice(1).map((w,i)=>words[i]+' '+w);
  const isLimit=/max|min|limit|weight|mass|length|width|height|how (many|much)|pages/i.test(query);
  const scored=[];
  for(const [src,chunk] of D.rules){
    const low=chunk.toLowerCase();
    // skip table-of-contents style chunks (mostly tiny lines / bare numbers)
    const lines=chunk.split('\n').map(l=>l.trim()).filter(Boolean);
    if(lines.length&&lines.filter(l=>cp(l).length<25).length>lines.length*0.6)continue;
    let score=words.reduce((s,w)=>s+Math.min(count(low,w),2),0);
    score+=bigrams.reduce((s,b)=>s+5*count(low,b),0);
    if(isLimit&&/absolute (min|max)|maximum of|minimum of|assessed pages/i.test(chunk))score+=4;
    if(score)scored.push([score,src,chunk]);
  }
  scored.sort((a,b)=>b[0]-a[0]);   // stable, like Python's sort
  const out=[];let used=0;
  for(const [,src,chunk] of scored.slice(0,8)){
    const piece='['+src+']\n'+cp(chunk).slice(0,900).join(''),n=cp(piece).length;
    if(used+n>6000)break;
    out.push(piece);used+=n;
  }
  return out.join('\n\n')||'(nothing found in the rulebooks)';
}
function rulesQuery(q,D){
  const extra=D.ar2en.filter(([ar])=>q.includes(ar)).map(([,en])=>en).join(' ');
  return (q+' '+extra).trim();
}

/* ---------- answer(): same as server.answer minus SEARCH and Instagram (no scraping from a browser) ---------- */
async function answer(question,k,D){
  let system=D.system;
  // regulations question? -> pull rulebook passages into context deterministically
  if(D.trigRe.test(question)){
    const passages=rulesLookup(rulesQuery(question,D),D);
    if(passages&&!passages.startsWith('('))
      system+='\n\nOFFICIAL RULEBOOK PASSAGES (retrieved for this question):\n'+passages+
        '\n\nSTRICT RULE: any regulation number/limit you state MUST appear '+
        'VERBATIM in the passages above. Your own memory of rule numbers is WRONG — '+
        'it is from old seasons. If the passages do not contain the number asked for, '+
        "you MUST reply that the 2026 regulations don't state it / you're not certain, "+
        'and suggest asking a Barq Racing team member. NEVER invent or recall a number.';
  }
  const msgs=[{role:'system',content:system},{role:'user',content:question}];
  let out;
  try{out=await llmChat(msgs,k);}catch(e){return '(brain error: '+e.message+')';}
  // one hop of rulebook lookup if the model asked for it (may appear after a preamble line)
  const m=/\bRULES\s*:\s*(.+)$/im.exec(out);
  if(m){
    const passages=rulesLookup(m[1].trim(),D);
    msgs.push({role:'assistant',content:out});
    msgs.push({role:'user',content:'Official rulebook passages:\n'+passages+
      '\n\nNow answer my original question using these, in MY language, '+
      "concise for speaking aloud. If the passages don't contain the answer, "+
      "say you're not certain rather than guessing."});
    try{out=await llmChat(msgs,k);}catch(e){out='(brain error after rules lookup: '+e.message+')';}
  }
  return out;
}

/* ---------- POST /voice: same steps and JSON shape as H.do_POST ---------- */
async function voice(init){
  const k=keys();
  if(!k)return json(401,{error:'login required'});
  const hdr=new Headers(init.headers||{});
  let audio,mime;
  try{audio=await new Response(init.body).blob();mime=hdr.has('Content-Type')?hdr.get('Content-Type'):'audio/webm';}
  catch(e){return json(400,{error:'bad request'});}
  if(audio.size>MAX_BODY)return json(413,{error:'request too large'});
  let D;
  try{D=await data();}catch(e){return json(200,{woke:false,error:'setup: '+e.message});}
  let heard,lang;
  try{[heard,lang]=await stt(audio,mime,k);}
  catch(e){return json(200,{woke:false,error:'stt: '+e.message});}
  // code-switched speech: reply in whichever language dominates the question
  const arN=(heard.match(/[؀-ۿ]/g)||[]).length,enN=(heard.match(/[A-Za-z]/g)||[]).length;
  if(arN||enN)lang=arN>=enN?'ar':'en';
  if(!heard)return json(200,{woke:false,heard:''});
  let question;
  if(hdr.get('X-PTT')==='1')question=wakeCheck(heard,D)||heard;   // push-to-talk: no wake word needed
  else{question=wakeCheck(heard,D);if(question===null)return json(200,{woke:false,heard});}
  const reply=await answer(question,k,D);
  lang=/[؀-ۿ]/.test(reply)?'ar':(lang==='ar'?'ar':'en');
  const resp={woke:true,heard,reply,lang};
  try{resp.audio=b64(await tts(reply,lang,k,D));}catch(e){resp.error='tts: '+e.message;}
  return json(200,resp);
}

// iOS only lets speechSynthesis talk later if it spoke once inside a gesture: prime it on the first tap
addEventListener('click',()=>{try{speechSynthesis.speak(new SpeechSynthesisUtterance(''));}catch(e){}},{capture:true,once:true});

window.RAAD_BRAIN={rulesLookup,rulesQuery,wakeCheck,stripPunct,audioExt,   // pure helpers, for tools/check_pages_parity.py
  sttScribe:(blob,mime)=>sttScribe(blob,mime,keys()||{})};         // direct fallback check; uses this tab's session keys
window.fetch=function(input,init){
  const url=typeof input==='string'?input:'';
  if(url==='/voice'&&init&&String(init.method||'').toUpperCase()==='POST')return voice(init);
  return _fetch(input,init);
};
})();
