from discord.ext import commands
from discord import Embed, User
import asyncio
import aiohttp
import pickle
import asyncpg
from cryptography.fernet import Fernet, InvalidToken
from settings import *


class TourneySignupCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    def cog_unload(self):
        loop = self.bot.loop
        loop.create_task(self.connpool.close())
        loop.create_task(self.session.close())

    @commands.command()
    async def register(self, ctx):
        await self.prompt_user(ctx.author)

    async def generate_oauth_url(self, user_id: int):
        user_id = str(user_id).encode()
        user_id_enc = Fernet(key).encrypt(user_id)
        return (
            f'https://osu.ppy.sh/oauth/authorize?'
            f'client_id={osu_app_client_id}&'
            f'response_type=code&'
            f'redirect_uri={redirect_url}&'
            f'state={user_id_enc.decode()}'
        )

    async def prompt_user(self, user: User):
        oauth_url = await self.generate_oauth_url(user.id)
        colour = 0xf5a623

        embed = Embed(title="Click here to register for ANZT8W", colour=colour, url=oauth_url)
        embed.set_footer(text=f"This link is unique to you - Registrations close {signup_close_date}")
        await user.send(embed=embed)

        embed = Embed(colour=colour,
                      description="```fix\nYou will be prompted to log in on the official osu! site.\n\n"
                                  "This lets us confirm you are the owner of these Discord and osu! accounts.```"
                                  "*[Forum Post](https://osu.ppy.sh/community/forums/topics/1204722) - "
                                  "[Source](https://github.com/JWWolstenholme/ANZTBot) - by Diony*")
        await user.send(embed=embed)

    async def write(self, writer, string):
        writer.write(string.encode())
        writer.write_eof()
        await writer.drain()

    async def handler(self, reader, writer):
        try:
            await self.handle(reader, writer)
        except Exception:
            errorcog = self.bot.get_cog('ErrorReportingCog')
            await errorcog.on_error('anzt.signup.handle')
            await self.write(writer, 'There was an unexpected error. Diony will fix it asap.')
        finally:
            writer.close()

    async def handle(self, reader, writer):
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
            await self.write(writer, "'State' parameter is bad: try asking ANZT bot for another link.")
            return

        signed_up_already = await self.check_if_registered(state)
        if signed_up_already:
            await self.write(writer, "You're already signed up!")
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
                await self.write(writer, "Failed to communicate with osu! servers. Maybe they're down atm?")
                return
            json = await r.json()
            access_token = json['access_token']

        print('Got access token, using token to get user info')
        headers = {'Authorization': f'Bearer {access_token}'}
        async with self.session.get('https://osu.ppy.sh/api/v2/me/osu', headers=headers) as r:
            if r.status != 200:
                print('failed to get user info')
                await self.write(writer, "Failed to communicate with osu! servers. Maybe they're down atm?")
                return
            json = await r.json()
            user_id = json['id']
        print(f'osu! UserID: {user_id}')
        print(f'Discord UserID: {state}')
        await self.persist_signup(state, user_id)
        await self.write(writer, "You're now registered!")
        print("Close the connection")
        writer.close()

    async def check_if_registered(self, discord_id):
        async with self.connpool.acquire() as conn:
            async with conn.transaction():
                result = await conn.fetchrow('''select discord_id from signups where discord_id=$1''', discord_id)
                return bool(result)

    async def persist_signup(self, discord_id, osu_id):
        async with self.connpool.acquire() as conn:
            async with conn.transaction():
                await conn.execute('''insert into signups values ($1, $2)''', discord_id, osu_id)

    @commands.Cog.listener()
    async def on_ready(self):
        # Wait for error cog to be ready
        await asyncio.sleep(1)
        self.connpool = await asyncpg.create_pool(database=dbname, user=dbuser, password=dbpass, host=dbhost, port=dbport)

        server = await asyncio.start_server(self.handler, '127.0.0.1', 7865)
        addr = server.sockets[0].getsockname()
        print(f'Serving on {addr}')
        async with server:
            await server.serve_forever()


def setup(bot):
    bot.add_cog(TourneySignupCog(bot))
