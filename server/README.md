# Tourney Registering OAuth Server

This directory contains a Flask server and it's accompanying WSGI file to interface with, in my case, Apache2.

This handles the part of the [OAuth 2.0 Authorization Code Grant](https://oauth.net/2/grant-types/authorization-code/) process, required by the [osu! v2 API](https://osu.ppy.sh/docs/index.html?bash#authentication), where users are redirected back to your service after the user has granted access to you.

More specifically when a user is redirected back to [osuanzt.com/register](http://osuanzt.com/register/), this web server will send the OAuth values included within the url parameters to the [`tourney-signup.py`](/cogs/tourney-signup.py) cog running in an instance of ANZTBot. ANZTBot then continues the rest of the OAuth procedure. A [TCP Python Stream](https://docs.python.org/3/library/asyncio-stream.html#tcp-echo-client-using-streams) is used to communicate between the web server and the discord bot.


## How I configured this to run in production
Configuring the flask web server to interface with Apache2 via WSGI and using the correct version of Python with the correct packages was quite an ordeal.

I initially followed [Flask's documentation on mod_wsgi](https://flask.palletsprojects.com/en/1.1.x/deploying/mod_wsgi/). However `libapache2-mod-wsgi-py3` installed a version of `mod_wsgi` compiled for Python `3.5.2` while I was developing in `3.9`.<br>
I eventually fixed this with a `pip install mod_wsgi` in my base Python `3.9` install and edited `/etc/apache2/mods-available/wsgi.load` to reference the new `mod_wsgi` by changing it from the following: 
```apache
LoadModule wsgi_module /usr/lib/apache2/modules/mod_wsgi.so
``` 
to 
```apache
LoadModule wsgi_module "/home/diony/.local/lib/python3.9/site-packages/mod_wsgi/server/mod_wsgi-py39.cpython-39-x86_64-linux-gnu.so"
WSGIPythonHome "/usr"
```
as suggested at the end of [`mod_wsgi`'s README](https://github.com/GrahamDumpleton/mod_wsgi#connecting-into-apache-installation).

For reference I added the following to `/etc/apache2/sites-available/000-default.conf` to configre apache2:
```apache
WSGIDaemonProcess ANZTBotRegister threads=5
WSGIScriptAlias /register /var/www/ANZTBotRegisterServer/wsgi_config.wsgi

<Directory /var/www/ANZTBotRegisterServer>
  WSGIProcessGroup ANZTBotRegister
  WSGIApplicationGroup %{GLOBAL}
  Order deny,allow
  Allow from all
</Directory>
```
