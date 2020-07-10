import asyncio
import os
import re
import sys
import traceback
import typing
from datetime import date, datetime, timedelta
from functools import wraps
from io import StringIO

import aiohttp
import asyncpg
import discord
import gspread_asyncio
import inflect
import pyrfc3339
import pytz
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
from gspread.exceptions import CellNotFound
from oauth2client.service_account import ServiceAccountCredentials
from pytz import timezone
from tzlocal import get_localzone

from settings import *

bot = commands.Bot(command_prefix='!')
infeng = inflect.engine()

# Regex
osu_mp_url = re.compile(r'((https://osu.ppy.sh/community/matches/)|(https://osu.ppy.sh/mp/))(?P<id>[0-9]+)')
ban_format = re.compile(r'(nm|hd|hr|dt|fm)[0-9]', re.IGNORECASE)
# match_id_format = re.compile(r'^([A-D]|[a-d])[0-9]+$')
match_id_format = re.compile(r'^[0-9]+$')

# Caches
userIDs_to_usernames = {}
bmapIDs_to_json = {}
last_ping = None

# Postgres connection pool
connpool = bot.loop.run_until_complete(asyncpg.create_pool(database=dbname, user=dbuser, password=dbpass, host=dbhost, port=dbport))


# Converter methods
def url_to_id(url: str) -> int:
    match = re.search(osu_mp_url, url)
    if match:
        return int(match.group('id'))
    else:
        raise SyntaxError("\"{}\" is not a valid mp link".format(url))


def to_ban(ban: str) -> str:
    if not re.match(ban_format, ban):
        raise SyntaxError("\"{}\" is not a valid ban".format(ban))
    return ban


def to_id(id: str) -> str:
    if re.match(match_id_format, id):
        return id
    raise SyntaxError(f"\"{id}\" is not a valid match id")


# Decorater methods
def send_typing(f):
    @wraps(f)
    async def wrapped(*args):
        if args[0].__class__ == discord.ext.commands.Context:
            async with args[0].typing():
                return await f(*args)
        elif args[0].__class__ == discord.Message:
            async with args[0].channel.typing():
                return await f(*args)
    return wrapped


# Checks
def is_channel(*args: str):
    async def predicate(ctx):
        return ctx.message.channel.name in args
    return commands.check(predicate)


def is_bot(message):
    return message.author.bot


def is_webhook(message):
    return message.webhook_id is not None


def is_staff():
    async def predicate(ctx):
        discord_id = ctx.author.id
        async with connpool.acquire() as conn:
            async with conn.transaction():
                staff = await conn.fetchrow('''SELECT * FROM staff where staff_discord_id=$1''', discord_id)
                if staff is None:
                    await ctx.message.delete()
                    await ctx.send(f'{ctx.author.mention} You need to be staff to use that command', delete_after=10)
                    return False
                return True
    return commands.check(predicate)


# Event listeners
@bot.event
async def on_ready():
    print('Logged in as ' + bot.user.name)
    # bot.loop.create_task(check_if_live(twitchannel))
    global last_ping
    with open('last_ping.txt', 'r') as f:
        last_ping = datetime.fromisoformat(f.read())
    bot.remove_command('help')


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.name in ['results', 'referee']:
        if re.match(match_id_format, message.content):
            await format(message)
    # Don't allow messages in #qualifiers that aren't commands
    if message.channel.name in ['qualifiers']:
        context = await bot.get_context(message)
        if not context.valid:
            await message.delete()
            await message.channel.send(f'{message.author.mention} please only use commands like `!lobby #` here', delete_after=5)
    await bot.process_commands(message)


