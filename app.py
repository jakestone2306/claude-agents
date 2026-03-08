import os
from flask import Flask, request, jsonify
from pipeline_risk_agent import run

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "agent": "Pipeline Risk Agent"})

@app.route("/run", methods=["POST"])
def run_agent():
    try:
        run()
        return jsonify({"status": "success", "message": "Pipeline risk analysis complete"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
