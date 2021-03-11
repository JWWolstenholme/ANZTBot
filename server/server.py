import asyncio
from flask import Flask, request
import pickle
app = Flask(__name__)


async def send_back_to_discord_bot(state, code):
    reader, writer = await asyncio.open_connection(
        "127.0.0.1", 7865)

    print(f"Sending state & code")
    data = {
        'state': state,
        'code': code
    }
    writer.write(pickle.dumps(data))

    print("Closing connection")
    writer.close()


@app.route("/")
def hello():
    state = request.args.get('state')
    code = request.args.get('code')
    if None in [state, code]:
        return "Incorrect arguments"
    try:
        asyncio.run(send_back_to_discord_bot(state, code))
    except ConnectionRefusedError:
        return "Couldn't communicate with discord bot"
    else:
        return "Process worked"


if __name__ == "__main__":
    app.run()