# Background tasks
async def check_if_live(user_login):
    while True:
        try:
            jsonresp = await request(f'https://api.twitch.tv/helix/streams?user_login={user_login}', {"Client-ID": clientID})
            # Change presence when live
            live = jsonresp['data'] != []
            if live:
                title = jsonresp['data'][0]['title']
                title = title if title != '' else 'with no title'
                activity = discord.Streaming(name=title,
                                             url=f'https://www.twitch.tv/{user_login}', platform='Twitch')
            else:
                activity = None
            await bot.change_presence(activity=activity)
            # Ping stream announce role
            if live:
                stream_start = pyrfc3339.parse(jsonresp['data'][0]['started_at'])
                global last_ping
                if last_ping < stream_start:
                    with open('last_ping.txt', 'w') as f:
                        f.write(str(stream_start))
                    last_ping = stream_start

                    # Do the ping
                    try:
                        anzt = bot.get_guild(199158455888642048)
                        embed = discord.Embed(title=f'**https://www.twitch.tv/{user_login}**', description=title, color=0x9146ff)
                        embed.set_author(name=f'{user_login} is live!',
                                         url=f'https://www.twitch.tv/{user_login}', icon_url='https://www.iconsdb.com/icons/preview/red/circle-xxl.png')
                        embed.set_thumbnail(url='https://i.imgur.com/XbO4hoK.png')

                        pingrole = [role for role in anzt.roles if role.name == 'Stream Ping'][0]
                        await pingrole.edit(mentionable=True)
                        await anzt.system_channel.send(f'{pingrole.mention}', embed=embed)
                        await pingrole.edit(mentionable=False)
                    except (IndexError, AttributeError):
                        continue
        # This catches timeouts when I run this on my shitty internet
        except aiohttp.client_exceptions.ClientConnectorError:
            pass
        except Exception as error:
            await error_handler(error)
        await asyncio.sleep(30)


# Error handlers
@bot.event
async def on_command_error(ctx, error):
    # Ignore commands that don't exist
    if error.__class__ == discord.ext.commands.CommandNotFound:
        return
    if error.__class__ == discord.ext.commands.CommandOnCooldown:
        await ctx.message.delete()
        await ctx.send(f'{ctx.author.mention} That command is on cooldown. Try again in {error.retry_after:.2f}s', delete_after=7)
        return
    if error.__class__ == discord.ext.commands.CheckFailure:
        return
    if error.__class__ == discord.ext.commands.BadArgument:
        await ctx.message.delete()
        await ctx.send(f'{ctx.author.mention} There was something wrong with your command arguments', delete_after=7)
        return
    if error.__class__ == discord.ext.commands.MissingRequiredArgument:
        await ctx.message.delete()
        await ctx.send(f'{ctx.author.mention} You\'re missing at least one argument', delete_after=7)
        return
    await error_handler(error, ctx)


@bot.event
async def on_error(event, message=None):
    await error_handler(message=message)


async def error_handler(error=None, ctx=None, message=None):
    # Report to Diony
    dioguild = bot.get_guild(255990138289651713)
    diochannel = dioguild.get_channel(610482665573056512)
    diony = dioguild.get_member(81316514216554496).mention

    if error is not None:
        tracebackoutput = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    else:
        tracebackoutput = "".join(traceback.format_exception(*sys.exc_info()))

    if ctx is not None:
        author = ctx.author
        content = ctx.message.content
        channel = ctx.channel
        server = ctx.guild.name
    elif message is not None:
        author = message.author
        content = message.content
        channel = message.channel
        server = message.guild.name
    else:
        # Fill out the rest of the message with traceback output.
        output = f'{diony}\n\n``````'
        if len(tracebackoutput)+len(output) > 2000:
            await diochannel.send(output.replace('``````', f'```{tracebackoutput[:2000-len(output)]}```'),
                                  file=discord.File(fp=StringIO(tracebackoutput), filename='fulltraceback.txt'))
        else:
            await diochannel.send(output.replace('``````', f'```{tracebackoutput}```'))
        return

    # Fill out the rest of the message with traceback output.
    output = (f'{diony}\n\n{author.display_name} said `{content}` in `#{channel}` '
              f'of `{server}` which caused ``````')
    if len(tracebackoutput)+len(output) > 2000:
        await diochannel.send(output.replace('``````', f'```{tracebackoutput[:2000-len(output)]}```'),
                              file=discord.File(fp=StringIO(tracebackoutput), filename='fulltraceback.txt'))
    else:
        await diochannel.send(output.replace('``````', f'```{tracebackoutput}```'))
    # Report to User
    await channel.send(f'{author.mention} There was an error executing that command.', delete_after=10)


# Commands
bmapidtojsoncache = {}


