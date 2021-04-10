import asyncio
from flask import Flask, request, render_template
import pickle
app = Flask(__name__, template_folder='pages/templates', static_folder='pages/static')


async def communicate_with_ANZTbot(state, code):
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

    result = await reader.read()
    addr = writer.get_extra_info('peername')
    print(f"Received {result!r} from {addr!r}")
    print("Closing connection")
    writer.close()

    result = pickle.loads(result)
    return render_template('index.html', success=result['success'], message=result['message'])


@app.route("/")
def hello():
    state = request.args.get('state')
    code = request.args.get('code')
    if None in [state, code]:
        return render_template('index.html', success=False, message="Incorrect URL arguments")
    try:
        # Using async here is bad practice. A library like https://pypi.org/project/Quart/ would be more suitable.
        return asyncio.run(communicate_with_ANZTbot(state, code))
    except ConnectionRefusedError:
        return render_template('index.html', success=False, message="Couldn't communicate with ANZTbot")


if __name__ == "__main__":
    app.run()
