import discord
from discord.ext import commands
import re
from resources import url_to_id, is_channel, agcm, request
from settings import *


class MatchResultPostingCog(commands.Cog):
    delete_delay = 10
    match_id_format = re.compile(r'^[a-h][0-9]+$', re.IGNORECASE)
    userID_username_cache = {}
    bmapID_json_cache = {}
    username_flag_cache = {}

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return
        # if message.channel.name in ['bot']:
        if message.channel.name in ['match-results', 'referee']:
            if re.match(self.match_id_format, message.content):
                async with message.channel.typing():
                    await message.delete()
                    await self.post_result(message)

    @commands.command(aliases=['del', 'undo'])
    @is_channel('match-results')
    async def delete(self, ctx):
        await ctx.message.delete()
        async for message in ctx.history():
            if message.author == self.bot.user:
                await message.delete()
                break

    async def post_result(self, message):
        async with message.channel.typing():
            # Get spreadsheet from google sheets
            agc = await agcm.authorize()
            sh = await agc.open(sheet_file_name)

            match_id = message.content.upper()
            ws = await sh.worksheet(match_id)

            # Get lobby id from sheet
            try:
                urlcell = await ws.acell('C4')
                lobby_id = url_to_id(urlcell.value)
            except (SyntaxError, IndexError):
                await message.channel.send(f'{message.author.mention} Couldn\'t find a valid mp link on the sheet for match: {match_id}', delete_after=self.delete_delay)
                return

            # Get lobby info with osu api
            lobbyjson = await request(f'https://osu.ppy.sh/api/get_match?k={apiKey}&mp={lobby_id}')
            if lobbyjson['match'] == 0:
                await message.channel.send(f'{message.author.mention} Mp link (https://osu.ppy.sh/mp/{lobby_id}) returned no results for match: {match_id}', delete_after=self.delete_delay)
                return
            # elif lobbyjson['match']['end_time'] is None:
            #     await message.channel.send(f'{message.author.mention} Mp link (https://osu.ppy.sh/mp/{lobby_id}) looks to be incomplete. Use !mp close', delete_after=self.delete_delay)
            #     return

            batch = (await ws.batch_get(['B2:L5']))[0]
            # Gather info together from sheet
            # syntax is batch[row][col] relative to the range B2:L5
            p1 = {'username': batch[0][4], 'score': batch[1][4], 'ban1': batch[1][9][0:3], 'roll': batch[2][4]}
            p2 = {'username': batch[0][6], 'score': batch[1][6], 'ban1': batch[2][9][0:3], 'roll': batch[2][6]}
            if '' in p1.values() or '' in p2.values():
                await message.channel.send(f'{message.author.mention} Failed to find username, score, ban or roll for one '
                                           f'or both players on the sheet for match: {match_id}', delete_after=self.delete_delay)
                return
            # Used to line up the scores vertically by left justifying the username to this amount
            longest_name_len = len(max([p1['username'], p2['username']], key=len))
            # Highlight who the winner was using bold and an emoji
            if p1['score'] > p2['score']:
                p1['score'] = f'**{p1["score"]}** :trophy:'
            elif p1['score'] < p2['score']:
                p2['score'] = f'**{p2["score"]}** :trophy:'

            # Retreive player's flags from api or cache
            if p1['username'] not in self.username_flag_cache.keys():
                json = await request(f'https://osu.ppy.sh/api/get_user?k={apiKey}&u={p1["username"]}&m=0&type=string')
                flag = json[0]['country'].lower()
                self.username_flag_cache[p1['username']] = flag
            else:
                flag = self.username_flag_cache[p1['username']]
            p1['flag'] = flag

            if p2['username'] not in self.username_flag_cache.keys():
                json = await request(f'https://osu.ppy.sh/api/get_user?k={apiKey}&u={p2["username"]}&m=0&type=string')
                flag = json[0]['country'].lower()
                self.username_flag_cache[p2['username']] = flag
            else:
                flag = self.username_flag_cache[p2['username']]
            p2['flag'] = flag

            # Construct the embed
            description = (f':flag_{p1["flag"]}: `{p1["username"].ljust(longest_name_len)} -` {p1["score"]}\n'
                           f'Roll: {p1["roll"]} - Ban: {p1["ban1"]}\n'
                           f':flag_{p2["flag"]}: `{p2["username"].ljust(longest_name_len)} -` {p2["score"]}\n'
                           f'Roll: {p2["roll"]} - Ban: {p2["ban1"]}')
            embed = discord.Embed(title=f'Match ID: {match_id}', description=description, color=0xe47607)
            embed.set_author(name=f'{tourneyRound}: ({p1["username"]}) vs ({p2["username"]})',
                             url=f'https://osu.ppy.sh/mp/{lobby_id}')

            # Add streamer and referee to footer
            ws = await sh.worksheet('Schedule')
            schedule_batch = (await ws.batch_get(['B5:I100']))[0]
            referee = ''
            streamer = ''
            reporter = message.author.display_name
            for row in schedule_batch:
                if row[0] == match_id:
                    try:
                        referee = row[6]
                        streamer = row[7]
                    except IndexError:
                        pass
                    break

            footer = f'Refereed by {referee}' if referee else f'Reported by {reporter}'
            footer += f' - Streamed by {streamer}' if streamer else ''
            embed.set_footer(text=footer)

            # Construct the fields within the embed, displaying each pick and score differences
            firstpick = batch[3][5]
            if firstpick not in [p1['username'], p2['username']]:
                await message.channel.send(f'{message.author.mention} Failed to find who picked first by looking at the'
                                           f'sheet for match: {match_id}', delete_after=self.delete_delay)
                return
            orange = ':small_orange_diamond:'
            blue = ':small_blue_diamond:'
            tiebreaker = ':diamond_shape_with_a_dot_inside:'

            # Get the mappool
            ws = await sh.worksheet('Mappool')
            poolRound = 0
            cells = f'D{3+25*poolRound}:F{2+25*(poolRound+1)}'
            poolbatch = (await ws.batch_get([cells]))[0]
            pool = {}
            for row in poolbatch:
                pool[int(row[2])] = row[0]

            # Only look at games that used a beatmap from the mappool and were not aborted
            filteredgames = [game for game in lobbyjson['games'] if game['end_time'] is not None and int(game['beatmap_id']) in pool]
            for i, game in enumerate(filteredgames):
                emote = orange if i % 2 == 0 else blue
                # Alternate players starting from whoever the sheet says had first pick
                picker = p1['username'] if (i % 2 == 0 if firstpick == p1['username'] else i % 2 != 0) else p2['username']
                bmapID = int(game['beatmap_id'])
                # Retreive beatmap information from osu api or cache
                if bmapID not in self.bmapID_json_cache.keys():
                    bmapJson = await request(f'https://osu.ppy.sh/api/get_beatmaps?k={apiKey}&b={bmapID}')
                    bmapJson = bmapJson[0]
                    self.bmapID_json_cache[bmapID] = bmapJson
                else:
                    bmapJson = self.bmapID_json_cache[bmapID]
                bmapFormatted = f"{bmapJson['artist']} - {bmapJson['title']} [{bmapJson['version']}]"

                # Filter out scores made by referees
                scores = [score for score in game['scores'] if int(score['user_id']) not in referees]
                scores.sort(key=lambda score: int(score['score']), reverse=True)
                # Retreive winner's username from osu api or cache
                if scores[0]['user_id'] not in self.userID_username_cache.keys():
                    winnerjson = await request(f'https://osu.ppy.sh/api/get_user?k={apiKey}&u={scores[0]["user_id"]}')
                    winner = winnerjson[0]['username']
                    self.userID_username_cache[scores[0]['user_id']] = winner
                else:
                    winner = self.userID_username_cache[scores[0]['user_id']]

                # Check if map was tiebreaker
                if pool[bmapID].startswith('TB'):
                    firstline = f'{tiebreaker} **Tiebreaker**'
                else:
                    firstline = f'{emote}Pick #{i+1} by __{picker}__ [{pool[bmapID]}]'
                # One or both players didn't play a map
                if len(scores) < 2:
                    # await message.channel.send(f'{message.author.mention} It looks like a score is missing in the {infeng.ordinal(i+1)} mappool map for match: {match_id}', delete_after=self.delete_delay)
                    embed.add_field(name=firstline,
                                    value=f'[{bmapFormatted}](https://osu.ppy.sh/b/{bmapID})\n'
                                    f'__{winner} ({int(scores[0]["score"]):,})__ wins. Other score missing.', inline=False)
                else:
                    embed.add_field(name=firstline,
                                    value=f'[{bmapFormatted}](https://osu.ppy.sh/b/{bmapID})\n'
                                    f'__{winner} ({int(scores[0]["score"]):,})__ wins by **({int(scores[0]["score"])-int(scores[1]["score"]):,})**', inline=False)

            # Try to find result channel for this server
            resultchannels = [c for c in message.guild.channels if c.name == 'match-results']
            if len(resultchannels) < 1:
                await message.channel.send(f'{message.author.mention} Couldn\'t find a channel named `match-results` in this server to post result to', delete_after=self.delete_delay)
                return
            for channel in resultchannels:
                try:
                    await channel.send(embed=embed)
                    if message.channel.name == 'referee':
                        await message.channel.send(f'{message.author.mention} Done', delete_after=self.delete_delay)
                    return
                except Exception:
                    continue
            else:

                await message.channel.send(f'{message.author.mention} Couldn\'t post to the results channel for some reason. ping diony', delete_after=self.delete_delay)


def setup(bot):
    bot.add_cog(MatchResultPostingCog(bot))
