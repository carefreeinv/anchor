# OpenAI-compatible chat completion fixtures

Recorded shapes for thinking locals (Qwen3 via Ollama OpenAI `/v1/chat/completions`).

Live capture notes (2026-09-06): with `max_tokens` 32–64, Ollama returned
`content=""`, populated `message.reasoning`, `finish_reason=length`. With
`max_tokens` ≥ 256, `content` eventually held the answer. Native `/api/chat`
`think:false` on that build still put “thinking” into `content` (unreliable).
Ollama was not reachable during the unit-test run that landed these fixtures.
