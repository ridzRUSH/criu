from flask import Flask, jsonify
import os, time, uuid

app = Flask(__name__)

counter = 0
started_at = time.time()
boot_id = uuid.uuid4().hex

@app.route("/")
def increment():
    global counter
    counter += 1
    print(f"COUNTER = {counter}", flush=True)
    return jsonify(counter=counter, boot_id=boot_id, pid=os.getpid(), host=os.uname().nodename)

@app.route("/peek")
def peek():
    return jsonify(counter=counter, boot_id=boot_id, pid=os.getpid(), host=os.uname().nodename,
                   uptime_s=round(time.time() - started_at, 1))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=False)