@bot.command()
@is_channel('qualifiers')
@send_typing
@commands.cooldown(1, 6, BucketType.channel)
async def lobby(ctx, lobby_id: int):
    await ctx.message.delete()
    id = ctx.author.id
    async with connpool.acquire() as conn:
        async with conn.transaction():
            player = await conn.fetchrow('''select * from players where discord_id=$1''', id)
            if player is None:
                await ctx.send(f'{ctx.author.mention} You don\'t appear to be registered for this tourney', delete_after=10)
                return
            lobby = await conn.fetchrow('''select * from lobbies where lobby_id=$1''', lobby_id)
            if lobby is None:
                await ctx.send(f'{ctx.author.mention} I can\'t find a lobby with id {lobby_id}', delete_after=10)
                return
            lobby_signup = await conn.fetchrow('''select * from lobby_signups where osu_id=$1''', player['osu_id'])

            try:
                # Signing up to a new lobby
                if lobby_signup is None:
                    await conn.execute('''insert into lobby_signups values ($1, $2)''', player['osu_id'], lobby_id)
                    await ctx.send(f'{ctx.author.mention} Added you to lobby {lobby_id}', delete_after=10)
                # Removing themselves from the lobby they are in
                elif lobby_signup['lobby_id'] == lobby_id:
                    await conn.execute('''delete from lobby_signups where osu_id=$1''', player['osu_id'])
                    await ctx.send(f'{ctx.author.mention} Removed you from lobby {lobby_id}', delete_after=10)
                # Switching lobbies
                else:
                    await conn.execute('''update lobby_signups set lobby_id=$1 where osu_id=$2''', lobby_id, player['osu_id'])
                    await ctx.send(f'{ctx.author.mention} Switched you to lobby {lobby_id}', delete_after=10)
            except asyncpg.exceptions.RaiseError:
                await ctx.send(f'{ctx.author.mention} Lobby {lobby_id} is full', delete_after=10)
    await update_lobbies(ctx)


@bot.command()
@is_channel('qualifiers')
@is_staff()
@send_typing
@commands.cooldown(1, 6, BucketType.channel)
async def signup(ctx, osu_username: str, lobby_id: int):
    await ctx.message.delete()
    async with connpool.acquire() as conn:
        async with conn.transaction():
            player = await conn.fetchrow('''select * from players where osu_username ilike $1''', osu_username)
            if player is None:
                await ctx.send(f'{ctx.author.mention} Couldn\'t find a user named {osu_username}', delete_after=10)
                return
            lobby = await conn.fetchrow('''select * from lobbies where lobby_id=$1''', lobby_id)
            if lobby is None:
                await ctx.send(f'{ctx.author.mention} I can\'t find a lobby with id {lobby_id}', delete_after=10)
                return
            lobby_signup = await conn.fetchrow('''select * from lobby_signups where osu_id=$1''', player['osu_id'])

            try:
                # Signing up to a new lobby
                if lobby_signup is None:
                    await conn.execute('''insert into lobby_signups values ($1, $2)''', player['osu_id'], lobby_id)
                    await ctx.send(f'{ctx.author.mention} Added {osu_username} to lobby {lobby_id}', delete_after=10)
                # Removing them from the lobby they are in
                elif lobby_signup['lobby_id'] == lobby_id:
                    await conn.execute('''delete from lobby_signups where osu_id=$1''', player['osu_id'])
                    await ctx.send(f'{ctx.author.mention} Removed {osu_username} from lobby {lobby_id}', delete_after=10)
                # Switching lobbies
                else:
                    await conn.execute('''update lobby_signups set lobby_id=$1 where osu_id=$2''', lobby_id, player['osu_id'])
                    await ctx.send(f'{ctx.author.mention} Switched {osu_username} to lobby {lobby_id}', delete_after=10)
            except asyncpg.exceptions.RaiseError:
                await ctx.send(f'{ctx.author.mention} Lobby {lobby_id} is full', delete_after=10)
    await update_lobbies(ctx)


@bot.command()
@is_channel('qualifiers')
@is_staff()
@send_typing
async def placeholders(ctx):
    await ctx.message.delete()
    # remove previous messages
    async with connpool.acquire() as conn:
        async with conn.transaction():
            messages = await conn.fetch('''select message_id from persistent_messages''')
            for message in messages:
                try:
                    i = await ctx.channel.fetch_message(message['message_id'])
                    await i.delete()
                except discord.NotFound:
                    pass
            await conn.execute('''delete from persistent_messages''')

    dates = [date(2020, 7, 10), date(2020, 7, 11), date(2020, 7, 12)]
    thumbnail_urls = ['https://i.imgur.com/Of7Z8pD.png', 'https://i.imgur.com/7Gochmd.png', 'https://i.imgur.com/EzpZz0k.png']
    ids = []
    # send the placeholder messages
    for _ in dates:
        message = await ctx.send(embed=discord.Embed(description='placeholder'))
        ids.append(message.id)
    message = await ctx.send(embed=discord.Embed(description='Use `!lobby #` to sign up for, switch to or leave a lobby E.g. !lobby 5\nAll times are in AEST (UTC+10) | @Diony in another channel for bot problems'))
    ids.append(message.id)
    # store the placeholder messages
    async with connpool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany('''insert into persistent_messages values ($1, $2, $3)''', list(zip(ids, dates, thumbnail_urls)))
            await conn.execute('''insert into persistent_messages (message_id) values ($1)''', ids[-1])


