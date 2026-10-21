"""One synthetic call per model tier, to check AI configuration: ``python -m app.ai.smoke``.

Sends no organisation data. Prints the provider, model version and token counts only.
"""

from __future__ import annotations

import sys

from app import ai
from app.config import get_settings

SYSTEM = "You are a configuration check. Reply with one JSON object and nothing else."
PROMPT = 'Return exactly {"ok": true}.'


def main() -> int:
    s = get_settings()
    if not s.ai_enabled or s.ai_provider == "disabled":
        print("AI is disabled (AI_ENABLED / AI_PROVIDER).")
        return 1
    failed = False
    for tier in ("fast", "reasoning"):
        try:
            c = ai.get_provider(s, tier).complete(SYSTEM, PROMPT, max_tokens=50)
        except Exception as exc:  # report the class and safe message only
            print(f"{tier}: FAILED ({type(exc).__name__}: {exc})")
            failed = True
            continue
        ok = '"ok"' in c.text
        print(
            f"{tier}: {'ok' if ok else 'unexpected answer'} · {c.provider} · "
            f"{c.model_version or c.model} · tokens in/out {c.input_tokens}/{c.output_tokens}"
        )
        failed = failed or not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
