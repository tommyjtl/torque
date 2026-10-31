// libfx is an unmodified, integrity-pinned engine. Torque owns every host tool.
import {readFile, readdir, stat} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createInterface} from 'node:readline';

const config = JSON.parse(await readFile(process.argv[2], 'utf8'));
const load = path => import(pathToFileURL(join(config.libfx_path, path)).href);
const {createFxAgent} = await load('node.js');
const {local} = await load('durable/local.mjs');
const {loadSkillFile, createSkillsAdapter} = await load('skills-node.js');
const info = await stat(config.key_file);
if ((info.mode & 0o777) !== 0o600 || info.uid !== process.getuid()) throw Error('Unsafe credential file');
const key = (await readFile(config.key_file, 'utf8')).trim();
if (!key || /\s/.test(key)) throw Error('Invalid credential file');
const send = value => process.stdout.write(JSON.stringify(value).replaceAll(key, '[REDACTED]') + '\n');
const pending = new Map();
let serial = 0, active = false, current;
const schema = properties => ({type:'object', properties, required:Object.keys(properties), additionalProperties:false});
const text = {type:'string'};
const bool = {type:'boolean'};
const definitions = [
  ['shell', 'Advanced shell execution. Auto/ask policy requires approval. Prefer directory/search/read tools, direct board tools and run_program for routine work.', schema({command:text})],
  ['read_file', 'Read a UTF-8 file in the workspace or packaged agent resources.', schema({path:text})],
  ['list_directory', 'List a workspace or packaged-resource directory. Use this instead of shell ls.', schema({path:text})],
  ['search_files', 'Search bounded UTF-8 files for a literal string. Use this instead of shell grep/find.', schema({path:text,query:text})],
  ['write_file', 'Create or replace a UTF-8 file inside projects/. Auto policy permits this; parent folders are created.', schema({path:text, content:text})],
  ['run_program', 'Run an existing projects/*.py program using managed Python, with arguments and no shell. Auto policy permits this. Use for requested programs, not simple direct board commands.', schema({path:text,arguments:{type:'array',items:text}})],
  ['device_snapshot', 'Read the MCU framebuffer/GPIO and display ownership. The working circle is session feedback; standby is one pixel. Readback is not optical observation.', schema({})],
  ['device_capabilities', 'Read connected firmware capabilities and display ownership. Board is UNO Q: binary 8x13 matrix and MCU RGB LEDs 3/4.', schema({})],
  ['input_capabilities', 'Discover currently readable Keychron keypad input for games, menus and interactive projects. Metadata only; no keystrokes consumed or recorded. Read the uno-q-input skill for the shared Python API.', schema({})],
  ['audio_capabilities', 'Inspect the local UNO Q Media Carrier audio capture endpoint and access. Metadata only: does not record, change routing, or prove a microphone signal. For requested audio programs read the uno-q-input audio reference.', schema({})],
  ['matrix_fill', 'Set every one of the 104 matrix pixels on (on=true) or off (on=false). Retains the requested state after this tool/turn, until changed or explicitly released. Use directly for light up all LEDs; no Python file or invented duration.', schema({on:bool})],
  ['matrix_draw', 'Draw 8 rows of exactly 13 binary pixels using . and #, retaining the frame after this turn. Use for a direct static pattern.', schema({rows:{type:'array',items:text}})],
  ['matrix_clear', 'Turn every matrix pixel off and retain the blank display. Session feedback will not repaint over this explicit off state.', schema({})],
  ['matrix_release', 'Explicitly return the matrix to Torque session-status feedback. This differs from turning the matrix off.', schema({})],
  ['rgb_set', 'Set MCU RGB LED 3 or 4 to the given boolean color channels. No PWM, firmware upload or Python file is needed.', schema({led:{type:'integer',enum:[3,4]},red:bool,green:bool,blue:bool})],
];
const readTools=new Set(['read_file','list_directory','search_files','device_snapshot','device_capabilities','input_capabilities','audio_capabilities']);
const tools = definitions.map(([name, description, inputSchema]) => ({
  name, description, inputSchema, idempotent:readTools.has(name),
  async execute(input, ctx) {
    const requestId = `tool-${++serial}`;
    const run = () => new Promise((resolve, reject) => {
      const abort = () => { pending.delete(requestId); reject(Error('Tool cancelled')); };
      if (ctx.signal.aborted) return abort();
      ctx.signal.addEventListener('abort', abort, {once:true});
      pending.set(requestId, {resolve:value=>{ctx.signal.removeEventListener('abort',abort);resolve(value)}, reject});
      send({type:'tool.request', request_id:requestId, session_id:ctx.sessionId,
        execution_id:ctx.executionId, tool:name, arguments:input});
    });
    // Observations do not approve anything. The daemon must authorize each effect.
    const approval=!readTools.has(name) && config.permission_mode!=='full' &&
      (config.permission_mode==='ask' || name==='shell');
    const answer = approval ? await ctx.observation.wait({kind:'approval',externalId:requestId}, run) : await run();
    if (answer.outcome!=='accepted') throw Error(answer.error || 'Permission denied; tool did not execute');
    if (answer.error) throw Error(answer.error);
    return answer.value;
  }
}));
const records=[];
for (const dir of [join(config.agent_dir,'skills'), join(config.workspace,'skills')]) {
  for (const entry of (await readdir(dir,{withFileTypes:true}).catch(e=>e.code==='ENOENT'?[]:Promise.reject(e)))) {
    if (!entry.isDirectory()) continue;
    const path=join(dir,entry.name,'SKILL.md');
    const record=await loadSkillFile(path);
    record.instructions=record.instructions.replace(/\]\((?!https?:)([^)]+)\)/g, (_,ref)=>`](${join(dir,entry.name,ref)})`);
    records.push(record);
  }
}
const skills=createSkillsAdapter(records);
const instructions=[await readFile(join(config.agent_dir,'AGENTS.md'),'utf8'), skills.instructions,
  'For games, menus or interactive projects, consider physical input even if the user does not name the keypad. Check input_capabilities and read the uno-q-input skill. Preserve explicit autoplay and use the shared torque.input API rather than copying evdev code. Keypresses run locally, not through model requests.',
  await readFile(join(config.workspace,'AGENTS.md'),'utf8').catch(e=>e.code==='ENOENT'?'':Promise.reject(e)),
  `Workspace: ${config.workspace}. Managed release: ${config.release_root}. Managed Python: ${config.python}. Permissions: ${config.permission_mode}. Auto permits routine board/project tools; shell still needs approval. Read resources using read_file. Write programs inside projects/. Never request or inspect credentials.`,
  'Users describe outcomes, not implementation details. For ordinary matrix/RGB commands use the direct board tools, not package introspection or a Python demo. Direct on/off/static pattern requests persist until changed. Do not invent a ten-second duration. For explicit coding/animation tasks choose the implementation yourself. The Python API is: from torque import Board, Frame; with Board() as b: b.matrix.draw(Frame.from_rows(rows)); b.rgb(3).set(True,False,False); b.snapshot(). Use run_program with a .py path and arguments instead of shell Python.',
  'After a successful action, give a short factual outcome, usually one sentence. Use returned display_mode/retained/framebuffer fields; do not call a working circle idle, or say off when a status pattern is visible. Mention technical details or limitations when material or requested; do not routinely narrate imports, file paths or unrelated non-actions.',
];
const agent=createFxAgent({name:'torque', backend:'native', model:config.model,
  provider:{name:'modular',baseUrl:'https://api.modular.com/v1',models:config.models},
  credentials:()=>({apiKey:key}),durability:local({dir:config.sessions_dir}),instructions,tools,
  hooks:{captureContent:false,onEvent:event=>send({type:'engine.hook',event})},
});
async function dispatch(message) {
  if(message.op==='tool.result') {
    const target=pending.get(message.request_id);
    if(target){pending.delete(message.request_id);target.resolve(message.result)}
    return;
  }
  if(message.op==='cancel'){await current?.cancel();return;}
  if(message.op!=='prompt')throw Error('Unknown engine operation');
  if(active)throw Error('A turn is already active');
  active=true;
  try {
    current=agent.session(message.session_id || undefined, {model:config.model});
    const turn=current.prompt(message.prompt,{messageId:message.message_id});
    send({type:'turn.accepted',...(await turn.accepted)});
    for await(const event of turn)send({type:'engine.output',event});
    send({type:'turn.result',result:await turn.result});
  } finally {active=false;}
}
const input=createInterface({input:process.stdin,crlfDelay:Infinity});
input.on('line',line=>{
  if(Buffer.byteLength(line)>256*1024){send({type:'worker.error',error:'Input too large'});return;}
  try{Promise.resolve(dispatch(JSON.parse(line))).catch(e=>send({type:'worker.error',error:String(e)}))}
  catch(e){send({type:'worker.error',error:String(e)})}
});
input.on('close',async()=>{await current?.cancel();await agent.close();process.exit(0)});
send({type:'worker.ready',skills:records.map(r=>r.name),model:config.model,backend:'native'});
