import sys
activate_this = '/var/www/ANZTBotRegisterServer/venv/bin/activate_this.py'
with open(activate_this) as file_:
    exec(file_.read(), dict(__file__=activate_this))
    sys.path.insert(0, '/var/www/ANZTBotRegisterServer')
    from server import app as application
