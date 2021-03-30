from os import path

import aiohttp
import asyncpg
import gspread_asyncio
from discord.ext import commands
from google.oauth2.service_account import Credentials
from settings import dbhost, dbname, dbpass, dbport, dbuser


class ResourcesCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        self.requests_session = aiohttp.ClientSession()
        self.agcm = gspread_asyncio.AsyncioGspreadClientManager(self._get_creds)
        self.connection_pool = asyncpg.create_pool(database=dbname, user=dbuser, password=dbpass, host=dbhost, port=dbport)

    def cog_unload(self):
        loop = self.bot.loop
        loop.create_task(self.connection_pool.close())
        loop.create_task(self.requests_session.close())

    async def agc(self):
        return await self.agcm.authorize()

    async def connpool(self):
        return self.connection_pool

    async def session(self):
        return self.requests_session

    def _get_creds(self):
        # Looks up one directory from this file. OS and launch location independant.
        client_secret = path.join(path.split(path.dirname(__file__))[0], 'client_secret.json')
        creds = Credentials.from_service_account_file(client_secret)
        scoped = creds.with_scopes([
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ])
        return scoped


def setup(bot):
    bot.add_cog(ResourcesCog(bot))
