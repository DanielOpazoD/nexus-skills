"""Detiene el descargador si desaparece su lanzador; conserva el checkpoint."""
import os
from pathlib import Path
import runpy
import signal
import sys
import threading
import time

if __name__ == '__main__':
    parent = int(sys.argv[1])
    target = Path(sys.argv[2]).resolve()
    sys.argv = [str(target), *sys.argv[3:]]
    sys.path.insert(0, str(target.parent))
    def watch_parent():
        while True:
            time.sleep(.5)
            if os.getppid() != parent:
                os.kill(os.getpid(), signal.SIGINT)
                return
    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        if os.getppid() != parent: raise KeyboardInterrupt()
        runpy.run_path(str(target), run_name='__main__')
    except KeyboardInterrupt:
        print('Interrumpido; avance conservado.', file=sys.stderr)
        sys.exit(130)
