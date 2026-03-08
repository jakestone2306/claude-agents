import os
from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

def run_agent(user_message: str):
    """Run a simple Claude agent."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system="You are a helpful AI agent. Complete tasks clearly and concisely.",
        messages=[{"role": "user", "content": user_message}]
    )
    return response.content[0].text

if __name__ == "__main__":
    print(run_agent("Hello! Confirm you are running correctly."))
