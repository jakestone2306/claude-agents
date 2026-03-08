import os
from flask import Flask, request, jsonify
from main import run_agent

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "Claude Agent is running!"})

@app.route("/run", methods=["POST"])
def run():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' in request body"}), 400
    result = run_agent(data["message"])
    return jsonify({"response": result})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
