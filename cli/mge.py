#!/usr/bin/python

import argparse, os, pathlib, sys, subprocess

import mercury.graph as mg


class MgeCli:
    """ The MgeCli class is a command line interface for managing Mercury-graph Evidence Endpoint objects.
    """

    def __init__(self, args):
        cmd = args['command']
        self.name = args['name']

        if cmd not in ['pilot', 'serve']:
            return

        if args['intent'] is None:
            print('Error: The intent argument is required.')
            sys.exit(1)


        self.intent = args['intent']
        self.just_once = args['just_once']

        if cmd != 'serve':
            return

        if args['port'] is None:
            print('Error: The port argument is required.')
            sys.exit(1)

        try:
            self.port = int(args['port'])

        except ValueError:
            print('Error: The port argument must be an integer.')
            sys.exit(1)


    def __exec(self, cmd):
        """ Executes a command and captures the output.

        Args:
            cmd (str): The command to execute.
        Returns:
            list: The output of the command as a list of strings.
        """

        try:
            txt = subprocess.run(cmd, shell = True, check = True, capture_output = True)

        except:
            msg = '"%s" returned an error %s' % (cmd, subprocess.CalledProcessError)
            raise RuntimeError(msg)

        return [s for s in txt.stdout.decode('utf8').strip().split('\n')]


    def new(self):
        if mg.evidence.Agentic._normalize_name(self.name) != self.name:
            print('Error: The name "%s" is not valid. It must be a string of letters, numbers, and underscores.' % self.name)
            sys.exit(1)

        ifn = str(pathlib.Path(__file__).resolve().parent / 'new_endpoint_template')
        if not os.path.exists(ifn):
            print('Error: The source template directory "%s" does not exist. Try re-installing the package.' % ifn)
            sys.exit(1)

        print ('Creating a new Endpoint object with the name %s...' % self.name)

        ofn = os.path.abspath(self.name)
        if os.path.exists(ofn):
            print('Error: The target directory "%s" already exists. Please choose a different name or remove the existing directory.' % ofn)
            sys.exit(1)

        self.__exec('cp -r %s %s' % (ifn, ofn))


    def summary(self):
        try:
            ep = mg.evidence.Endpoint(self.name)

        except Exception:
            print('Error: Could not load the Endpoint object from %s. Please check the path and try again.' % self.name)
            sys.exit(1)

        print ('Displaying a summary of the Endpoint in %s...' % self.name)


    def pilot(self):
        print ('Piloting the Endpoint in %s to the state %s with just_once=%s...' % (self.name, self.intent, self.just_once))


    def serve(self):
        print ('Serving the Endpoint in %s only if state is actually %s on port %s...' % (self.name, self.intent, self.port))


    def unlock(self):
        print ('Unlocking the Endpoint in %s...' % self.name)


    def complete(self):
        print('complete -W "new summary pilot serve unlock complete --just_once --help --version" mge ')


# An argparse.ArgumentParser to manage the command line interface.
#   RawTextHelpFormatter is used to allow multi-line help messages.
parser = argparse.ArgumentParser(prog			 = '\033[1mMercury-graph Evidence\033[0m: Endpoint management cli %s' % mg.__version__,
                                 description	 = 'Creates, displays, serves and pilots persisted Endpoint objects.',
                                 allow_abbrev	 = False,
                                 formatter_class = argparse.RawTextHelpFormatter)

# The help message is a multi-line string.
help = '\n'.join([
    '📁 new [name]:                 Creates the scaffold of a new Endpoint object with all the necessary files.',
    '📊 summary [path]:             Displays a summary of the state of an Endpoint.',
    '🌀 pilot [path, intent]:       Loads the Endpoint and pilots it to an intended state running the necessary',
    '                               queries to reach that state.',
    '🌎 serve [path, intent, port]: Loads the Endpoint, verifies the intent and serves it via http on the given',
    '                               port. It exposes its Agentic \033[1m.meta\033[0m property and the \033[1m.run\033[0m method.',
    '🔑 unlock [path]:              Forces removing the lock of the current Endpoint. \033[1mUse with caution!\033[0m',
    '✨ complete bash:              Prints the Bash tab-completion command.',
    '                               Use: \033[1msource <(mge complete bash)\033[0m'])

# Add each argument to the parser.
parser.add_argument('command', choices = ['new', 'summary', 'pilot', 'serve', 'unlock', 'complete'], help = help)
parser.add_argument('name', help = 'name of new Endpoint \033[3m(for new)\033[0m or path to an existing Endpoint \033[3m(all other commands)\033[0m.')
parser.add_argument('intent', help = 'desired final state \033[3m(for pilot)\033[0m or required state \033[3m(for serve)\033[0m', nargs = '?')
parser.add_argument('port', help = 'port to serve the Endpoint \033[3m(only for serve)\033[0m', nargs = '?')
parser.add_argument('--just_once', action = 'store_true', help = 'stop at first run instead of until intent is reached \033[3m(only for pilot)\033[0m')
parser.add_argument('--version', action = 'version', version = mg.__version__)


if __name__ == '__main__':
    args = parser.parse_args()

    cli = MgeCli(vars(args))		# Just create the object and print errors for bad requests making args.command = None on error.

    if args.command == 'new':
        cli.new()
    elif args.command == 'summary':
        cli.summary()
    elif args.command == 'pilot':
        cli.pilot()
    elif args.command == 'serve':
        cli.serve()
    elif args.command == 'unlock':
        cli.unlock()
    elif args.command == 'complete':
        cli.complete()