@bot.command()
@is_channel('qualifiers')
@send_typing
@commands.cooldown(1, 20, BucketType.channel)
async def refresh(ctx):
    await ctx.message.delete()
    await update_lobbies(ctx)


@bot.command(aliases=['ref', 'referee'])
@is_channel('qualifiers')
@is_staff()
@send_typing
@commands.cooldown(1, 6, BucketType.channel)
async def reff(ctx, lobby_id: int):
    await ctx.message.delete()
    id = ctx.author.id
    async with connpool.acquire() as conn:
        async with conn.transaction():
            staff = await conn.fetchrow('''SELECT * FROM staff where staff_discord_id=$1''', id)
            lobby = await conn.fetchrow('''SELECT * FROM lobbies where lobby_id=$1''', lobby_id)
            if lobby is None:
                await ctx.send(f'{ctx.author.mention} I can\'t find a lobby with id {lobby_id}', delete_after=10)
                return

            # removing themselves as reff
            if lobby['staff_osu_id'] == staff['staff_osu_id']:
                await conn.execute('''update lobbies set staff_osu_id=NULL where lobby_id=$1''', lobby_id)
                await ctx.send(f'{ctx.author.mention} Removed you as reff for lobby {lobby_id}', delete_after=10)
            # Switching reff
            else:
                await conn.execute('''update lobbies set staff_osu_id=$1 where lobby_id=$2''', staff['staff_osu_id'], lobby_id)
                await ctx.send(f'{ctx.author.mention} Added/replaced you as reff for lobby {lobby_id}', delete_after=10)
    await update_lobbies(ctx)


async def update_lobbies(ctx):
    async with connpool.acquire() as conn:
        async with conn.transaction():
            messages = await conn.fetch('''select * from persistent_messages;''')
            lobbies = await conn.fetch('''select * from lobbies;''')
            signups = await conn.fetch('''select osu_username, lobby_id from players natural join lobby_signups;''')
            staff = await conn.fetch('''select * from staff''')
    # message records that have a day associated will contain information about lobbies on that day.
    messages = [message for message in messages if message['day'] is not None]
    messages.sort(key=lambda x: x['day'])
    for i in messages:
        message = await ctx.channel.fetch_message(i['message_id'])
        lobbies_for_message = [record for record in lobbies if record['time'].date() == i['day']]
        lobbies_for_message.sort(key=lambda x: x['time'])

        embed = discord.Embed(color=discord.Colour(0x6e95fc))
        embed.set_thumbnail(url=i['thumbnail_url'])
        for lobby in lobbies_for_message:
            players = [record['osu_username'] for record in signups if record['lobby_id'] == lobby['lobby_id']]
            time = lobby['time']
            # datetime didn't have an easy way to get lowercase am/pm so I just did it manually
            timestring = f'{time.hour%12}:{str(time.minute).zfill(2)}{"am" if time.hour < 12 else "pm"}'
            # uses discord emotes to represent time with an analog clock emote
            name = f':clock{time.hour%12}: {timestring}'
            # either contains the reffs osu name or None if lobby has no reff
            referee_name = [record['staff_osu_username'] for record in staff if record['staff_osu_id'] == lobby['staff_osu_id']]

            free_spots = 16 - len(players)
            if free_spots == 0:
                emote = ':red_circle:'
            elif free_spots == 16:
                emote = ':orange_circle:'
            else:
                emote = ':green_circle:'
            playerstring = '    '.join(players) if len(players) > 0 else '-'
            reff = f' | Reffed by {referee_name[0]}' if referee_name else ''
            value = f'{emote} **ID: {lobby["lobby_id"]}** | {free_spots} free spots{reff}```{playerstring}```'
            embed.add_field(name=name, inline=False, value=value)
        await message.edit(content='', embed=embed)


