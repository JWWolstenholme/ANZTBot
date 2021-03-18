import gspread_asyncio
from settings import *
import asyncio
import asyncpg
import os
import re
import aiohttp
from oauth2client.service_account import ServiceAccountCredentials
from discord.ext import commands

'''This file contains persistent objects that should only be initiated here,
   but can be imported and used elsewhere too. It also contains some utility
   methods.'''


def send_typing(f):
    '''Decorater that can be used to send typing indicator. Only works on
       methods that have a message or context as their first parameter.'''
    @wraps(f)
    async def wrapped(*args):
        if args[0].__class__ == discord.ext.commands.Context:
            async with args[0].typing():
                return await f(*args)
        elif args[0].__class__ == discord.Message:
            async with args[0].channel.typing():
                return await f(*args)
    return wrapped


def is_channel(*args: str):
    async def predicate(ctx):
        return ctx.message.channel.name in args
    return commands.check(predicate)


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


async def request(url: str, headers: dict = {}) -> dict:
    '''Quick and dirty short-hand REST API grabber.'''
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as r:
            if r.status != 200:
                raise Exception('External server returned status code other than 200')
            json = await r.json()
    return json


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


osu_mp_url = re.compile(r'((https://osu.ppy.sh/community/matches/)|(https://osu.ppy.sh/mp/))(?P<id>[0-9]+)')


def url_to_id(url: str) -> int:
    match = re.search(osu_mp_url, url)
    if match:
        return int(match.group('id'))
    else:
        raise SyntaxError("\"{}\" is not a valid mp link".format(url))


def __get_creds():
    scope = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    # Looks in the same directory as this script. Operating system and launch location independant.
    client_secret = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'client_secret.json')
    return ServiceAccountCredentials.from_json_keyfile_name(client_secret, scope)


def init():
    # Google Sheets authentication manager
    global agcm
    agcm = gspread_asyncio.AsyncioGspreadClientManager(__get_creds)

    # Postgresql connection manager
    # global connpool
    # connpool = asyncpg.create_pool(database=dbname, user=dbuser, password=dbpass, host=dbhost, port=dbport)
