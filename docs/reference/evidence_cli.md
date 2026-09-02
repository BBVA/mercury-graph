# The `mge` command-line interface

The **`mge`** command-line interface is the recommended way to create, inspect, pilot and serve **Endpoints**.

Although every component of the `mercury.graph.evidence` module can be used directly from Python, most users will interact with Endpoints
through the `mge` command. It automates the complete Endpoint lifecycle, from creating a new project to exposing it as a REST service.


## Typical workflow

The most common workflow consists of the following steps:

```text
mge new demo

# Edit the Endpoint configuration

mge pilot demo ALL_READY

mge summary demo

mge serve demo ALL_READY 8000
```

where:

* **`new`** creates a new Endpoint project.
* **`pilot`** loads the Endpoint and drives it to the desired operational state.
* **`summary`** displays the current Endpoint configuration and state.
* **`serve`** exposes the Endpoint through its REST API.


## Command reference

The following output is produced directly by running:

```bash
mge --help
```

This is the authoritative description of the command-line interface. Whenever the CLI changes, this output should be considered the
reference.

```text
usage: Mercury-graph Evidence: Endpoint management cli 3.3.1 [-h] [--just_once] [--log_file LOG_FILE] [--version]
                                                                     {new,summary,pilot,serve,unlock,complete} name [intent] [port]

Creates, displays, serves and pilots persisted Endpoint objects.

positional arguments:
  {new,summary,pilot,serve,unlock,complete}
                        📁 new [name]:                 Creates the scaffold of a new Endpoint object with all the necessary files.
                        📊 summary [path]:             Displays a summary of the state of an Endpoint.
                        🌀 pilot [path, intent]:       Loads the Endpoint and pilots it to an intended state running the necessary
                                                       queries to reach that state.
                        🌎 serve [path, intent, port]: Loads the Endpoint, verifies the intent and serves it via http on the given
                                                       port. It exposes its Agentic .meta property and the .run method.
                        🔑 unlock [path]:              Forces removing the lock of the Endpoint. Use with caution!
                        ✨ complete bash:              Prints the Bash tab-completion command.
                                                       Use: source <(mge complete bash)
  name                  name of new Endpoint (for new) or path to an existing Endpoint (all other commands).
  intent                desired final state (for pilot) or required state (for serve)
  port                  port to serve the Endpoint (only for serve)

options:
  -h, --help            show this help message and exit
  --just_once           stop at first run instead of until intent is reached (only for pilot)
  --log_file LOG_FILE   path of the Agentic event log file (only for pilot and serve)
  --version             show program's version number and exit

```

## Python implementation

::: cli.mge
