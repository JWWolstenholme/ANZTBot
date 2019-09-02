from discord.ext import commands
import discord
from settings import *
import gspread_asyncio
import re
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


# Event listeners
@bot.event
async def on_ready():
    print('Logged in as ' + bot.user.name)


# Error handlers
@bot.event
async def on_error(ctx, error):
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
    modpool = ctx.invoked_with

    await ctx.message.delete()

    agc = await agcm.authorize()
    sh = await agc.open('Mappool Selection')
    ws = await sh.get_worksheet(0)

    mods = ['nm', 'hd', 'hr', 'dt', 'fm', 'tb']
    offset = mods.index(modpool)

    picked = await ws.col_values(offset * 3 + 1)
    urls = await ws.col_values(offset * 3 + 2)
    picker = await ws.col_values(offset * 3 + 3)

    picked = picked[1:]
    urls = urls[1:]
    picker = picker[1:]

    embed = discord.Embed(title='Currently suggested ' + modpool.upper() + ' maps', color=0xe47607, url='https://doc'
                          's.google.com/spreadsheets/d/1UsNH5BIvAkR1Fwb5vdR0I7zHQgSWmFFgemZh4v5cTJg/edit#gid=588134396')
    for i, url in enumerate(urls):
        bmapId = re.findall(r'\d+', url)[-1]
        if bmapId in bmapidtojsoncache.keys():
            mapJson = bmapidtojsoncache[bmapId]
        else:
            mapJson = await request(f'https://osu.ppy.sh/api/get_beatmaps?k={apiKey}&b={bmapId}')
            mapJson = mapJson[0]
            bmapidtojsoncache[bmapId] = mapJson

        indent = '\u200b \u200b \u200b \u200b \u200b \u200b \u200b \u200b \u200b '
        maptitle = f'{mapJson["artist"]} - {mapJson["title"]} [{mapJson["version"]}]'
        emote = ':radio_button:' if picked[i] == 'TRUE' else ':white_circle:'
        maplength = '{:d}:{:02d}'.format(int(int(mapJson['total_length']) / 60), int(mapJson['total_length']) % 60)
        embed.add_field(name=f'{emote} {maptitle}', value=f'{indent}[Link]({url}) - {picker[i]} - {maplength}, '
                        f'{float(mapJson["difficultyrating"]):.2f}*, {mapJson["bpm"]}bpm, {mapJson["diff_approach"]}ar,'
                        f' {mapJson["diff_overall"]}od')

    embed.set_footer(text=f'Requested by {ctx.author.display_name}')
    await ctx.send(embed=embed)


@bot.command()
@is_channel('results')
@send_typing
async def format(ctx, id: url_to_id, match_id: int,
                 p1score: typing.Optional[int], p2score: typing.Optional[int],
                 p1ban: to_ban, p2ban: to_ban,
                 warmups: typing.Optional[int]=2):
    '''Handles the acquisition of match information through the osu api and sends a discord message'''
    await ctx.message.delete()

    lobbyjson = await request(f'https://osu.ppy.sh/api/get_match?k={apiKey}&mp={id}')
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
async def request(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
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
