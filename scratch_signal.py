import subprocess
import os
import signal
import time

p = subprocess.Popen(
    "node -e \"setInterval(() => console.log('running...'), 1000); process.on('SIGBREAK', () => { console.log('got SIGBREAK'); setTimeout(()=>process.exit(0), 1000); }); process.on('SIGINT', () => { console.log('got SIGINT'); setTimeout(()=>process.exit(0), 1000); });\"",
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
