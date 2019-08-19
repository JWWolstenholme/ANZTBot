#! /usr/bin/python3

import discord
import re
import aiohttp
import asyncio
import traceback
import gspread_asyncio
import os
from oauth2client.service_account import ServiceAccountCredentials
# See https://i.imgur.com/PXyTi8L.png for settings.py format
from settings import *

client = discord.Client()
resultpattern = re.compile(r'((https://osu.ppy.sh/community/matches/)|(https://osu.ppy.sh/mp/))(?P<id>[0-9]+)'
                           r' (?P<b1>(NM|nm|HD|hd|HR|hr|DT|dt|FM|fm)[0-9]) (?P<b2>(NM|nm|HD|hd|HR|hr|DT|dt|FM|fm)[0-9])'
                           r'(?P<wm>( [0-9]))?')
poolerpattern = re.compile(r'\!(NM|nm|HD|hd|HR|hr|DT|dt|FM|fm|TB|tb)')


@client.event
async def on_message(message):
    try:
        if message.author == client.user:
            return

        if message.content.startswith('ping'):
            await message.channel.send(':upside_down:')

        if message.channel.name == 'results':
            if re.match(resultpattern, message.content):
                await handle_match(message)
            else:
                print('Invalid')

        if message.channel.name == 'mappool':
            if re.match(poolerpattern, message.content):
                await handle_pool(message)
    except Exception:
        # Report to Diony
        guild = client.get_guild(255990138289651713)
        channel = guild.get_channel(610482665573056512)
        diony = guild.get_member(81316514216554496).mention
        await channel.send(f'{diony}\n\n{message.author.display_name} said `{message.content}` in `#{message.channel}` '
                           f'of `{message.guild.name}` which caused ```{traceback.format_exc()}```')
        # Report to user
        botmessage = await message.channel.send(f'{message.author.mention} There was an error executing that command. '
                                                'Someone has been notified.')
        await asyncio.sleep(8)
        await botmessage.delete()

bmapidtojsoncache = {}

async def handle_pool(message):
    await message.delete()

    agc = await agcm.authorize()
    sh = await agc.open('Mappool Selection')
    ws = await sh.get_worksheet(0)

    mods = ['nm', 'hd', 'hr', 'dt', 'fm', 'tb']
    messagemod = message.content[1:].lower()
    offset = mods.index(messagemod)

    picked = await ws.col_values(offset * 3 + 1)
    urls = await ws.col_values(offset * 3 + 2)
    picker = await ws.col_values(offset * 3 + 3)

    picked = picked[1:]
    urls = urls[1:]
    picker = picker[1:]

    embed = discord.Embed(title='Currently suggested ' + messagemod.upper() + ' maps', color=0xe47607, url='https://doc'
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

    embed.set_footer(text=f'Requested by {message.author.display_name}')
    await message.channel.send(embed=embed)


def get_creds():
    scope = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    # Looks in the same directory as this script. Operating system and launch location independant.
    client_secret = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'client_secret.json')
    return ServiceAccountCredentials.from_json_keyfile_name(client_secret, scope)

agcm = gspread_asyncio.AsyncioGspreadClientManager(get_creds)

async def handle_match(message):
    '''Handles the acquisition of match information through the osu api and sends a discord message'''
    await message.delete()

    group = re.search(resultpattern, message.content)

    # Grab match id and bans straight from message
    lobby_id = group.group('id')
    p1b = group.group('b1')
    p2b = group.group('b2')

    warmups = group.group('wm')
    warmups = 2 if warmups is None else int(warmups)

    lobbyjson = await request(f'https://osu.ppy.sh/api/get_match?k={apiKey}&mp={lobby_id}')

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
    embed = discord.Embed(title=f'{tourneyRound} - https://osu.ppy.sh/mp/{lobby_id}', color=0xe47607)
    embed.set_author(name=f'{acronym}')
    embed.add_field(name=f'{p1} {emotes[finalscore[p1]]}', value=f'Banned {p1b.upper()}', inline=True)
    embed.add_field(name=f'{emotes[finalscore[p2]]} {p2}', value=f'Banned {p2b.upper()}', inline=True)
    embed.set_footer(text=f'Coded by Diony | Reported by {message.author.display_name}')
    await message.channel.send(embed=embed)


async def request(url):
    json = {}
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            if r.status == 200:
                json = await r.json()
    return json


@client.event
async def on_ready():
    print('Logged in as ' + client.user.name)
    print('------')


client.run(botToken)
