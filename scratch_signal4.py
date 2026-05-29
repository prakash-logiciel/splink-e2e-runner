import subprocess
import os
import signal
import time

p = subprocess.Popen(
    "npx --no-install cross-env node node_test.js",
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    stdin=subprocess.PIPE,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
)

time.sleep(2)
print("Sending CTRL_BREAK_EVENT")
os.kill(p.pid, signal.CTRL_BREAK_EVENT)

try:
    out, err = p.communicate(timeout=5)
    print("out:", out.decode('utf-8', errors='replace'))
    print("err:", err)
except subprocess.TimeoutExpired:
    print("Timeout! It hung. Probably asking Terminate batch job.")
    p.kill()
