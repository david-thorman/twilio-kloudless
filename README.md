# Twilio Kloudless Mash-Up

Basic idea is SMS interface to your cloud storage. It uses [Twilio](https://www.twilio.com) for SMS and [Kloudless](https://developers.kloudless.com) for cloud storage interactions.

Commands:

- `ls` - returns indexed list of visible folders
- `cd (<index>|..)` - change to listed directory or to parent respectively
- `get <index>` - Get an SMS with a link to download the file
- `send <index> <phone number>` - send an SMS with link to file to number (e.g.
  +15555555555)
- `reset` - starts your session back from the beginning

## Intro
This app allows you to interact with your cloud storage accounts via SMS. It is meant to demonstrate how easy it is to manage cloud storage accounts in different situations with Kloudless.

## Structure
This is a python app that uses [Flask](http://flask.pocoo.org/) to be very simple reciever of web hooks that Twilio uses to handle the messages. It is broken into two parts:

- `run.py` - The flask app that defines the routes to handle requests, it is a thin wrapper around the handler. It also handles the web interfaces for associating cloud storage accounts with your phone number.
- `handler.py` - This takes in the body of the message, parses out the command and arguments, and passses them to the right parts of the Kloudless SDK.

The application stores session data client-side using Flask's built in sessions (this is possible because Twilio maintains a cookie that allows us to associate multiple messages with a single phone number).  It stores the current working direct, bread crumbs, current account if applicable, and current possible choices that the user can make. Log in is handled by a one time password that is sent to your number to verify that you are the owner and from there you can authenticate accounts and remove existing accounts.

## Development Process
In order to help developers build their own applications using Kloudless I just wanted to go through my own development process.

### How I Started
The `run.py` I ended up with is essentially a modified version of the sample app that you end up with in [Twilio's SMS and MMS Python Quickstart](https://www.twilio.com/docs/quickstart/python/sms). I decided to use Flask because that is what their guide uses and it is really simple and has all the functionality I need.

I also went through the [Kloudless Python SDK README](https://github.com/Kloudless/kloudless-python/blob/master/README.md) to figure out the basic commands that would be necessary. Here is the mapping:

- `ls` for accounts: `kloudless.Account.all()`
    - this returns a list of account objects that the user then selects from using `cd <index>`
- `ls` for a directory, if you have the right account object in `account` and the folder id in `folder_id`:
  `kloudless.Folder(id=folder_id, parent_resource=account).contents()`
    - To list the root folder of a particular account you can simply do
    - this returns a list of folder and file objects that you can then choose from and work with.
- `get` if you have the file object stored in `file_obj` and the account in `account`: `acccount.links.create(file_id=file.id)`
    - this returns a link object containing a url that the user can visit to preview (if the source supports it) or download the file.
    - I decided to just return a link, since I wasn't sure whether all file types could be sent via MMS and most phones have some kind of web browser (though it might be fairly bare bones).
- `send` is basically like `get` except that you are sending it to someone else.

I decided that this functionality as pretty much independed of the workings of the rest of the web app, so I stuck it in a separate file, `handler.py`.

### Putting it All Together
The main route that handles the SMS messages is `/sms` and that initializes the session for the number if it doesn't exist and starts the user at a top level "directory" that lists all of the accounts that the user can choose from.  We need to look up which accounts the user has added from the database so that we can return the right information and make sure there is no unauthorized access.

The command gets split out from the message body and the remaining parts are passed in as arguments to the relevant function. The result is just put back into a TWiML response for Twilio to send back to the user. In order to maintain a meaningful idea of where the user is, we maintain a couple of things in the session:

- Current working directory, if an account hasn't been chosen yet, then we set this to a kind of "meta" node that indicates that we must list the accounts when the user tells us to 'ls'.
- Current account, if selected.
- Directory stack, since this app is simple and only allows going one level at a time, we maintain a history of your previous directories so that you can go back from whence you came.
- Available choices, we store the results of an `ls` (and make one implicitly if you haven't) to make sure that we know the right option you are picking for `cd` and `get`.

Using this information we have plenty of information to do basic file directory traversal and fetch files for you. From this relatively simple base in the handler it is pretty trivial to add other interactions like `rm` or `send` that would remove files/directories and send files to someone else respsectively.  All of this is done without a single line of source specific code or even reading the documentation for any of these sources. That is the ease that Kloudless provides.

### The Web App
The back end portion was extremely simple because all that we had to do was handle POST requests from Twilio that contained all the information that we needed and we didn't have to maintain any persistent data outside of the session. I wanted this to be useable by other people so I made a really simple web application to allow people to confirm their phone numbers and associate their cloud storage accounts.

#### Log-In
I didn't want to store passwords for these phone numbers, so all I do is generate a onetime password that gets sent to the phone number provided, that then gets entered to be confirmed. After that, I just set a flag in the person's session that we can use to check if they have authenticated.

We do need to make sure that cloud storage accounts are associated with the right phone numbers, so we are going to store the accounts (actually just the account ids) in a [set]() in [Redis](). This is a simple way to make sure that the important data is persistent and quickly accessible.

#### Connecting Accounts
Authenticating user cloud storage accounts is also extremely simple using kloudless, I simply send the user to the [Kloudless services]() page with my app id and a call back url. The user can select the cloud storage account they want and my application just gets back the `account_id` and which service they connected.

#### Security Considerations
If we want to have this accessible over the interenet, there are a couple of concerns:

1. Making sure that only calls from Twilio are accepted by the webhook reciever
1. Ensure that all data is encrypted in transport between server and client
1. Only your phone number has access to your cloud storage accounts

The first is some what tricky, but Twilio provides a header with a signature that authorizes all of the requests that it makes. They provide a utility that implements request verification by going through the cryptographic hash of the request data with your Twilio token secret so that you know that only they could have made the request. This could also by done via firewalling off all access to the application except from Twilio's servers, but this is not feasible since they have a large number of servers that the web hooks could be made from.

The second is relatively straight forward, I am running this on a VPS with just the simple server behind [stunnel](https://www.stunnel.org/index.html) using a self-signed certificate. It is for your own safety, even if it isn't verified by a third party.

The third is what I am usng redis for, I am persisting the association between a particular phone number and set of cloud storage accounts to make sure that there is no unauthorized access. Since I am not exposing my API key directly to any clients, there is less blatant risk of compromising it, so as long as my config file is safe, my secret is safe.

Of course, no security is perfect. This application is relatively simple, however, and these were the basic things that I thought would make it relatively secure to be publicly available on the internet. Of course, I am not sure how secure SMS is as a medium of transport or how easy it is to spoof the source phone number of an SMS message, but I cannot really do anything about those particular risks.

## Running this Code
I tried to keep dependencies to a minimum and they can be installed through the `requirements.txt` file in this repository (via `pip install -r requirements.txt`). You will also need to configure the application by copying `config.yml.sample` to `config.yml` and substitute your configuration values where relevant. With configuration in place, just `python run.py` to start the service. Once it is up, you can visit it (by default) at `http://localhost:15456`.

## Exploring the Code
A majority of the interesting code is in `handler.py`, this is the code that does the work of interacting with the cloud storage API. It is meant to be simple and adding a new command is as easy as adding a new function and adding it to the list of functions.
