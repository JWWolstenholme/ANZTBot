from discord.ext import commands
import discord
from settings import *
import gspread_asyncio
import re
import asyncio
import aiohttp
import os
from oauth2client.service_account import ServiceAccountCredentials

from functools import wraps
import typing
import traceback

bot = commands.Bot(command_prefix='!')

osu_mp_url = re.compile(r'((https://osu.ppy.sh/community/matches/)|(https://osu.ppy.sh/mp/))(?P<id>[0-9]+)')
ban_format = re.compile(r'(nm|hd|hr|dt|fm)[0-9]', re.IGNORECASE)


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


# Decorater methods
def send_typing(f):
    @wraps(f)
    async def wrapped(*args):
        async with args[0].typing():
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


# Event listeners
@bot.event
async def on_ready():
    print('Logged in as ' + bot.user.name)
    bot.loop.create_task(check_if_live('osuanzt'))


# Background tasks
async def check_if_live(user_login):
    while True:
        jsonresp = await request(f'https://api.twitch.tv/helix/streams?user_login={user_login}', {"Client-ID": clientID})
        live = jsonresp['data'] != []
        if live:
            title = jsonresp['data'][0]['title']
            title = title if title is not '' else 'with no title'
            activity = discord.Streaming(name=title,
                                         url=f'https://www.twitch.tv/{user_login}', platform='Twitch')
        else:
            activity = None
        await bot.change_presence(activity=activity)
        await asyncio.sleep(30)


# Error handlers
@bot.event
async def on_command_error(ctx, error):
    # Report to Diony
    guild = bot.get_guild(255990138289651713)
    channel = guild.get_channel(610482665573056512)
    diony = guild.get_member(81316514216554496).mention

    tracebackoutput = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    await channel.send(f'{diony}\n\n{ctx.author.display_name} said `{ctx.message.content}` in `#{ctx.channel}` '
                       f'of `{ctx.guild.name}` which caused ```{tracebackoutput}```')

    # Report to User
    await ctx.channel.send(f'{ctx.author.mention} There was an error executing that command. '
                           f'Someone has been notified.', delete_after=10)

# Commands
bmapidtojsoncache = {}


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


@bot.command(aliases=['e'])
@commands.has_permissions(administrator=True)
async def embed(ctx, *argv: str):
    embed = discord.Embed(title='This is a test', color=0xe47607)
    # Loop over arguments two at a time, ignoring StopIteration caused by odd number of arguments
    it = iter(argv)
    for x in it:
        try:
            embed.add_field(name=x, value=next(it))
        except StopIteration:
            pass

    embed.set_footer(text=f'Requested by {ctx.author.display_name}')
    await ctx.send(embed=embed)


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


@bot.command()
@is_channel('results')
@send_typing
async def format(ctx, id: url_to_id, match_id: int,
                 p1score: typing.Optional[int], p2score: typing.Optional[int],
                 p1ban: to_ban, p2ban: to_ban,
                 warmups: typing.Optional[int] = 2):
    '''Handles the acquisition of match information through the osu api and sends a discord message'''
    await ctx.message.delete()

    lobbyjson = await (f'https://osu.ppy.sh/api/get_match?k={apiKey}&mp={id}')
    if lobbyjson['match'] == 0:
        raise Exception('Osu api returned no matches for match id {}'.format(id))

    # Get player usernames from lobby title
    players = re.search(r'\((?P<p1>.+?)\) vs(.)* \((?P<p2>.+?)\)', lobbyjson['match']['name'])
    p1 = players.group('p1').lower()
    p2 = players.group('p2').lower()

    # Stores a cache of ids to usernames reducing api calls
    ids_to_usernames = {}

    # List slicing skips warmups
    games = lobbyjson['games'][warmups:]

    # Store username -> tourney match score
    finalscore = {p1: 0, p2: 0}
    if p1score is not None and p2score is not None:
        finalscore[p1] = p1score
        finalscore[p2] = p2score
    else:
        for bmap in games:
            # Map was aborted
            if bmap['end_time'] is None:
                continue

            # Store username -> score on map
            mapscores = {}

            for score in bmap['scores']:
                userid = score['user_id']
                # Convert userid to username
                if userid not in ids_to_usernames.keys():
                    userjson = await request(f'https://osu.ppy.sh/api/get_user?k={apiKey}&u={userid}')
                    username = userjson[0]['username'].lower()
                    ids_to_usernames[userid] = username
                else:
                    username = ids_to_usernames[userid]

                if score['pass'] == '1':
                    mapscores[username] = int(score['score'])
                else:
                    mapscores[username] = 0

            if mapscores[p1] > mapscores[p2]:
                finalscore[p1] += 1
            else:
                finalscore[p2] += 1

    emotes = [':zero:', ':one:', ':two:', ':three:', ':four:', ':five:', ':six:', ':seven:', ':eight:', ':nine:',
              ':keycap_ten: ']
    embed = discord.Embed(title=f'ID: {match_id} - https://osu.ppy.sh/mp/{id}', color=0xe47607)
    embed.set_author(name=f'{acronym} - {tourneyRound}')
    embed.add_field(name=f'{p1} {emotes[finalscore[p1]]}', value=f'Banned {p1ban.upper()}', inline=True)
    embed.add_field(name=f'{emotes[finalscore[p2]]} {p2}', value=f'Banned {p2ban.upper()}', inline=True)
    embed.set_footer(text=f'Reported by {ctx.message.author.display_name}')
    await ctx.send(embed=embed)


# Utility methods
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


# Entry point
agcm = gspread_asyncio.AsyncioGspreadClientManager(get_creds)
bot.run(botToken)