@bot.command()
@commands.has_permissions(administrator=True)
@send_typing
async def pingunsigned(ctx):
    # Get everything after the command
    content = ctx.message.content.lstrip(ctx.prefix + ctx.invoked_with + ' ')
    await ctx.message.delete()
    if content.strip() == '':
        await ctx.send('Add what you want to say to the pingees after the command', delete_after=6)
        return
    async with connpool.acquire() as conn:
        async with conn.transaction():
            nonsigned_discord_ids = await conn.fetch('''select discord_id from players natural join (select osu_id from players except select osu_id from lobby_signups) as i;''')
    nonsigned_discord_ids = [record['discord_id'] for record in nonsigned_discord_ids]
    nonsigned_users = [bot.get_user(id) for id in nonsigned_discord_ids]
    if None in nonsigned_users:
        await ctx.send('Failed to find at least one of the pingees by discord id.', delete_after=7)
        return
    confirmed = await confirm(ctx, f'This will append your message (minus the command) with the pings of {len(nonsigned_users)} people. React with the tick to confirm within {20} seconds.')
    if confirmed:
        pings = ' '.join([user.mention for user in nonsigned_users])
        await ctx.send(f'{content}\n{pings}')


@bot.command()
@is_staff()
@send_typing
async def unsigned(ctx):
    await ctx.message.delete()
    async with connpool.acquire() as conn:
        async with conn.transaction():
            nonsigned_records = await conn.fetch('''select osu_username from players natural join (select osu_id from players except select osu_id from lobby_signups) as i;''')
    nonsigned_osu_usernames = [record['osu_username'] for record in nonsigned_records]
    user_list = '    '.join(nonsigned_osu_usernames) if len(nonsigned_osu_usernames) > 0 else '-'
    await ctx.send(f'{len(nonsigned_osu_usernames)} players have not yet signed up. ```{user_list}```')


@bot.command()
@is_channel('bot')
@send_typing
async def streamping(ctx):
    rolename = 'Stream Ping'
    pingrole = [role for role in ctx.guild.roles if role.name == rolename][0]
    if pingrole in ctx.author.roles:
        await ctx.author.remove_roles(pingrole)
        await ctx.send(f'{ctx.author.mention}, Removed your `{rolename}` role successfully.')
    else:
        await ctx.author.add_roles(pingrole)
        await ctx.send(f'{ctx.author.mention}, Gave you the `{rolename}` role successfully.')


@bot.command()
@is_channel('bot')
@send_typing
async def pickemping(ctx):
    rolename = 'Pickem Ping'
    pingrole = [role for role in ctx.guild.roles if role.name == rolename][0]
    if pingrole in ctx.author.roles:
        await ctx.author.remove_roles(pingrole)
        await ctx.send(f'{ctx.author.mention}, Removed your `{rolename}` role successfully.')
    else:
        await ctx.author.add_roles(pingrole)
        await ctx.send(f'{ctx.author.mention}, Gave you the `{rolename}` role successfully.')


@bot.command()
@is_channel('bot', 'scheduling')
@send_typing
async def when(ctx, match_id: to_id):
    # await ctx.message.delete()
    # Get spreadsheet from google sheets
    agc = await agcm.authorize()
    sh = await agc.open(sheet_file_name)
    ws = await sh.worksheet(schedule_sheet_name)

    # Get details for specified match from sheet
    try:
        finds = await ws.findall(match_id)
        # limit findings to the column that holds ids
        finds = [cell for cell in finds if cell.col == 1]
        cell = finds[0]
    except (CellNotFound, IndexError):
        await ctx.send(f'{ctx.author.mention} Couldn\'t find a match with ID: {match_id}', delete_after=10)
        return
    row = await ws.row_values(cell.row)

    austz = timezone('Australia/Melbourne')
    schednaive = datetime.strptime(f'{datetime.now().year} {row[5]} {row[6]}', '%Y %A, %d %b %I:%M %p')
    schedaware = austz.localize(schednaive)
    nowaware = datetime.now(get_localzone())

    nowausaware = nowaware.astimezone(austz)
    dstchange = nowausaware.dst() != schedaware.dst()

    tznotice = "UTC+11 / AEDT" if schedaware.dst() else "UTC+10 / AEST"
    delta = strfdelta(schedaware-nowaware, '{days} days, {hours} hours, {minutes} minutes')
    dststuff = "**Daylight savings ends between now and this match. Clocks should turn back an hour at 2am (AU) or 3am (NZ) on the 5th April.**" if dstchange else "There are no daylight savings changes before this match"
    try:
        p1flag = f':flag_{country[row[1]]}: '
        p2flag = f' :flag_{country[row[4]]}:'
    except KeyError:
        pass
    finally:
        p1flag = f''
        p2flag = f''
    embed = discord.Embed(title=f'{p1flag}{row[1]} vs {row[4]}{p2flag}', colour=discord.Colour(0xaadb35),
                          description=f'The sheet says **{row[5]}** at **{row[6]}** in **{tznotice}**\nThis occurs in `{delta}`\n{dststuff}')
    embed.set_author(name=f'Match ID: {match_id}')
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(administrator=True)
async def purge(ctx, limit: int):
    await ctx.channel.purge(limit=limit)


