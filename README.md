# Ask

> _ask_ \[as:k\] liten låda -- [SAOL](https://lexin.nada.kth.se/lexin/#searchinfo=both,swe_swe,ask;)

> _ask_ _noun_
> a case for holding something -- [Cambridge Swedish/English dictionary](https://dictionary.cambridge.org/dictionary/swedish-english/ask_1)

_Ask_ creates persistent, isolated, declarative development environments for your projects.
Each project gets its own [Incus](https://linuxcontainers.org/incus) container,
provisioned with [PyInfra](https://pyinfra.com),
configured by a single `ask.toml` in the project root.
Containers shut down when idle and start again on demand, so they cost nothing when you're not using them.

## Installation

<details open>
<summary>UV</summary>

```shell
$ uv tool install git+https://github.com/raniz85/ask.git
```

</details>

<details>
<summary>pipx</summary>

```shell
$ pipx install git+https://github.com/raniz85/ask.git
```

</details>

You also need [Incus](https://linuxcontainers.org/incus) installed and initialised
(i.e. run `incus admin init`)
on your host.
`ask setup` will attempt to install and help you set up Incus,
but to get everything right,
it is best if you [do it yourself](https://linuxcontainers.org/incus/docs/main/installing/).

## Getting started

Run the one-time setup to configure Incus for rootless containers and create a default flavour:

```shell
~/ $ ask setup
```

Then, in any project directory, create its manifest:

```shell
~/ $ cd ~/my-project
~/my-project $ ask init
```

Edit the generated `ask.toml` to declare packages, bind mounts, services, tool managers, scripts and custom pyinfra taskfiles.
Shared container configuration lives in flavour files under `~/.config/ask/flavors/`.

Once configured, create the container with

```shell
~/my-project $ ask create
```

The container will be created and provisioned using your configuration.

## Daily usage

Enter the project's container with a shell:

### Start a shell

```shell
~/my-project $ ask enter
raniz@my-project ~/my-project $ _
```

Use `ask enter --root` for a root shell in the container.

### Run scripts

Run a script defined in `ask.toml` without entering the container:

```shell
~/my-project $ ask run test
```

If the name is unambiguous with other shortcuts, you can drop `run`:

```shell
~/my-project $ ask test
```

### Run arbitrary commands

Or run any command directly:

```shell
~/my-project $ ask exec uv run pytest
```

Any options that come after the command are passed on:

```shell
~/my-project $ ask exec echo --debug
--debug
```

### Start an agent

Start the default agent with the `agent` subcommand.

```shell
~/my-project $ ask agent
```

If you have multiple agents defined, you can start a specific one.

```shell
~/my-project $ ask agent claude
```

Agents can also be started by command-line aliases — `ask agent omp` is the same as `ask agent oh-my-pi`, and `ask agent vibe` is the same as `ask agent mistral-vibe`. Aliases work on the command line only, not in `ask.toml`.

If the agent name is unambigous with other shortcuts, you can drop `agent`:

```shell
~/my-project $ ask claude
```

Options following the agent name, or unknown options if no name is given, are passed on to the agent.

```shell
~/my-project $ ask agent --resume
```

### Start an IDE

IDEs are listed per flavour layer and started with the `ide` subcommand, which opens them with GUI access by default (`--no-gui` disables it).

```toml
[layers.python]
ides = [
  "pycharm",
]
```

```shell
~/my-project $ ask ide
```

If you have multiple IDEs defined, you can start a specific one, and pass options on to it.

```shell
~/my-project $ ask ide pycharm .
```

PyCharm installs the unified build (the official `pycharm-community-edition` package on Arch, JetBrains' tarball on Debian); registering a JetBrains license in the IDE unlocks the Pro features. The license state lives under `~/.config/JetBrains`, which Ask mounts into the container.

GUI access shares the host's Wayland socket with the container. X11 applications are supported through [xwayland-satellite](https://github.com/Supreeeme/xwayland-satellite), started inside the container when the first GUI session opens and stopped when the last one closes. It is used when the `xwayland-satellite` package is installed in the container: PyCharm pulls it in on Arch, and other layers can add it to their `packages`. It is not available on Debian.

### Management

To apply configuration changes explicitly, or to manage the container by hand:

```shell
~/my-project $ ask converge              # apply ask.toml to the container
~/my-project $ ask create                # create the container
~/my-project $ ask restart               # restart the container
~/my-project $ ask stop                  # stop the container now instead of waiting for idle shutdown
~/my-project $ ask destroy               # delete the container and its configuration entirely
~/ $ ask rename my-project your-project  # rename the ask and the project directory
```
