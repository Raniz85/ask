# Ask Configuration

The configuration for an ask is a combination of two files:

1. The ask manifest
2. A flavour

## Ask manifest

The ask manifest lives in the project and details project-specific configuration such as required tooling and scripts.
It is defined in a file called _ask.toml_ and is usually checked in and shared between all developers.

###

## Flavours

Flavours decide the base of the ask.
It configures the base Linux distribution, the shell, your user and any tooling you want in there.
This is a personal configuration and typically not shared with anyone else.

Flavours are defined under _$XDF_CONFIG_HOME/ask/flavors/<name>.toml_.

###
