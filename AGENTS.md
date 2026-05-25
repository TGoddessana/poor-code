# poor-code Agent Guide

## Essential Commands

**Run the application**
```bash
poor-code
```
or
```bash
python -m poor_code
```

**Run tests**
```bash
pytest
```

**Run specific test**
```bash
pytest tests/domain/tool/test_read.py
```

**First-time setup**
1. Run `poor-code` 
2. Type `/login` to configure Ollama Cloud provider
3. Provide API key and model name when prompted

## Project Structure

- `src/poor_code/` - Main application code
  - `cli.py` - Application entrypoint
  - `app.py` - Main Textual application
  - `domain/` - Core domain logic (agent, tools)
  - `provider/` - LLM provider integrations
  - `ui/` - Textual UI components
  - `infra/` - Infrastructure (settings, context loading)
- `tests/` - Test suite organized by module
- `uv.lock` - Dependency lockfile (use `uv sync` for dev setup)

## Development Workflow

1. **Authentication**: Must run `/login` command before agent can function
2. **Testing**: 
   - Unit tests: `pytest tests/domain/`
   - Integration tests: `pytest tests/integration/`
   - Provider tests: `pytest tests/provider/`
3. **Linting**: Not configured - focus on correctness over style
4. **Type checking**: Not configured - uses Python 3.14+ runtime typing

## Important Notes

- The agent requires explicit authentication via `/login` command
- On first run without credentials, uses `NoAuthLLM` which fails with hint to `/login`
- Settings are loaded from `~/.poor-code/settings.json` (global) and `./.poor-code/settings.json` (project)
- Context includes: POORCODE.md (global+project), git status/branch, current date
- History only stores user/assistant/tool messages - system/context is transient per turn
- Test dependencies: pytest, pytest-asyncio, respx, textual-dev
- Built with Textual>=8.2.7 for TUI interface
- Key infrastructure components: SettingsLoader, ContextLoader, SystemPromptComposer, PromptBuilder, TurnAssembler
- DO NOT modify `messages.py` - event names are hardwired in UI store reducer
- Maintain unidirectional dependency: domain/ → ui/ imports forbidden
- Preserve Agent.run() signature: `async def run(self, cmd, cancel) -> AsyncIterator[Event]`
- OllamaChat uses `/api/chat` (native), OpenAIChat uses `/v1/chat/completions`
- Framing uses NdjsonFraming (NDJSON), not SSE
- CLAUDE.md (project root) is the agent's memory reference, POORCODE.md is user-created context
- Current execution is sequential - tool concurrency (Phase 4) is planned but not implemented
- Skills system (Phase 3) is planned for dynamic loading via forked agents
- Branch: feat/first-agent-loop (as of HANDSOFF.md)
- Stack: Python 3.14, Textual, uv