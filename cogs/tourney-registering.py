from discord.ext import commands
import asyncio
import aiohttp
import pickle
from cryptography.fernet import Fernet, InvalidToken


class TourneyRegisterCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.key = Fernet.generate_key()

    @commands.command()
    async def register(self, ctx):
        discord_id = str(ctx.author.id)
        discord_id_enc = Fernet(self.key).encrypt(discord_id.encode())
        oauth_url = f'https://osu.ppy.sh/oauth/authorize?client_id=2870&response_type=code&redirect_uri=http://osuanzt.com/register/&state={discord_id_enc.decode()}'
        await ctx.send(f'Register via {oauth_url}')

    async def handler(self, reader, writer):
        data = await reader.read()
        data = pickle.loads(data)
        addr = writer.get_extra_info('peername')
        print(f"Received {data!r} from {addr!r}")

        code = data['code']
        state = data['state']
        try:
            state = Fernet(self.key).decrypt(state.encode()).decode()
        except InvalidToken:
            print('token is bad')
            return

        print(f'Using one-time code to get authorization token')
        data = {
            'client_id': 2870,
            'client_secret': 'LwVcOqPiRkfngFwVjAXMSlyfViwQzViAZL0h9Aff',
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': 'http://osuanzt.com/register/'
        }
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
        await asyncio.sleep(2)

        # self.dioguild = self.bot.get_guild(255990138289651713)
        # self.diochannel = self.dioguild.get_channel(610482665573056512)
        # self.diony = (await self.dioguild.query_members(user_ids=[81316514216554496]))[0].mention

        server = await asyncio.start_server(self.handler, '127.0.0.1', 7865)
        addr = server.sockets[0].getsockname()
        print(f'Serving on {addr}')
        async with server:
            await server.serve_forever()


def setup(bot):
    bot.add_cog(TourneyRegisterCog(bot))
