from discord.ext import commands
import discord
from settings import *
import gspread_asyncio
import re
import aiohttp
import os
from oauth2client.service_account import ServiceAccountCredentials

bot = commands.Bot(command_prefix='!')

url_to_id_pattern = re.compile(r'((https://osu.ppy.sh/community/matches/)|(https://osu.ppy.sh/mp/))(?P<id>[0-9]+)')


def url_to_id(url: str) -> int:
    match = re.search(url_to_id_pattern, url)
    if match:
        lobby_id = int(match.group('id'))
        return lobby_id
    else:
        raise SyntaxError("Mp link is invalid")


@bot.command()
async def test(ctx, id: url_to_id):
    await ctx.send(id)


@bot.command()
async def nm(ctx):
    await handle_pool(ctx, 'nm')


@bot.command()
async def hd(ctx):
    await handle_pool(ctx, 'hd')


@bot.command()
async def hr(ctx):
    await handle_pool(ctx, 'hr')


@bot.command()
async def dt(ctx):
    await handle_pool(ctx, 'dt')


@bot.command()
async def fm(ctx):
    await handle_pool(ctx, 'fm')


@bot.command()
async def tb(ctx):
    await handle_pool(ctx, 'tb')


@bot.event
async def on_ready():
    print('Logged in as ' + bot.user.name)


bmapidtojsoncache = {}

async def handle_pool(ctx, modpool: str):
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


async def request(url: str) -> dict:
    json = {}
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            if r.status == 200:
                json = await r.json()
    return json


def get_creds():
    scope = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    # Looks in the same directory as this script. Operating system and launch location independant.
    client_secret = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'client_secret.json')
    return ServiceAccountCredentials.from_json_keyfile_name(client_secret, scope)

agcm = gspread_asyncio.AsyncioGspreadClientManager(get_creds)
bot.run(botToken)
