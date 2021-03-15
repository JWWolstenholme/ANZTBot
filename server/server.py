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
    writer.write_eof()
    await writer.drain()

    result = (await reader.read()).decode()
    addr = writer.get_extra_info('peername')
    print(f"Received {result!r} from {addr!r}")
    print("Closing connection")
    writer.close()
    return result


@app.route("/")
def hello():
    state = request.args.get('state')
    code = request.args.get('code')
    if None in [state, code]:
        return "Incorrect arguments"
    try:
        result = asyncio.run(send_back_to_discord_bot(state, code))
        return result
    except ConnectionRefusedError:
        return "Couldn't communicate with discord bot"


if __name__ == "__main__":
    app.run()
