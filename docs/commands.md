# Ask Command Reference

Every ask command operates on the project in the current directory,
or the one given with the global `--path`/`-p` option.
Pass the global `--assume-yes` option to answer yes to every prompt,
for running ask without a terminal.

<!-- ask:gen:commands -->

### `ask create`

Create the project's container and converge it.

### `ask config`

Print the project's resolved configuration.

### `ask converge`

Apply ask.toml and the flavour's configuration to the container.

| Argument   | Description                                                                               |
| ---------- | ----------------------------------------------------------------------------------------- |
| `--create` | Create the project's container if it does not exist, without asking. Defaults to `false`. |

### `ask destroy`

Delete the project's container and its configuration.

### `ask enter`

Start a shell in the project's container.

| Argument                   | Description                                                                                                                                                          |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GUI --gui --no-gui`       | Start a GUI session sharing the host's Wayland socket with the container. Defaults to `false`.                                                                       |
| `--root --no-root`         | Start a root shell instead of the container user's. Defaults to `false`.                                                                                             |
| `--create`                 | Create the project's container if it does not exist, without asking. Defaults to `false`.                                                                            |
| `--converge --no-converge` | Converge the project's container if its configuration has changed since it was last converged, without asking. --no-converge never converges it. Defaults to `None`. |

### `ask exec`

Run a command in the project's container.

| Argument                   | Description                                                                                                                                                          |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `COMMAND...`               | Command and arguments to run.                                                                                                                                        |
| `--gui --no-gui`           | Start a GUI session sharing the host's Wayland socket with the container. Defaults to `false`.                                                                       |
| `--create`                 | Create the project's container if it does not exist, without asking. Defaults to `false`.                                                                            |
| `--converge --no-converge` | Converge the project's container if its configuration has changed since it was last converged, without asking. --no-converge never converges it. Defaults to `None`. |

### `ask agent`

Start an AI agent in the project's container.

| Argument                   | Description                                                                                                                                                          |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NAME --name`              | Agent name; defaults to the flavour's default agent. Defaults to `None`.                                                                                             |
| `ARGS...`                  | Arguments passed to the command.                                                                                                                                     |
| `--gui --no-gui`           | Start a GUI session sharing the host's Wayland socket with the container. Defaults to `false`.                                                                       |
| `--create`                 | Create the project's container if it does not exist, without asking. Defaults to `false`.                                                                            |
| `--converge --no-converge` | Converge the project's container if its configuration has changed since it was last converged, without asking. --no-converge never converges it. Defaults to `None`. |

### `ask ide`

Start an IDE in the project's container.

| Argument                   | Description                                                                                                                                                          |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NAME --name`              | IDE name; defaults to the project's first configured IDE. Defaults to `None`.                                                                                        |
| `ARGS...`                  | Arguments passed to the IDE's binary.                                                                                                                                |
| `--gui --no-gui`           | Start a GUI session sharing the host's Wayland socket with the container. Defaults to `true`.                                                                        |
| `--create`                 | Create the project's container if it does not exist, without asking. Defaults to `false`.                                                                            |
| `--converge --no-converge` | Converge the project's container if its configuration has changed since it was last converged, without asking. --no-converge never converges it. Defaults to `None`. |

### `ask init`

Create an ask.toml template in the current directory.

### `ask ls`

List all known asks (Incus containers created by ask).

### `ask rename`

Rename the project's directory and its container.

| Argument    | Description                     |
| ----------- | ------------------------------- |
| `OLD --old` | Current project directory name. |
| `NEW --new` | New project directory name.     |

### `ask restart`

Restart the project's container.

### `ask setup`

Set up Incus and create a default flavour.

### `ask stop`

Stop the project's container now instead of waiting for idle shutdown.

### `ask run`

Run a script defined in the project's ask.toml.

| Argument                   | Description                                                                                                                                                          |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NAME --name`              | Script name defined in ask.toml.                                                                                                                                     |
| `ARGS...`                  | Arguments appended to the script's command.                                                                                                                          |
| `--gui --no-gui`           | Start a GUI session sharing the host's Wayland socket with the container. Defaults to `false`.                                                                       |
| `--create`                 | Create the project's container if it does not exist, without asking. Defaults to `false`.                                                                            |
| `--converge --no-converge` | Converge the project's container if its configuration has changed since it was last converged, without asking. --no-converge never converges it. Defaults to `None`. |

<!-- /ask:gen -->
