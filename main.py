import discord
import re
import aiohttp
# See https://i.imgur.com/PXyTi8L.png for settings.py format
from settings import *

client = discord.Client()
resultpattern = re.compile('(https://osu.ppy.sh/community/matches/)|(https://osu.ppy.sh/mp/)(?P<id>[0-9]+) (?P<b1>(NM|nm|HD|hd|HR|hr|DT|dt|FM|fm)[0-9]) (?P<b2>(NM|nm|HD|hd|HR|hr|DT|dt|FM|fm)[0-9])(?P<wm>( [0-9]))?')


@client.event
async def on_message(message):
    if message.author == client.user:
        return
    
    if message.content.startswith('ping'):
        await message.channel.send(':upside_down:')
    
    if message.channel.name == 'results':
        if re.match(resultpattern, message.content):
            await handle_match(message)
        else:
            print('Invalid')


async def handle_match(message):
    """Handles the acquisition of match information through the osu api and sends a discord message"""
    
    group = re.search(resultpattern, message.content)
    
    # Grab match id and bans straight from message
    lobby_id = group.group('id')
    p1b = group.group('b1')
    p2b = group.group('b2')
    
    warmups = group.group('wm')
    if warmups is None:
        warmups = 2
    else:
        warmups = int(warmups)
    
    lobbyjson = await request(f'https://osu.ppy.sh/api/get_match?k={apiKey}&mp={lobby_id}')
    
    # Get player usernames from lobby title
    players = re.search('\((?P<p1>.+?)\) vs(.)* \((?P<p2>.+?)\)', lobbyjson['match']['name'])
    p1 = players.group('p1')
    p2 = players.group('p2')
    
    # Stores a cache of ids to usernames reducing api calls
    ids_to_usernames = {}
    
    # List slicing skips warmups
    games = lobbyjson['games'][warmups:]
    
    # Store username -> tourney match score
    finalscore = {p1: 0, p2: 0}
    
    for bmap in games:
        # Store username -> score on map
        mapscores = {}
        
        for score in bmap['scores']:
            userid = score['user_id']
            # Convert userid to username
            if userid not in ids_to_usernames.keys():
                userjson = await request(f'https://osu.ppy.sh/api/get_user?k={apiKey}&u={userid}')
                username = userjson[0]['username']
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
    await message.delete()
    await message.channel.send(embed=embed)


async def request(url):
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
