"""The program's entry point: main.py imports this file when the Pico powers up.

main.py can only be replaced over the cable (ota.py), which is why the name is still "escuta". Since
2026-10-29 the amp's display has been desoldered at pins 4..14 and the program is the proxy
(proxy.py, docs/proxy-ligacao.md). The old listener, with the display wired straight to the
controller and uncut writing (escrita.py, plano.py, refresh.py), is in the
git history (commit 45e782c).
"""

import proxy                            # noqa: F401  (the program runs when imported)
