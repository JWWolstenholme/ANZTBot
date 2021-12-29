import asyncio
import pickle
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from discord import Embed, File, User
from discord.errors import Forbidden
from discord.ext import commands
from discord.ext.commands.converter import MessageConverter
from discord.ext.commands.errors import MessageNotFound
from gspread.exceptions import APIError
from utility_funcs import get_setting, get_exposed_settings, request, res_cog


class TourneySignupCog(commands.Cog):
    delete_delay = 10

    def __init__(self, bot):
        self.bot = bot
        self.prompted_users = []

    async def _connpool(self):
        return await res_cog(self.bot).connpool()

    @commands.Cog.listener()
    async def on_message(self, message):
        '''Deletes unnecessary messages in the registration channel'''
        if message.author == self.bot.user:
            return
        if message.channel.name in ['register']:
            if message.content != '!register':
                await message.delete()
                return

    @commands.command()
    async def register(self, ctx):
        # If user was prompted.
        if await self.prompt_user(ctx.author):
            await ctx.message.add_reaction('✅')
        else:
            await ctx.message.add_reaction('❌')
            await ctx.send(f'{ctx.author.mention} I\'ve already sent you a dm', delete_after=10)
        await asyncio.sleep(10)
        await ctx.message.delete()

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def clearcache(self, ctx):
        self.prompted_users = []
        await ctx.message.delete()

    async def user_prompted(self, user_id):
        return user_id in self.prompted_users

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if self.watch_message_id is None:
            return
        if payload.message_id != self.watch_message_id:
            return
        await self.prompt_user(payload.member)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def watch(self, ctx, message):
        await ctx.trigger_typing()
        await ctx.message.delete()

        try:
            message = await MessageConverter().convert(ctx, message)
        except MessageNotFound:
            await ctx.send("Couldn't find a message with what you provided.", delete_after=self.delete_delay)
            return

        # Save to the database
        async with (await self._connpool()).acquire() as conn:
            async with conn.transaction():
                # We store the message id (which is unique per channel) and check it against reactions in all channels
                # so there could be false postives with messages from other channels.
                # I do this because I don't know how to convert a full message link url to a message without a context.
                await conn.execute('''update settings set watch_message_link = $1;''', message.id)

        self.watch_message_id = message.id
        await ctx.send(f'{ctx.author.mention} Now watching that message.', delete_after=self.delete_delay)

    async def load_from_settings(self):
        async with (await self._connpool()).acquire() as conn:
            async with conn.transaction():
                record = await conn.fetchrow('select * from settings')
                self.watch_message_id = record['watch_message_link']

    async def generate_oauth_url(self, user_id: int, settings):
        user_id = str(user_id).encode()
        user_id_enc = Fernet(settings["key"].encode()).encrypt(user_id)
        return (
            f'https://osu.ppy.sh/oauth/authorize?'
            f'client_id={settings["osu_app_client_id"]}&'
            f'response_type=code&'
            f'redirect_uri={settings["redirect_url"]}&'
            f'state={user_id_enc.decode()}'
        )

    async def prompt_user(self, user: User):
        '''Returns a boolean indicating if the user has been prompted or not'''
        if await self.user_prompted(user.id):
            return False

        setts = get_setting("tourney-signup")
        oauth_url = await self.generate_oauth_url(user.id, setts)
        colour = 0xf5a623

        embed = Embed(title=f"Click here to register for {setts['exposed_settings']['acronym']}", colour=colour, url=oauth_url)
        embed.set_footer(text=f"This link is unique to you - Registrations close {setts['exposed_settings']['signup_close_date']}")

        try:
            await user.send(embed=embed)
        except Forbidden:
            anztguild = self.bot.get_guild(199158455888642048)
            botchannel = anztguild.get_channel(681098070393487409)
            embed = Embed(colour=0xFF253F, url='https://support.discord.com/hc/en-us/articles/217916488-Blocking-Privacy-Settings-',
                          description='You have private messages disabled so I couldn\'t give you your signup link.\n'
                          'You can enable them in the settings under: ```Privacy & Safety > Allow direct messages from server members```'
                          'Then try to register again. You can then disable the setting again.')
            await botchannel.send(f'{user.mention}', embed=embed)
            return False

        embed = Embed(colour=colour,
                      description="```fix\nYou will be prompted to log in on the official osu! site.\n\n"
                                  "This lets us confirm you are the owner of these Discord and osu! accounts.```"
                                  f"*[Forum Post]({setts['exposed_settings']['forum_post_url']}) - "
                                  "[Source](https://github.com/JWWolstenholme/ANZTBot) - by Diony*")
        await user.send(embed=embed)
        self.prompted_users.append(user.id)
        return True

    async def write(self, writer, success: bool, message: str):
        data = {
            'success': success,
            'message': message
        }
        writer.write(pickle.dumps(data))
        writer.write_eof()
        await writer.drain()

    async def handler(self, reader, writer):
        try:
            await self.handle(reader, writer)
        except Exception:
            errorcog = self.bot.get_cog('ErrorReportingCog')
            await errorcog.on_error('anzt.signup.handle')
            await self.write(writer, False, 'There was an error. Diony will fix it asap.')
        finally:
            writer.close()

    async def handle(self, reader, writer):
        data = await reader.read()
        data = pickle.loads(data)
        addr = writer.get_extra_info('peername')
        print(f"Received {data!r} from {addr!r}")

        session = await res_cog(self.bot).session()
        setts = get_setting("tourney-signup")

        # See https://osu.ppy.sh/docs/index.html?bash#authorization-code-grant to see what the rest of this method is doing.
        code = data['code']
        state = data['state']
        try:
            state = Fernet(setts["key"].encode()).decrypt(state.encode()).decode()
        except InvalidToken:
            await self.write(writer, False, "'State' parameter is bad: try asking ANZT bot for another link.")
            return

        if await self.check_if_registered(state):
            await self.write(writer, False, "You're already signed up!")
            return

        print(f'Using one-time code to get authorization token')
        data = {
            'client_id': setts["osu_app_client_id"],
            'client_secret': setts["osu_app_client_secret"],
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': setts["redirect_url"]
        }
        # There's duplicate code here but idk how to elegantly fix that
        async with session.post('https://osu.ppy.sh/oauth/token', data=data) as r:
            if r.status != 200:
                print('failed to get authorization token')
                await self.write(writer, False, "Failed to reach osu! servers. Maybe they're down?")
                return
            json = await r.json()
            access_token = json['access_token']

        print('Got access token, using token to get user info')
        headers = {'Authorization': f'Bearer {access_token}'}
        async with session.get('https://osu.ppy.sh/api/v2/me/osu', headers=headers) as r:
            if r.status != 200:
                print('failed to get user info')
                await self.write(writer, False, "Failed to reach osu! servers. Maybe they're down?")
                return
            json = await r.json()
            user_country = json['country_code']
            user_id = json['id']
        if user_country not in setts["allowed_countries"]:
            print('user rejected due to their flag')
            await self.write(writer, False, 'You need an Australian or New Zealand flag on your profile!')
            return
        print(f'osu! UserID: {user_id}')
        print(f'Discord UserID: {state}')
        await self.persist_signup(state, user_id)
        await self.write(writer, True, "You're now registered!")
        print("Close the connection")
        writer.close()

    async def check_if_registered(self, discord_id):
        async with (await self._connpool()).acquire() as conn:
            async with conn.transaction():
                result = await conn.fetchrow('''select discord_id from signups where discord_id=$1''', discord_id)
                return bool(result)

    async def persist_signup(self, discord_id, osu_id):
        # Persist in database
        async with (await self._connpool()).acquire() as conn:
            async with conn.transaction():
                await conn.execute('''insert into signups values ($1, $2)''', discord_id, osu_id)

        # Persist in spreadsheet
        setts = get_exposed_settings("tourney-signup")
        agc = await res_cog(self.bot).agc()
        try:
            sh = await agc.open_by_url(setts["sheet_url"])
        except APIError as e:
            if e.args[0]['status'] == 'PERMISSION_DENIED':
                print('no perms. share with anzt-bot@anzt-bot.iam.gserviceaccount.com')
            return
        ws = await sh.worksheet(setts["sheet_tab_name"])

        disc_user = self.bot.get_user(int(discord_id))

        apiKey = get_setting('osu', 'apikey')
        json = await request(f'https://osu.ppy.sh/api/get_user?k={apiKey}&u={osu_id}&type=id&m=0', self.bot)
        json = json[0]
        osu_username = json['username']
        rank = json['pp_rank']
        country = json['country']

        await ws.append_row([datetime.now().strftime('%d/%m/%Y %H:%M:%S'), discord_id, str(disc_user), disc_user.display_name, osu_id, osu_username, rank, country])

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def csv(self, ctx):
        await ctx.message.delete()

        filename = 'signups.csv'
        async with (await self._connpool()).acquire() as conn:
            async with conn.transaction():
                await conn.copy_from_query('select * from signups', output=filename, format='csv', header=True)
        with open(filename, 'rb') as fp:
            await ctx.send(file=File(fp, filename))

    @commands.Cog.listener()
    async def on_ready(self):
        # Wait for error cog to be ready
        await asyncio.sleep(5)
        await self.load_from_settings()

        server = await asyncio.start_server(self.handler, '127.0.0.1', 7865)
        addr = server.sockets[0].getsockname()
        print(f'Serving on {addr}')
        async with server:
            await server.serve_forever()


def setup(bot):
    bot.add_cog(TourneySignupCog(bot))
