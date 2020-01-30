import asyncio
import os
import re
import sys
import traceback
import typing
from functools import wraps
from io import StringIO

import aiohttp
import discord
import gspread_asyncio
import inflect
from discord.ext import commands
from gspread.exceptions import CellNotFound
from oauth2client.service_account import ServiceAccountCredentials

from settings import *

bot = commands.Bot(command_prefix='!')
infeng = inflect.engine()

# Regex
osu_mp_url = re.compile(r'((https://osu.ppy.sh/community/matches/)|(https://osu.ppy.sh/mp/))(?P<id>[0-9]+)')
ban_format = re.compile(r'(nm|hd|hr|dt|fm)[0-9]', re.IGNORECASE)
match_id_format = re.compile(r'^([A-D]|[a-d])[0-9]+$')

# Caches
userIDs_to_usernames = {}
bmapIDs_to_json = {}


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


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.name == 'results':
        if re.match(match_id_format, message.content):
            await format(message)
    await bot.process_commands(message)


# Background tasks
async def check_if_live(user_login):
    while True:
        try:
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
        except Exception as error:
            await error_handler(error)
        await asyncio.sleep(30)


# Error handlers
@bot.event
async def on_command_error(ctx, error):
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
        sh = await agc.open('ANZT 7 Summer')
        ws = await sh.worksheet(schedule_sheet_name)

        # Get details for specified match from sheet
        match_id = message.content.upper()
        try:
            cell = await ws.find(match_id)
        except CellNotFound:
            await message.channel.send(f'{message.author.mention} Couldn\'t find a match with ID: {match_id}', delete_after=10)
            return
        row = await ws.row_values(cell.row)

        # Get lobby id from sheet
        try:
            lobby_id = url_to_id(row[12])
        except (SyntaxError, IndexError):
            await message.channel.send(f'{message.author.mention} Couldn\'t find a valid mp link on the sheet for match: {match_id}', delete_after=10)
            return

        # Get lobby info with osu api
        lobbyjson = await request(f'https://osu.ppy.sh/api/get_match?k={apiKey}&mp={lobby_id}')
        if lobbyjson['match'] == 0:
            await message.channel.send(f'{message.author.mention} Mp link (https://osu.ppy.sh/mp/{lobby_id}) returned no results for match: {match_id}', delete_after=10)
            return
        elif lobbyjson['match']['end_time'] is None:
            await message.channel.send(f'{message.author.mention} Mp link (https://osu.ppy.sh/mp/{lobby_id}) looks to be incomplete. Use !mp close', delete_after=10)
            return

        # Gather info together from sheet
        p1 = {'username': row[1], 'score': row[2], 'ban': row[7][1:4], 'roll': row[8]}
        p2 = {'username': row[4], 'score': row[3], 'ban': row[9][1:4], 'roll': row[10]}
        if '' in p1.values() or '' in p2.values():
            await message.channel.send(f'{message.author.mention} Failed to find username, score, ban or roll for one '
                                       f'or both players on the sheet for match: {match_id}')
            return
        # Used to line up the scores vertically by left justifying the username to this amount
        longest_name_len = len(max([p1['username'], p2['username']], key=len))
        # Highlight who the winner was using bold and an emoji
        if p1['score'] > p2['score']:
            p1['score'] = f'**{p1["score"]}** :trophy:'
        elif p1['score'] < p2['score']:
            p2['score'] = f'**{p2["score"]}** :trophy:'

        # Construct the embed
        description = (f':flag_{country[p1["username"]]}: `{p1["username"].ljust(longest_name_len)} -` {p1["score"]}\n'
                       f'Roll: {p1["roll"]} - Ban: {p1["ban"]}\n'
                       f':flag_{country[p2["username"]]}: `{p2["username"].ljust(longest_name_len)} -` {p2["score"]}\n'
                       f'Roll: {p2["roll"]} - Ban: {p2["ban"]}')
        embed = discord.Embed(title=f'Match ID: {match_id}', description=description, color=0xe47607)
        embed.set_author(name=f'{tourneyRound}: ({p1["username"]}) vs ({p2["username"]})',
                         url=f'https://osu.ppy.sh/mp/{lobby_id}', icon_url='https://i.imgur.com/Y1zRCd8.png')
        embed.set_thumbnail(url='https://i.imgur.com/Y1zRCd8.png')
        try:
            referee = row[13]
            if referee == '':
                raise IndexError()
            embed.set_footer(text=f'Refereed by {referee}')
        except IndexError:
            embed.set_footer(text=f'Reported by {message.author.display_name}')

        # Construct the fields within the embed, displaying each pick and score differences
        firstpick = row[11]
        if firstpick not in ['P1', 'P2']:
            await message.channel.send(f'{message.author.mention} Failed to find who picked first by looking at the'
                                       f'sheet for match: {match_id}', delete_after=10)
            return
        orange = ':small_orange_diamond:'
        blue = ':small_blue_diamond:'
        # Only look at games that used a beatmap from the mappool and were not aborted
        filteredgames = [game for game in lobbyjson['games'] if game['end_time'] is not None and game['beatmap_id'] in pool]
        for i, game in enumerate(filteredgames):
            emote = orange if i % 2 == 0 else blue
            # Alternate players starting from whoever the sheet says had first pick
            picker = p1['username'] if (i % 2 == 0 if firstpick == 'P1' else i % 2 != 0) else p2['username']
            bmapID = game['beatmap_id']
            # Retreive beatmap information from osu api or cache
            if bmapID not in bmapIDs_to_json.keys():
                bmapJson = await request(f'https://osu.ppy.sh/api/get_beatmaps?k={apiKey}&b={bmapID}')
                bmapJson = bmapJson[0]
                bmapIDs_to_json[bmapID] = bmapJson
            else:
                bmapJson = bmapIDs_to_json[bmapID]
            bmapFormatted = f"{bmapJson['artist']} - {bmapJson['title']} [{bmapJson['version']}]"

            # Filter out scores made by referees
            scores = [score for score in game['scores'] if score['user_id'] not in referees]
            # One or both players didn't play a map
            if len(scores) < 2:
                await message.channel.send(f'{message.author.mention} It looks like a score is missing in the {infeng.ordinal(i+1)} mappool map for match: {match_id}', delete_after=10)
                return
            scores.sort(key=lambda score: score['score'])
            # Retreive winner's username from osu api or cache
            if scores[0]['user_id'] not in userIDs_to_usernames.keys():
                winnerjson = await request(f'https://osu.ppy.sh/api/get_user?k={apiKey}&u={scores[0]["user_id"]}')
                winner = winnerjson[0]['username']
                userIDs_to_usernames[scores[0]['user_id']] = winner
            else:
                winner = userIDs_to_usernames[scores[0]['user_id']]

            embed.add_field(name=f'{emote}Pick #{i+1} by __{picker}__ [{pool[bmapID]}]',
                            value=f'[{bmapFormatted}](https://osu.ppy.sh/b/{bmapID})\n'
                            f'__{winner} ({scores[0]["score"]})__ wins by **({scores[0]["score"]-scores[1]["score"]})**', inline=False)

        await message.channel.send(embed=embed)


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
