"""What exists in Claude Code, so generated advice can be checked against it (UPG-08).

In Phase 7 the team memo recommended a Claude Code feature that does not exist (`.claudedir`).
A memo that mentions a slash command outside this list, or a made-up `.claude...` file, is
treated as invalid output: repaired once, then replaced by the rule-based memo.

Source: the built-in commands and bundled skills table, plus aliases, of
https://code.claude.com/docs/en/commands (read 2026-10-07). Update it when Claude Code adds commands.
"""
import re

KNOWN_COMMANDS = frozenset("""
/add-dir /advisor /agents /artifact-capabilities /artifact-diagramming /artifacts /autocompact /autofix-pr
/auto-mode-setup /background /batch /branch /btw /bug /cd /chrome /claude-api /claude-in-chrome /clear
/code-review /color /compact /config /context /copy /cost /dataviz /debug /deep-research /design
/design-login /design-sync /desktop /diff /doctor /effort /exit /export /fast /feedback
/fewer-permission-prompts /focus /fork /goal /heapdump /help /hooks /ide /import /init /insights
/install-github-app /install-slack-app /keybindings /list-agents /login /logout /loop /mcp /memory /mobile
/model /output-style /passes /permissions /plan /plugin /plugin-authoring /powerup /pr-comments
/privacy-settings /radio /rate-limit-options /recap /release-notes /reload-plugins /reload-skills
/remote-control /remote-env /rename /resume /review /rewind /run /run-skill-generator /sandbox /schedule
/scroll-speed /security-review /setup-bedrock /setup-vertex /simplify /skill-doctor /skills /slides /stats
/status /statusline /stickers /stop /subtask /tasks /team-onboarding /teleport /terminal-setup /theme /tui
/ultraplan /ultrareview /update-config /upgrade /usage /usage-credits /verify /vim /voice /web-setup
/workflow-authoring /workflows
/allowed-tools /android /app /bg /checkpoint /checkup /continue /ios /new /proactive /quit /rc /reset
/routines /settings /share /undo
""".split())

# The commands a cost-efficiency memo is expected to use, named in the prompt.
COST_COMMANDS = ("/compact", "/clear", "/context", "/model", "/usage")

# A slash command as written in prose: not part of a path, URL or a rate like "$13/day".
_COMMAND = re.compile(r"(?<![\w/.$%:])/[a-z][a-z0-9-]*\b")
# A made-up Claude config file such as ".claudedir" or ".clauderc" (".claude/" and CLAUDE.md are real).
_INVENTED_FILE = re.compile(r"\.claude[a-z0-9_-]+", re.IGNORECASE)


def unknown_commands(text):
    """Slash commands in `text` that Claude Code does not have."""
    return sorted({c for c in _COMMAND.findall(text) if c not in KNOWN_COMMANDS})


def invented_files(text):
    return sorted({f.lower() for f in _INVENTED_FILE.findall(text)})
