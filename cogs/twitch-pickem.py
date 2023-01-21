import asyncio
from datetime import datetime, timedelta
from requests.api import get

import twitch
from discord import Embed, Streaming
from discord.ext import commands, tasks
from utility_funcs import is_channel, get_setting


class TwitchAndPickemsCog(commands.Cog):
    delete_delay = 10
    last_ping = datetime.fromisoformat('2011-11-04T00:05:23')

    def __init__(self, bot):
        self.bot = bot
        setts = get_setting("twitch")
        self.client = twitch.TwitchHelix(client_id=setts["client_id"],
                                         client_secret=setts["client_secret"],
                                         scopes=[twitch.constants.OAUTH_SCOPE_ANALYTICS_READ_EXTENSIONS])
        self.check_if_live.start()

    def cog_unload(self):
        self.check_if_live.cancel()

    async def cog_before_invoke(self, ctx):
        await ctx.message.channel.typing()

    @tasks.loop(seconds=22)
    async def check_if_live(self):
        should_check = get_setting("twitch", "active")
        if should_check != "Y":
            return

        twitchannel = get_setting("twitch", "twitch_channel")

        try:
            if not self.bot.is_ready():
                await self.bot.wait_until_ready()
                # Give the error reporting cog some time to do what's in it's on_ready listener before it's ready to handle errors
                await asyncio.sleep(1)
            self.client.get_oauth()
            data = self.client.get_streams(user_logins=[twitchannel])
            live = str(data) != '[]'
            if live:
                data = data[0]
                # Set bot's activity accordingly
                title = data['title']
                title = title if title != '' else 'with no title'
                activity = Streaming(name=title, url=f'https://www.twitch.tv/{twitchannel}', platform='Twitch')

                # Determine if we should ping people based on our last saved stream start time
                stream_start = data['started_at']
                with open('last_stream_start.txt', 'r') as f:
                    last_stream_start = datetime.fromisoformat(f.read())

                if last_stream_start < stream_start:
                    with open('last_stream_start.txt', 'w') as f:
                        f.write(str(stream_start))

                    if self.last_ping + timedelta(minutes=30) < stream_start:
                        await self.do_stream_ping(data)
                    self.last_ping = stream_start
            else:
                activity = None
            await self.bot.change_presence(activity=activity)
        except ConnectionResetError:
            pass
        except Exception:
            errorcog = self.bot.get_cog('ErrorReportingCog')
            await errorcog.on_error('anzt.twitch.loop')

    async def do_stream_ping(self, data):
        url = f'https://www.twitch.tv/{data["user_name"]}'
        embed = Embed(title=f'**{data["title"]}**', url=url, color=0x9146ff)
        embed.set_author(name=f'{data["user_name"]} is live!',
                         url=url, icon_url='https://www.iconsdb.com/icons/preview/red/circle-xxl.png')
        # embed.set_thumbnail(url='https://i.imgur.com/XbO4hoK.png')
        embed.set_image(url='https://static-cdn.jtvnw.net/previews-ttv/live_user_osuanzt-960x540.jpg')

        anzt = self.bot.get_guild(199158455888642048)
        anzt_channel = anzt.get_channel(945236506547728414)
        pingrole = [role for role in anzt.roles if role.name == 'Stream Ping'][0]
        pingrole = await pingrole.edit(mentionable=True)
        await anzt_channel.send(f'{pingrole.mention}', embed=embed)
        await pingrole.edit(mentionable=False)

    @commands.command()
    @is_channel('bot')
    async def pickemping(self, ctx):
        await self.toggle_role(ctx, 'Pickem Ping')

    @commands.command()
    @is_channel('bot')
    async def streamping(self, ctx):
        await self.toggle_role(ctx, 'Stream Ping')

    async def toggle_role(self, ctx, rolename):
        pingrole = [role for role in ctx.guild.roles if role.name == rolename][0]
        if pingrole in ctx.author.roles:
            await ctx.author.remove_roles(pingrole)
            await ctx.send(f'{ctx.author.mention}, Removed your `{rolename}` role.')
        else:
            await ctx.author.add_roles(pingrole)
            await ctx.send(f'{ctx.author.mention}, Gave you the `{rolename}` role.')


async def setup(bot):
    await bot.add_cog(TwitchAndPickemsCog(bot))
