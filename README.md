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

```shell
$ uv tool install ask
```

You also need [Incus](https://linuxcontainers.org/incus) installed and initialised on your host.

## Getting started

Run the one-time setup to configure Incus for rootless containers and create a default flavour:

```shell
$ ask setup
```

Then, in any project directory, create its manifest:

```shell
$ cd ~/my-project
$ ask init
```

Edit the generated `ask.toml` to declare packages, bind mounts, services, tool managers and scripts.
Shared container configuration lives in flavour files under `~/.config/ask/flavors/`.

## Daily usage

Enter the project's container with a shell:

```shell
$ ask enter
Starting ask my-project...OK
Entering ask my-project...
raniz@my-project ~/my-project > _
```

The container is created on first use and converged automatically when `ask.toml` changes.

Run a script defined in `ask.toml` without entering the container:

```shell
$ ask run test
```

Or run any command directly:

```shell
$ ask exec uv run pytest
```

To apply configuration changes explicitly, or to manage the container by hand:

```shell
$ ask converge   # apply ask.toml to the container
$ ask create     # create the container
$ ask restart    # restart the container
$ ask stop       # stop the container now instead of waiting for idle shutdown
$ ask destroy    # delete the container and its configuration entirely
```
