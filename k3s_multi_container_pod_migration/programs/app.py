from flask import Flask, jsonify
import uuid, redis

app = Flask(__name__)
counter = 0
boot_id = uuid.uuid4().hex

def connect():
    return redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)

# Open and close Redis per request: no TCP connection stays open at checkpoint time.
@app.route("/")
def increment():
    global counter
    counter += 1
    r = connect()
    try:
        hits = r.incr("hits")
        r.rpush("log", f"req-{counter}")
    finally:
        r.connection_pool.disconnect()
    return jsonify(counter=counter, redis_hits=hits, boot_id=boot_id)

@app.route("/peek")
def peek():
    r = connect()
    try:
        hits = int(r.get("hits") or 0)
        log_len = r.llen("log")
    finally:
        r.connection_pool.disconnect()
    return jsonify(counter=counter, redis_hits=hits, redis_log_len=log_len, boot_id=boot_id)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=False)
