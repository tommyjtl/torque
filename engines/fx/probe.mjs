import {createFxAgent, getBackendInfo} from 'libfx';
import {local} from 'libfx/durable-local';
import {createSkillsAdapter,loadSkillFile} from 'libfx/skills/node';
import {readFile,writeFile,mkdir,stat,readdir} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {join} from 'node:path';
import {homedir} from 'node:os';
const run=promisify(execFile), root=process.cwd(), home=homedir();
const keyPath=join(home,'.config/fx/modular-api-key');
const keyInfo=await stat(keyPath); if((keyInfo.mode&0o777)!==0o600 || keyInfo.uid!==process.getuid())throw Error('Unsafe key file');
const key=(await readFile(keyPath,'utf8')).trim(); if(!key || /\s/.test(key))throw Error('Invalid key');
const redact=v=>JSON.stringify(v).replaceAll(key,'[REDACTED]');
const assert=(v,m)=>{if(!v)throw Error(m)};
const before=await readFile(join(home,'.fx/settings.json'));
const hooks=[], effects=[], decisions=[], outputs=[];
let requests=0;
try {
for(const [dir,name,instruction] of [['managed','torque-managed-probe','When asked for the probe markers, say MANAGED-COPPER.'],['workspace/skills/user-probe','user-probe','When asked for the probe markers, also say USER-ORBIT.']]){
 await mkdir(join(root,dir),{recursive:true,mode:0o700});
 await writeFile(join(root,dir,'SKILL.md'),`---\nname: ${name}\ndescription: Probe marker instructions.\n---\n${instruction}\n`);
}
const skills=createSkillsAdapter(await Promise.all(['managed/SKILL.md','workspace/skills/user-probe/SKILL.md'].map(p=>loadSkillFile(join(root,p)))));
const sessionDir=join(root,'sessions'); await mkdir(sessionDir,{recursive:true,mode:0o700});
const options={name:'torque-engine-proof',backend:'native',model:'MiniMaxAI/MiniMax-M3.1-Flash',
 provider:{name:'modular',baseUrl:'https://api.modular.com/v1',models:{'MiniMaxAI/MiniMax-M3.1-Flash':{contextWindow:1048576,maxOutputTokens:2048,supportsToolUse:true,supportsVision:true}}},
 credentials:()=>({apiKey:key}),
 durability:local({dir:sessionDir}),
 fetch:(...args)=>{requests++;return fetch(...args)},
 instructions:[skills.instructions,'Use the board_probe tool exactly once when asked; use precisely the command requested. Do not retry denied tools. Never read credentials.'],
 hooks:{captureContent:false,onEvent:e=>hooks.push({type:e.type,data:e.data})},
 tools:[{name:'board_probe',description:'Run a command after the host authorizes that exact action. Only uname -m has been authorized by the user for this probe.',idempotent:false,
 inputSchema:{type:'object',properties:{command:{type:'string'}},required:['command'],additionalProperties:false},
 async execute(input,ctx){
  if(!input || typeof input.command!=='string')throw Error('Invalid command');
  const decision=await ctx.observation.wait({kind:'approval',prompt:input.command},async()=>{
    await new Promise(r=>setTimeout(r,200));
    const approved=input.command==='uname -m'; decisions.push({command:input.command,approved});
    return {outcome:approved?'accepted':'denied'};
  });
  if(decision.outcome!=='accepted')throw Error('Permission denied; command was not executed.');
  const env={PATH:'/usr/bin:/bin',HOME:home};
  const result=await run('/usr/bin/uname',['-m'],{cwd:join(root,'workspace'),env,timeout:5000});
  effects.push(input.command);return {architecture:result.stdout.trim(),home:env.HOME};
 }}]};
const backend=await getBackendInfo({surface:'agent',backend:'native'});assert(backend.backend==='native','Native backend failed');
let agent=createFxAgent(options), session=agent.session();
const turn=session.prompt('Return both probe markers, then use board_probe to run uname -m exactly once and report the actual architecture. Remember continuity code TORQUE-KEYSTONE for my next message.');
const accepted=await turn.accepted;
// A turn continues with no attached stream reader; this models a frontend detach.
await new Promise(r=>setTimeout(r,1200));
let text='';for await(const event of turn){if(event.type==='text_delta')text+=event.delta;}
const result=await turn.result;outputs.push(text);
assert(result.stopReason==='end_turn','Initial turn failed');
assert(text.includes('MANAGED-COPPER')&&text.includes('USER-ORBIT'),'Two skill scopes not followed');
assert(text.includes('aarch64')&&effects.length===1,'Real approved shell tool failed');
await agent.close();
agent=createFxAgent(options);session=agent.session(accepted.sessionId);
const resumed=session.prompt('What continuity code did I give you? Answer it without tools.');
text='';for await(const e of resumed){if(e.type==='text_delta')text+=e.delta;}
assert((await resumed.result).stopReason==='end_turn'&&text.includes('TORQUE-KEYSTONE'),'Session persistence failed');outputs.push(text);
assert(effects.length===1,'Resume repeated an effect');
const denied=session.prompt('For the permission-denial test only, call board_probe once with command touch forbidden-marker, even though it must be denied. Do not retry. Report the denial.');
text='';for await(const e of denied){if(e.type==='text_delta')text+=e.delta;}
assert((await denied.result).stopReason==='end_turn','Denial turn failed');outputs.push(text);
assert(decisions.some(d=>!d.approved)&&effects.length===1,'Permission denial did not prevent execution');
await agent.close();
assert(before.equals(await readFile(join(home,'.fx/settings.json'))),'Global fx settings changed');
let leaked=false;async function scan(dir){for(const entry of await readdir(dir,{withFileTypes:true})){const path=join(dir,entry.name);if(entry.isDirectory())await scan(path);else if((await readFile(path)).includes(Buffer.from(key)))leaked=true;}}
await scan(sessionDir);assert(!leaked,'Credential persisted in session state');
const types=[...new Set(hooks.map(e=>e.type))];
for(const type of ['turn.start','turn.end','model.start','model.end','tool.start','tool.end','wait.start','wait.end'])assert(types.includes(type),'Missing real hook '+type);
const report={passed:true,backend:backend.backend,libfx:'0.0.14',architecture:process.arch,model:options.model,requests,tool_effects:effects,decisions,hook_types:types,outputs,config_unchanged:true,credential_in_state:false,session_id:accepted.sessionId,session_continuity:true,detached_frontend:true,rss_mib:Math.round(process.memoryUsage().rss/1048576)};
await writeFile(join(root,'report.json'),redact(report),{mode:0o600}); console.log(redact(report));
} catch(e) { console.error(redact({passed:false,error:String(e)}));process.exitCode=1; }
