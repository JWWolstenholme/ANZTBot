from quart import Quart, request, render_template

app = Quart(__name__, template_folder='pages/templates', static_folder='pages/static')

# Reference to the signup handler, set by the tourney-signup cog
_signup_handler = None


def set_signup_handler(handler):
    global _signup_handler
    _signup_handler = handler


@app.route("/")
async def hello():
    state = request.args.get('state')
    code = request.args.get('code')
    if None in [state, code]:
        return await render_template('index.html', success=False, message="Incorrect URL arguments")
    
    if _signup_handler is None:
        return await render_template('index.html', success=False, message="Signup handler not initialized")
    
    try:
        # Pass the state & code to the bot to process and display result
        result = await _signup_handler(state, code)
        return await render_template('index.html', success=result['success'], message=result['message'])
    except Exception as e:
        print(f"Error in signup handler: {e}")
        return await render_template('index.html', success=False, message="An error occurred during signup")