@bot.command(aliases=['purgebot'])
@commands.has_permissions(administrator=True)
async def botpurge(ctx, limit: int):
    await ctx.message.delete()
    await ctx.channel.purge(limit=limit, check=is_bot)


@bot.command(aliases=['purgewebhook'])
@commands.has_permissions(administrator=True)
async def webhookpurge(ctx, limit: int):
    await ctx.message.delete()
    await ctx.channel.purge(limit=limit, check=is_webhook)


@bot.command(name='del', aliases=['delete', 'undo'])
@is_channel('results', 'mappool')
async def delete(ctx):
    await ctx.message.delete()
    async for message in ctx.history():
        if message.author == bot.user:
            await message.delete()
            break


@bot.command(aliases=['hd', 'hr', 'dt', 'fm', 'tb'])
@is_channel('mappool')
@send_typing
async def nm(ctx):
    # Prep
    await ctx.message.delete()
    abreviations = {'nm': 'NoMod', 'hd': 'Hidden', 'hr': 'HardRock', 'dt': 'DoubleTime', 'fm': 'FreeMod', 'tb': 'TieBreaker'}
    skips = list(abreviations.values()) + ['No beatmap added']
    modpool = abreviations[ctx.invoked_with]

    # Get spreadsheet as 2d array
    agc = await agcm.authorize()
    sh = await agc.open('7S Mappool selection')
    ws = await sh.get_worksheet(0)
    raw = await ws.get_all_values()

    # Strip down 2d array to relevant maps
    # remove header row
    raw = raw[1:]
    # cut off cells on the right side
    raw = [row[:11] for row in raw]
    # Look down column 'C' looking for the specified modpool header, then collect rows until the modpool is over
    found = False
    maps = []
    for row in raw:
        if found and row[2] in skips:
            break
        if found:
            maps.append(row)
        if row[2] == modpool:
            found = True

    # Create user-readable message
    output = f'>>> __**Suggested {modpool} beatmaps:**__'
    for map in maps:
        emote = ':radio_button:' if map[0] == 'TRUE' else ':white_circle:'
        mapname = map[2] if len(map[2]) < 50 else map[2][:47] + '...'
        output += f'\n{emote} {mapname}\n             {map[4]}   |   {map[3]}*   |   {map[5]}bpm   |   {map[7]}ar   |   {map[8]}od'
    await ctx.send(output)


@bot.command()
@is_channel('mappool')
@send_typing
async def picked(ctx):
    # Prep
    await ctx.message.delete()
    abreviations = {'nm': 'NoMod', 'hd': 'Hidden', 'hr': 'HardRock', 'dt': 'DoubleTime', 'fm': 'FreeMod', 'tb': 'TieBreaker'}
    skips = list(abreviations.values()) + ['No beatmap added']

    # Get spreadsheet as 2d array
    agc = await agcm.authorize()
    sh = await agc.open('7S Mappool selection')
    ws = await sh.get_worksheet(0)
    raw = await ws.get_all_values()

    # Strip down 2d array to relevant maps
    # remove header row
    raw = raw[1:]
    # cut off cells on the right side
    raw = [row[:11] for row in raw]

    output = f'>>> __**Selected beatmaps**__'

    # Look down column 'C' looking for the specified modpool header, then collect rows until the modpool is over
    for modpool in list(abreviations.values()):
        output += f'\n**{modpool}:**'
        found = False
        for row in raw:
            if found and row[2] in skips:
                break
            if found and row[0] == 'TRUE':
                emote = ':radio_button:' if row[0] == 'TRUE' else ':white_circle:'
                mapname = row[2] if len(row[2]) < 50 else row[2][:47] + '...'
                output += f'\n{emote} {mapname}\n             {row[4]}   |   {row[3]}*   |   {row[5]}bpm   |   {row[7]}ar   |   {row[8]}od'
            if row[2] == modpool:
                found = True

    await ctx.send(output)


