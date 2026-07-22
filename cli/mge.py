#!/usr/bin/python

import argparse, datetime, os, pathlib, sys, subprocess

import uvicorn

from fastapi import Body, FastAPI, HTTPException

import mercury.graph as mg


class MgeFileLogger:
    """ A minimal append-only file logger for Agentic events.
    """

    def __init__(self, path):
        """ Initializes the logger and checks that its file can be written.

        Arguments:
            path (str): The path of the log file.
        """

        self.path = path
        with open(self.path, 'a'):
            pass


    def append(self, event):
        """ Appends an Agentic event dictionary to the log file.

        Arguments:
            event (dict): The Agentic event to log.
        """

        with open(self.path, 'a') as f:
            f.write('%s\n' % event)


class MgeHttpServe:
    """ The MgeHttpServe class exposes an Endpoint Agentic API over HTTP.
    """

    def __init__(self, ep):
        """ Initializes the HTTP server object.

        Arguments:
            ep (Endpoint): The Endpoint to expose.
        """

        self.ep = ep
        self.app = FastAPI(title = 'Mercury-graph Evidence Endpoint', version = mg.__version__)

        self.app.get('/meta')(self.meta)
        self.app.post('/run')(self.run)
        self.app.post('/dry_run')(self.dry_run)


    def meta(self):
        """ Returns the Endpoint metadata. """

        try:
            return self.ep.meta

        except HTTPException:
            raise

        except Exception as e:
            raise HTTPException(status_code = 500, detail = str(e))


    def run(self, request = Body(...)):
        """ Runs a request against the Endpoint.

        Arguments:
            request (dict): The JSON request body.
        """

        request = self.__validated_request(request)

        try:
            return self.ep.run(request)

        except mg.evidence.agentic.AgenticRunInvalidRequest:
            raise HTTPException(status_code = 400, detail = 'Invalid request.')

        except mg.evidence.agentic.AgenticRunInvalidState:
            raise HTTPException(status_code = 503, detail = 'Invalid state.')

        except mg.evidence.agentic.AgenticRunFailed:
            raise HTTPException(status_code = 500, detail = 'Run failed.')

        except HTTPException:
            raise

        except Exception as e:
            raise HTTPException(status_code = 500, detail = str(e))


    def dry_run(self, request = Body(...)):
        """ Simulates running a request against the Endpoint.

        Arguments:
            request (dict): The JSON request body.
        """

        request = self.__validated_request(request)

        try:
            return self.ep.dry_run(request)

        except HTTPException:
            raise

        except Exception as e:
            raise HTTPException(status_code = 500, detail = str(e))


    def serve(self, port):
        """ Starts the HTTP server.

        Arguments:
            port (int): The TCP port to listen on.
        """

        uvicorn.run(self.app, host = '0.0.0.0', port = port)


    def __validated_request(self, request):
        """ Checks that a request body is a JSON object.

        Arguments:
            request (dict): The JSON request body.
        """

        if type(request) != dict:
            raise HTTPException(status_code = 400, detail = 'Request body must be a JSON object.')

        return request


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
        self.logger = None

        if args.get('log_file') is not None:
            try:
                self.logger = MgeFileLogger(args['log_file'])

            except (OSError, TypeError, ValueError):
                print('Error: The log file "%s" cannot be written to.' % args['log_file'])
                sys.exit(1)

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
        """ Executes the "new" command after the arguments have been checked to exist. """

        if mg.evidence.Agentic._normalize_name(self.name) != self.name:
            print('Error: The name "%s" is not valid. It must be a string of letters, numbers, and underscores.' % self.name)
            sys.exit(1)

        ifn = str(pathlib.Path(__file__).resolve().parent / 'new_endpoint_template')
        if not os.path.exists(ifn):
            print('Error: The source template directory "%s" does not exist. Try re-installing the package.' % ifn)
            sys.exit(1)

        ofn = os.path.abspath(self.name)
        if os.path.exists(ofn):
            print('Error: The target directory "%s" already exists. Please choose a different name or edit the existing Endpoint.' % ofn)
            sys.exit(1)

        self.__exec('cp -r %s %s' % (ifn, ofn))

        conf_fn = os.path.join(ofn, 'mge_endpoint.jsonc')
        creation_date = datetime.date.today().isoformat()

        with open(conf_fn, 'r') as f:
            txt = f.read()

        txt = txt.replace('"name": ""', '"name": "%s"' % self.name, 1)
        txt = txt.replace('"creation_date": ""', '"creation_date": "%s"' % creation_date, 1)
        txt = txt.replace('"mge_version": ""', '"mge_version": "%s"' % mg.__version__, 1)

        with open(conf_fn, 'w') as f:
            f.write(txt)

        try:
            ep = mg.evidence.Endpoint(self.name)

        except Exception:
            print('Error: The newly created Endpoint "%s" failed to load.' % self.name)
            sys.exit(1)

        print ('Created a new Endpoint object "%s" in folder "%s".' % (ep.id, ep.home))


    def summary(self):
        """ Executes the "summary" command after the arguments have been checked to exist. """

        try:
            ep = mg.evidence.Endpoint(self.name)

        except Exception:
            print('Error: Could not load the Endpoint object from "%s". Please check the path and try again.' % self.name)
            sys.exit(1)

        print (ep)


    def pilot(self):
        """ Executes the "pilot" command after the arguments have been checked to exist. """
        try:
            ep = mg.evidence.Endpoint(self.name, logger = self.logger)

        except Exception:
            print('Error: Could not load the Endpoint object from "%s". Please check the path and try again.' % self.name)
            sys.exit(1)

        if ep.lock(mg.evidence.endpoint.LockState.LOCK) != mg.evidence.endpoint.LockState.LOCK:
            print('Error: Could not lock the Endpoint "%s". It is locked by another process.' % ep.id)
            sys.exit(1)

        print ('Piloting the Endpoint "%s" to the state "%s" with just_once=%s ...' % (ep.id, self.intent, self.just_once))

        try:
            ep.pilot(self.intent, just_once = self.just_once)

        finally:
            ep.lock(mg.evidence.endpoint.LockState.FREE)

        state = ep.meta['state']
        name  = ep.state_name(state)
        if name is None:
            name = '\033[2m(no name)\033[0m'

        print ('\nFinal state is %d "%s"\n\nDone.' % (state, name))


    def serve(self):
        """ Executes the "serve" command after the arguments have been checked to exist. """

        try:
            ep = mg.evidence.Endpoint(self.name, logger = self.logger)

        except Exception:
            print('Error: Could not load the Endpoint object from "%s". Please check the path and try again.' % self.name)
            sys.exit(1)

        if ep.lock(mg.evidence.endpoint.LockState.LOCK) != mg.evidence.endpoint.LockState.LOCK:
            print('Error: Could not lock the Endpoint "%s". It is locked by another process.' % ep.id)
            sys.exit(1)

        state = ep.meta['state']
        name  = ep.state_name(state)
        if name is None:
            name = '\033[2m(no name)\033[0m'

        if str(state) != str(self.intent) and str(name).lower() != str(self.intent).lower():
            ep.lock(mg.evidence.endpoint.LockState.FREE)
            print('Error: The Endpoint "%s" is in state %d "%s" but the intent is "%s".' % (ep.id, state, name, self.intent))
            sys.exit(1)

        print ('Serving the Endpoint "%s" see "http://127.0.0.1:%s/meta" ...' % (ep.id, self.port))

        try:
            MgeHttpServe(ep).serve(self.port)

        finally:
            ep.lock(mg.evidence.endpoint.LockState.FREE)


    def unlock(self):
        """ Executes the "unlock" command after the arguments have been checked to exist. """

        try:
            ep = mg.evidence.Endpoint(self.name)

        except Exception:
            print('Error: Could not load the Endpoint object from "%s". Please check the path and try again.' % self.name)
            sys.exit(1)

        ep.lock(mg.evidence.endpoint.LockState.FORCE_FREE)

        print ('Endpoint "%s" forcefully unlocked.' % ep.id)


    def complete(self):
        """ Executes the "complete". The argument self.name is ignored. Should be "bash" because it is a mandatory argument. """

        print('complete -W "new summary pilot serve unlock complete --just_once --log_file --help --version" -A directory mge')


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
    '🔑 unlock [path]:              Forces removing the lock of the Endpoint. \033[1mUse with caution!\033[0m',
    '✨ complete bash:              Prints the Bash tab-completion command.',
    '                               Use: \033[1msource <(mge complete bash)\033[0m'])

# Add each argument to the parser.
parser.add_argument('command', choices = ['new', 'summary', 'pilot', 'serve', 'unlock', 'complete'], help = help)
parser.add_argument('name', help = 'name of new Endpoint \033[3m(for new)\033[0m or path to an existing Endpoint \033[3m(all other commands)\033[0m.')
parser.add_argument('intent', help = 'desired final state \033[3m(for pilot)\033[0m or required state \033[3m(for serve)\033[0m', nargs = '?')
parser.add_argument('port', help = 'port to serve the Endpoint \033[3m(only for serve)\033[0m', nargs = '?')
parser.add_argument('--just_once', action = 'store_true', help = 'stop at first run instead of until intent is reached \033[3m(only for pilot)\033[0m')
parser.add_argument('--log_file', help = 'path of the Agentic event log file \033[3m(only for pilot and serve)\033[0m')
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
