from discord.ext import commands
import asyncio
import aiohttp
import pickle
from cryptography.fernet import Fernet, InvalidToken
from settings import key, osu_app_client_id, osu_app_client_secret, redirect_url


class TourneyRegisterCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    @commands.command()
    async def register(self, ctx):
        # We encrypt the user's discord id so we can ensure the user can't generate an OAuth url that would link to another user's discord account
        # And also so we can tell which discord account started the OAuth process
        discord_id = str(ctx.author.id)
        discord_id_enc = Fernet(key).encrypt(discord_id.encode())
        oauth_url = f'https://osu.ppy.sh/oauth/authorize?client_id={osu_app_client_id}&response_type=code&redirect_uri={redirect_url}&state={discord_id_enc.decode()}'
        await ctx.send(f'Register via {oauth_url}')

    async def handler(self, reader, writer):
        data = await reader.read()
        data = pickle.loads(data)
        addr = writer.get_extra_info('peername')
        print(f"Received {data!r} from {addr!r}")

        # See https://osu.ppy.sh/docs/index.html?bash#authorization-code-grant to see what the rest of this method is doing.
        code = data['code']
        state = data['state']
        try:
            state = Fernet(key).decrypt(state.encode()).decode()
        except InvalidToken:
            print('token is bad')
            return

        print(f'Using one-time code to get authorization token')
        data = {
            'client_id': osu_app_client_id,
            'client_secret': osu_app_client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_url
        }
        # There's duplicate code here but idk how to elegantly fix that
        async with self.session.post('https://osu.ppy.sh/oauth/token', data=data) as r:
            if r.status != 200:
                print('failed to get authorization token')
                return
            json = await r.json()
            access_token = json['access_token']

        print('Got access token, using token to get user info')
        headers = {'Authorization': f'Bearer {access_token}'}
        async with self.session.get('https://osu.ppy.sh/api/v2/me/osu', headers=headers) as r:
            if r.status != 200:
                print('failed to get user info')
                return
            json = await r.json()
            user_id = json['id']
        print(f'osu! UserID: {user_id}')
        print(f'Discord UserID: {state}')
        print("Close the connection")
        writer.close()

    @commands.Cog.listener()
    async def on_ready(self):
        # Wait for error cog to be ready
        await asyncio.sleep(1)

        server = await asyncio.start_server(self.handler, '127.0.0.1', 7865)
        addr = server.sockets[0].getsockname()
        print(f'Serving on {addr}')
        async with server:
            await server.serve_forever()


def setup(bot):
    bot.add_cog(TourneyRegisterCog(bot))