async def format(message):
    """This method isn't a @bot.command() so that users do not need to use the command prefix in the one
    channel this is used in. This method is called from on_message() when a match id is posted in #results.
    """
    async with message.channel.typing():
        await message.delete()
        # Get spreadsheet from google sheets
        agc = await agcm.authorize()
        sh = await agc.open(sheet_file_name)
        ws = await sh.worksheet(schedule_sheet_name)

        # Get details for specified match from sheet
        match_id = message.content.upper()
        try:
            finds = await ws.findall(match_id)
            # limit findings to the column that holds ids
            finds = [cell for cell in finds if cell.col == 1]
            cell = finds[0]
        except CellNotFound:
            await message.channel.send(f'{message.author.mention} Couldn\'t find a match with ID: {match_id}', delete_after=10)
            return
        row = await ws.row_values(cell.row)

        # Get lobby id from sheet
        try:
            lobby_id = url_to_id(row[14])
        except (SyntaxError, IndexError):
            await message.channel.send(f'{message.author.mention} Couldn\'t find a valid mp link on the sheet for match: {match_id}', delete_after=10)
            return

        # Get lobby info with osu api
        lobbyjson = await request(f'https://osu.ppy.sh/api/get_match?k={apiKey}&mp={lobby_id}')
        if lobbyjson['match'] == 0:
            await message.channel.send(f'{message.author.mention} Mp link (https://osu.ppy.sh/mp/{lobby_id}) returned no results for match: {match_id}', delete_after=10)
            return
        # elif lobbyjson['match']['end_time'] is None:
        #     await message.channel.send(f'{message.author.mention} Mp link (https://osu.ppy.sh/mp/{lobby_id}) looks to be incomplete. Use !mp close', delete_after=10)
        #     return

        # Gather info together from sheet
        p1 = {'username': row[1], 'score': row[2], 'ban1': row[7][1:4], 'ban2': row[8][1:4], 'roll': row[9]}
        p2 = {'username': row[4], 'score': row[3], 'ban1': row[10][1:4], 'ban2': row[11][1:4], 'roll': row[12]}
        if '' in p1.values() or '' in p2.values():
            await message.channel.send(f'{message.author.mention} Failed to find username, score, ban or roll for one '
                                       f'or both players on the sheet for match: {match_id}', delete_after=10)
            return
        # Used to line up the scores vertically by left justifying the username to this amount
        longest_name_len = len(max([p1['username'], p2['username']], key=len))
        # Highlight who the winner was using bold and an emoji
        if p1['score'] > p2['score']:
            p1['score'] = f'**{p1["score"]}** :trophy:'
        elif p1['score'] < p2['score']:
            p2['score'] = f'**{p2["score"]}** :trophy:'

        # Construct the embed
        try:
            description = (f':flag_{country[p1["username"]]}: `{p1["username"].ljust(longest_name_len)} -` {p1["score"]}\n'
                           f'Roll: {p1["roll"]} - Bans: {p1["ban1"]}, {p1["ban2"]}\n'
                           f':flag_{country[p2["username"]]}: `{p2["username"].ljust(longest_name_len)} -` {p2["score"]}\n'
                           f'Roll: {p2["roll"]} - Bans: {p2["ban1"]}, {p2["ban2"]}')
        except KeyError:
            await message.channel.send(f'{message.author.mention} Failed to map username(s) `{p1["username"]}` and/or `{p2["username"]}` from the spreadsheet to known participants. This is usually caused by incorrect capitilisation on the spreadsheet or name changes.', delete_after=16)
            return
        embed = discord.Embed(title=f'Match ID: {match_id}', description=description, color=0xe47607)
        embed.set_author(name=f'{tourneyRound}: ({p1["username"]}) vs ({p2["username"]})',
                         url=f'https://osu.ppy.sh/mp/{lobby_id}', icon_url='https://i.imgur.com/Y1zRCd8.png')
        embed.set_thumbnail(url='https://i.imgur.com/Y1zRCd8.png')
        try:
            referee = row[15]
            if referee == '':
                raise IndexError()
            embed.set_footer(text=f'Refereed by {referee}')
        except IndexError:
            embed.set_footer(text=f'Reported by {message.author.display_name}')

        # Construct the fields within the embed, displaying each pick and score differences
        firstpick = row[13]
        if firstpick not in ['P1', 'P2']:
            await message.channel.send(f'{message.author.mention} Failed to find who picked first by looking at the'
                                       f'sheet for match: {match_id}', delete_after=10)
            return
        orange = ':small_orange_diamond:'
        blue = ':small_blue_diamond:'
        tiebreaker = ':diamond_shape_with_a_dot_inside:'
        # Only look at games that used a beatmap from the mappool and were not aborted
        filteredgames = [game for game in lobbyjson['games'] if game['end_time'] is not None and int(game['beatmap_id']) in pool]
        for i, game in enumerate(filteredgames):
            emote = orange if i % 2 == 0 else blue
            # Alternate players starting from whoever the sheet says had first pick
            picker = p1['username'] if (i % 2 == 0 if firstpick == 'P1' else i % 2 != 0) else p2['username']
            bmapID = int(game['beatmap_id'])
            # Retreive beatmap information from osu api or cache
            if bmapID not in bmapIDs_to_json.keys():
                bmapJson = await request(f'https://osu.ppy.sh/api/get_beatmaps?k={apiKey}&b={bmapID}')
                bmapJson = bmapJson[0]
                bmapIDs_to_json[bmapID] = bmapJson
            else:
                bmapJson = bmapIDs_to_json[bmapID]
            bmapFormatted = f"{bmapJson['artist']} - {bmapJson['title']} [{bmapJson['version']}]"

            # Filter out scores made by referees
            scores = [score for score in game['scores'] if int(score['user_id']) not in referees]
            scores.sort(key=lambda score: int(score['score']), reverse=True)
            # Retreive winner's username from osu api or cache
            if scores[0]['user_id'] not in userIDs_to_usernames.keys():
                winnerjson = await request(f'https://osu.ppy.sh/api/get_user?k={apiKey}&u={scores[0]["user_id"]}')
                winner = winnerjson[0]['username']
                userIDs_to_usernames[scores[0]['user_id']] = winner
            else:
                winner = userIDs_to_usernames[scores[0]['user_id']]

            # Check if map was tiebreaker
            if pool[bmapID] == 'TB':
                firstline = f'{tiebreaker} **Tiebreaker**'
            else:
                firstline = f'{emote}Pick #{i+1} by __{picker}__ [{pool[bmapID]}]'
            # One or both players didn't play a map
            if len(scores) < 2:
                # await message.channel.send(f'{message.author.mention} It looks like a score is missing in the {infeng.ordinal(i+1)} mappool map for match: {match_id}', delete_after=10)
                embed.add_field(name=firstline,
                                value=f'[{bmapFormatted}](https://osu.ppy.sh/b/{bmapID})\n'
                                f'__{winner} ({int(scores[0]["score"]):,})__ wins. Other score missing.', inline=False)
            else:
                embed.add_field(name=firstline,
                                value=f'[{bmapFormatted}](https://osu.ppy.sh/b/{bmapID})\n'
                                f'__{winner} ({int(scores[0]["score"]):,})__ wins by **({int(scores[0]["score"])-int(scores[1]["score"]):,})**', inline=False)

        # Try to find result channel for this server
        resultchannels = [c for c in message.guild.channels if c.name == 'results']
        if len(resultchannels) < 1:
            await message.channel.send(f'{message.author.mention} Couldn\'t find a channel named `results` in this server to post result to', delete_after=10)
            return
        for channel in resultchannels:
            try:
                await channel.send(embed=embed)
                return
            except Exception:
                continue
        else:
            await message.channel.send(f'{message.author.mention} Couldn\'t post to the results channel for some reason. ping diony', delete_after=10)


# Utility methods
async def confirm(ctx, prompt, timeout=20.0):
    message = await ctx.send(prompt)
    await message.add_reaction('✅')
    await message.add_reaction('❌')

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ['✅', '❌']

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=timeout, check=check)
    except asyncio.TimeoutError:
        await message.delete()
        return False
    else:
        await message.delete()
        return str(reaction.emoji) == '✅'


async def request(url: str, headers: dict = {}) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as r:
            if r.status != 200:
                raise Exception('External server returned status code other than 200')
            json = await r.json()
    return json


def get_creds():
    scope = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    # Looks in the same directory as this script. Operating system and launch location independant.
    client_secret = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'client_secret.json')
    return ServiceAccountCredentials.from_json_keyfile_name(client_secret, scope)


def strfdelta(tdelta, fmt):
    """Used to convert timedelta objects into strings with a specified format.
       See https://stackoverflow.com/a/8907269"""
    d = {"days": tdelta.days}
    d["hours"], rem = divmod(tdelta.seconds, 3600)
    d["minutes"], d["seconds"] = divmod(rem, 60)
    return fmt.format(**d)


# Entry point
agcm = gspread_asyncio.AsyncioGspreadClientManager(get_creds)
bot.run(botToken)
