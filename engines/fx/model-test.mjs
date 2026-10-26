// Explicit, bounded inference probe. No shell, file, MCU or user-session tools.
import {readFile, lstat} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';

let key = '', agent, deadlineTimer;
const output = value => process.stdout.write(JSON.stringify(value).replaceAll(key || '\u0000', '[REDACTED]') + '\n');
const result = {text: false, tool: false, passed: false, requests: 0, effects: 0};
const deadline = new AbortController();
try {
  const config = JSON.parse(await readFile(process.argv[2], 'utf8'));
  const info = await lstat(config.key_file);
  if (!info.isFile() || (info.mode & 0o777) !== 0o600 || info.uid !== process.getuid()) throw Error('Unsafe credential');
  key = (await readFile(config.key_file, 'utf8')).trim();
  if (!key || /\s/.test(key)) throw Error('Invalid credential');
  const {createFxAgent, memory} = await import(pathToFileURL(join(config.libfx_path, 'node.js')).href);
  const nonce = randomUUID();
  let phase = 'text', calls = 0;
  const profile = {...config.profile, maxOutputTokens: Math.min(config.profile.maxOutputTokens || 2048, 2048)};
  agent = createFxAgent({
    name: 'torque-model-test', backend: 'native', model: config.model,
    provider: {name: 'modular', baseUrl: 'https://api.modular.com/v1', models: {[config.model]: profile}},
    credentials: () => ({apiKey: key}), durability: memory(),
    instructions: 'This is a compatibility probe. Follow the requested output exactly. Use only the provided harmless nonce tool when asked.',
    fetch: (url, init) => {
      if (++result.requests > 6) throw Error('Request budget exceeded');
      return fetch(url, {...init, signal: AbortSignal.any([init.signal, deadline.signal].filter(Boolean))});
    },
    tools: [{name: 'torque_probe', description: 'Read-only nonce echo for this compatibility test; no external effects.',
      idempotent: true, inputSchema: {type: 'object', properties: {nonce: {type: 'string'}},
        required: ['nonce'], additionalProperties: false},
      execute(input, ctx) {
        if (ctx.signal.aborted || phase !== 'tool' || !input || Object.keys(input).length !== 1 || input.nonce !== nonce)
          throw Error('Invalid nonce probe');
        if (++calls > 1) throw Error('Probe called more than once');
        return {confirmation: 'TORQUE_TOOL_OK', nonce};
      },
    }],
  });
  deadlineTimer = setTimeout(() => deadline.abort(), 75000);
  const session = agent.session(undefined, {model: config.model});
  async function turn(prompt) {
    const request = session.prompt(prompt);
    let text = '';
    for await (const event of request) {
      if (event.type === 'text_delta') text += event.delta;
      if (text.length > 8192) { await session.cancel(); throw Error('Output budget exceeded'); }
    }
    const completed = await request.result;
    return {text, stop: completed.stopReason};
  }
  const first = await turn('Reply exactly TORQUE_MODEL_OK without using tools.');
  result.text = first.stop === 'end_turn' && first.text.includes('TORQUE_MODEL_OK') && calls === 0;
  if (result.text) {
    phase = 'tool';
    const second = await turn(`Call torque_probe exactly once with nonce ${nonce}, then reply with its confirmation.`);
    result.tool = second.stop === 'end_turn' && calls === 1 && second.text.includes('TORQUE_TOOL_OK');
  }
  result.passed = result.text && result.tool;
  if (!result.passed) result.error = 'Model did not complete the bounded text/tool probe';
} catch (_) {
  result.error = 'Model probe failed or exceeded its request/time/output budget';
} finally {
  clearTimeout(deadlineTimer);
  deadline.abort();
  if (agent) await agent.close().catch(() => {});
  output(result);
}
