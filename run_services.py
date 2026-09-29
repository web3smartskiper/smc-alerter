"""Restart either service if it exits, and stop both cleanly on shutdown."""
import signal
import subprocess
import sys
import time

stopping = False


def stop(*_):
    global stopping
    stopping = True


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    children = {}
    retry_at = {}
    try:
        while not stopping:
            for script in ('signal_alerter.py', 'forwarder.py'):
                child = children.get(script)
                if child is not None and child.poll() is not None:
                    print(f'{script} exited with {child.returncode}; restarting in 10 seconds', flush=True)
                    children.pop(script)
                    retry_at[script] = time.monotonic() + 10
                if script not in children and time.monotonic() >= retry_at.get(script, 0):
                    children[script] = subprocess.Popen([sys.executable, script])
            time.sleep(1)
    finally:
        for child in children.values():
            if child.poll() is None:
                child.terminate()
        for child in children.values():
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    main()
