import kloudless

class CommandHandler(object):
    """
    This class is just acting as a container for cloud storage commands.
    """
    command_list = ['ls', 'cd', 'get', 'send', 'reset']
    def __init__(self, redis_client,  twilio_client, source_num):
        self.redis = redis_client
        self.twilio = twilio_client
        self.number = source_num

    def handle(self, number, session, body):
        """
        Parses out the command to execute and then calls the proper function.
        """
        argv = body.split()
        command = argv.pop(0).lower()
        if command not in self.command_list:
            return "Un-recognized command"
        try:
            result = getattr(self, command)(number, session, *argv)
        except Exception, e:
            return (("Erroneous command: %s\n\nIf you are unsure why this is "
                     "happening, start over by sending 'reset'") % e)
        return result

    def ls(self, number, session):
        """
        Lists currently visible accounts or directories/files for the current
        session.
        """
        pwd = session.get('pwd', '__META__ROOT__')
        if pwd == '__META__ROOT__':
            account_ids = self.redis.smembers('%s-accounts' % number)
            accounts = [kloudless.Account.retrieve(i) for i in account_ids] 
            choices = [('account', x.id, x.service, x.account) for x in accounts]
            message = "Available accounts, use 'cd <index>' to pick one:\n"
            for i in xrange(0,len(choices)):
                c = choices[i]
                message += "%s: %s,%s\n" % (i, c[2], c[3])
        else:
            account_id = session.get('account')
            if not account_id:
                return ("You do not have an account selected, please "
                        "'reset' your session and select one")
            account = kloudless.Account.retrieve(account_id)
            folder = kloudless.Folder(id=pwd, parent_resource=account) 
            choices = [(x.type, x.id, x.name) for x in folder.contents()]
            message = "Folders/Files in this directory:\n"
            for i in xrange(0, len(choices)):
                c = choices[i]
                message += "%s: %s,%s\n" % (i, c[0], c[2])
        session['choices'] = choices
        return message

    def cd(self, number, session, index):
        """
        Changes directories by updating the current working directory and
        pushing the old parent on the parents stack.
        """
        if not session.has_key('parents'):
            session['parents'] = []
            
        if index == '..':
            if len(session['parents']) < 1:
                return "Already at top level directory"
            session['pwd'] = session['parents'].pop()
            return self.ls(number, session)

        index = int(index)
        choices = session.get('choices')
        if not choices:
            self.ls(session)
            choices = session.get('choices')
        choice = choices[index]
        kind = choice[0]
        if kind == 'account':
            session['account'] = choice[1]
            session['parents'].append(session['pwd'])
            session['pwd'] = 'root'
        elif kind != 'file':
            session['parents'].append(session['pwd'])
            session['pwd'] = choice[1]
        else:
            message = "Your choice was not a folder, please make a different choice"
            return message
        return self.ls(number, session)

    def get(self, number, session, index):
        """
        This looks up a link for the chosen file and then puts it into a nice message.
        """
        index = int(index)
        choices = session.get('choices')
        if not choices:
            self.ls(number, session)
            choices = session.get('choices')
        choice = choices[index]
        kind = choice[0]
        if kind != 'file':
            return "You can only get files, please choose a file"
        if not session.has_key('account'):
            return "Please choose an account before you can get a file"
        account = kloudless.Account().retrieve(id=session['account'])
        link = account.links.create(file_id=choice[1])
        return "Here is a link to your file %s: %s" % (choice[2], link.url)


    def send(self, number, session, index, dest):
        index = int(index)
        choices = session.get('choices')
        if not choices:
            self.ls(number, session)
            choices = session.get('choices')
        choice = choices[index]
        kind = choice[0]
        if kind != 'file':
            return "You can only get files, please choose a file"
        if not session.has_key('account'):
            return "Please choose an account before you can get a file"
        account = kloudless.Account().retrieve(id=session['account'])
        link = account.links.create(file_id=choice[1])
        message = "%s sent you a link to a file %s: %s" % (number, choice[2], link.url)
        try:
            self.twilio.messages.create(to=dest,
                                        _from=self.number,
                                        body=message)
            return "Ok, message sent"
        except Exception, e:
            print e
            return ("There was a problem sending your message, please check "
                    "the phone number")

    def reset(self, number, session):
        """
        Restarts your session from the beginning, useful if something strange
        happens and you can't do anything.
        """
        for i in ['account', 'pwd', 'choices', 'parents']:
            if session.has_key(i):
                del(session[i])
        return "OK"
