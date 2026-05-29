import subprocess
import os
import signal
import time

p = subprocess.Popen(
    "npx --no-install node node_test.js",
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
)

time.sleep(2)
print("Sending CTRL_BREAK_EVENT")
os.kill(p.pid, signal.CTRL_BREAK_EVENT)

for line in iter(p.stdout.readline, b""):
    if not line: break
    print(line.decode().strip())
