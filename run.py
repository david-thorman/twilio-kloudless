from flask import (Flask, request, redirect, abort, session, url_for,
                   flash, render_template)
from urllib import quote_plus
import yaml
import redis
import re
import random
import string

# External APIs
from twilio.rest import TwilioRestClient
from twilio.util import RequestValidator
import twilio.twiml
import kloudless

from handler import CommandHandler

# Settings
with open('./config.yml') as config_file:
    config = yaml.load(config_file)
    SECRET_KEY = config.get('SECRET_KEY')
    KLOUDLESS_API_KEY = config.get('KLOUDLESS_API_KEY')
    KLOUDLESS_APP_ID = config.get('KLOUDLESS_APP_ID')
    REDIS_CONFIG = config.get('REDIS_CONFIG')
    APP_NUMBER = config.get('APP_NUMBER')
    TWILIO_CONFIG = config.get('TWILIO_CONFIG')
    DEBUG = config.get('DEBUG')
    PORT = config.get('PORT')
    USE_HTTPS = config.get("USE_HTTPS")

app = Flask(__name__)
app.config.from_object(__name__)

kloudless.configure(api_key=KLOUDLESS_API_KEY)
redis_client = redis.StrictRedis(**REDIS_CONFIG)
twilio_client = TwilioRestClient(**TWILIO_CONFIG)
twilio_validator = RequestValidator(TWILIO_CONFIG['token'])
cmd_handler = CommandHandler(redis_client, twilio_client, APP_NUMBER)

# Actual App Routes
@app.route("/", methods=['GET','POST'])
def index():
    """
    This presents a simple welcoming page and a form to enter a phone number,
    """
    if request.method == 'POST':
        if (request.form.has_key('phone')
                and valid_phone(request.form['phone'])):
            session['phone'] = request.form['phone']
            code = gen_code()
            session['confirmation_code'] = code
            twilio_client.messages.create(to=session['phone'],
                                          _from=APP_NUMBER,
                                          body=(("Your confirmation code is: "
                                                 "%s") % code))
            return redirect(my_url('confirm'))
        else:
            flash("Please enter a valid phone number")
            return redirect(my_url('index'))
    else:
        if session.get('authed', False):
            return redirect(my_url('accounts'))
        return render_template('index.html')

@app.route("/confirm", methods=['GET','POST'])
def confirm():
    """
    This view renders the form where the user can enter their
    confirmation code and finally be "logged in".
    """
    if not session.has_key('phone') or not session.has_key('confirmation_code'):
        flash("Please log in.")
        return redirect(my_url('index'))
    if request.method == 'POST':
        if (request.form.has_key('code')
                and session['confirmation_code'] == request.form['code']):
            session['authed'] = True
            del session['confirmation_code']
            return redirect(my_url('accounts'))
        else:
            flash("Your confirmation code was invalid")
            return redirect(my_url('index'))
    else:
        return render_template('confirm.html')

@app.route("/accounts", methods=['GET'])
def accounts():
    """
    This main view shows the logged in user what accounts they have connected
    and allows them to connect other accounts simply by clicking a link that
    sends them through the Kloudless web Authentication process.
    """
    if not session.get('authed', False):
        flash("Please log in.")
        return redirect(my_url('index'))
    account_ids = redis_client.smembers('%s-accounts' % session['phone'])
    accounts = [kloudless.Account.retrieve(i) for i in account_ids]
    callback_url = quote_plus(my_url('auth_callback'))
    return render_template('accounts.html', accounts=accounts, app_number=APP_NUMBER,
                           callback_url=callback_url, app_id=KLOUDLESS_APP_ID)

@app.route("/callback", methods=['GET'])
def auth_callback():
    """
    This is the call back for the Kloudless web auth process, it stores the new account
    id that we recieve from Kloudless in a credential set in redis.
    """
    if not session.get('authed', False):
        flash("Please log in.")
        return redirect(my_url('index'))
    if request.args.has_key('account'):
        redis_client.sadd('%s-accounts' % session['phone'], request.args['account'])
        flash("Account added!")
        return redirect(my_url('accounts'))

@app.route("/logout", methods=['GET'])
def logout():
    """
    This just clears out the relevant information from the authenticated user
    session so they can log in again, or not.
    """
    if session.get('authed', False):
        for i in ['phone', 'authed', 'confirmation_code']:
            if session.has_key(i):
                del session[i]
    return redirect(my_url('index'))

@app.route("/delete", methods=['GET'])
def delete():
    """
    This will delete all cloud storage accounts that the user has connected and
    disassociate them from the phone number
    """
    if session.get('authed', False):
        key = '%s-accounts' % session['phone']
        account_ids = redis_client.smembers(key)
        for account_id in account_ids:
            kloudless.Account(id=account_id).delete()
        redis_client.delete(key)
        flash("Accounts deleted")
    return redirect(my_url('index'))

@app.route("/sms", methods=['POST'])
def message_dispatch():
    """
    This is the reciever for the Twilio web hooks, once it confirms that the
    request came from Twilio, it delegates all work to the command handler.
    """
    if not from_twilio(request):
        abort(403)
    resp = twilio.twiml.Response()
    if not session.get("pwd"):
        session['pwd'] = '__META__ROOT__'
    body = request.values.get("Body")
    number = request.values.get("From")
    message = cmd_handler.handle(number,session,body)
    session.modified = True
    resp.message(message)
    # We are probably going to modify the session on every command.
    return str(resp)

# Utility Functions
def valid_phone(phone_number):
    """
    Checks whether phone number is valid E.164
    """
    return bool(re.match(r"^\+?\d{10,15}$", phone_number))

def gen_code():
    """
    This is for generating confirmation codes, generates alphanumeric codes
    """
    return ''.join([random.choice(string.ascii_uppercase + string.digits) for _ in range(10)])

def from_twilio(req):
    """
    This verifies that the request is from twilio for security purposes.
    """
    return twilio_validator.validate(my_url('message_dispatch'), req.form,
                                     req.headers['X-Twilio-Signature'])

def my_url(url):
    """
    I am running this behind Stunnel for security so we need to make sure that
    the urls we generate to ourselves are all HTTPS if necessary.
    """
    if USE_HTTPS:
        return url_for(url, _scheme="https", _external=True)
    else:
        return url_for(url)

if __name__ == "__main__":
    app.run(debug=True, host="", port=PORT)
