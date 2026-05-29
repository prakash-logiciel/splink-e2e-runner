import subprocess
import os
import signal
import time

p = subprocess.Popen(
    "npx -v",
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
)

time.sleep(2)
print("Sending CTRL_BREAK_EVENT")
os.kill(p.pid, signal.CTRL_BREAK_EVENT)

out, err = p.communicate()
print("out:", out)
print("err:", err)
