# Modular model compatibility

Validated on 2026-10-23 with stock fx 0.0.14 on Linux aarch64, using Modular's
shared endpoint `https://api.modular.com/v1`. These results describe those tests;
server behavior and model availability can change. The preferred default is MiniMax M3.1
Flash, which passed both text and actual shell-tool execution. Setup first reads
the authenticated `/v1/models` catalog and adds only known IDs returned there.
If M3.1 Flash is absent, the default falls back to DeepSeek V4.1 Flash, then
Gemma 4. An explicit `--model` must also be visible. Discovery performs no
inference; the selected model is tested separately.

| Model ID | Context tokens | Text through fx | `uname -m` through fx |
|---|---:|---|---|
| `MiniMaxAI/MiniMax-M3.1-Flash` | 1,048,576 | Passed | Passed |
| `deepseek/deepseek-v4.1-flash` | 1,048,576 | Passed | Passed |
| `google/gemma-4-31b-it` | 262,144 | Passed | Passed |
| `minimax/minimax-m3` | 1,048,576 | Tool-schema HTTP 400 | Blocked by the same schema error |
| `qwen/qwen3.8-27b` | 262,144 | Tool-schema HTTP 400 | Blocked by the same schema error |

A later interactive M3.1 Flash task produced two empty shell argument objects
and failed local validation. This is separate from the HTTP 400 schema errors
below; the basic tool-test pass is not a guarantee for every multi-step task.
See the [tool-call incident journal](journal/2026-10-23-fx-empty-shell-arguments.md)
for evidence, the suggested retry, and the unresolved component root cause.

All five advertise function tools and image input; the metadata records these
capabilities. Image input has not been exercised by this project. Maximum output
limits are omitted because a verified per-endpoint value was not available.

M3 and Qwen both returned successful responses to direct Chat Completions calls
without tools. fx advertises its tools even for a text-only user prompt. M3's
endpoint rejected large string-length bounds in those schemas. Qwen's endpoint
rejected overlapping `oneOf` branches. `tool_choice` omission and non-strict
requests did not resolve the M3 error in the investigation.

The project uses stock fx. No source patch, permission bypass, or alternate
proxy is installed. Choose a passing model rather than patching the client.

On the board, choose a model for one session:

```bash
fx --model deepseek/deepseek-v4.1-flash
```

To save a different default, rerun setup:

```bash
bash setup.sh --model google/gemma-4-31b-it
```

Verification makes small billed requests, preserves permission checks, and
requires a successful `uname -m` tool result, not merely a model's assertion.
`--no-verify` skips inference tests but still performs model discovery. Model
visibility alone does not prove inference access, service health, or fx tool
compatibility. New unknown IDs need verified metadata before automatic setup
will add them. Discovery failure leaves the existing profile unchanged.

Sources:
- [fx custom connections and schema](https://fx.sh/docs/configure-fx/custom-model-connections)
- [Modular quickstart](https://docs.modular.com/quickstart)
- [Modular supported models](https://docs.modular.com/models)
- [Modular function calling](https://docs.modular.com/inference/function-calling)
- [MiniMax M3 native context configuration](https://huggingface.co/MiniMaxAI/MiniMax-M3/blob/main/config.json)

The authenticated Models API and console were also used to confirm exact shared
endpoint IDs. The console is authoritative when its catalog differs from the
public models page. Token counts in `config/models.json` express the advertised
1M/256K model windows; they are not a measured long-context stress test.
