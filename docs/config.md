# Ask Configuration

The configuration for an ask is a combination of two files:

1. The ask manifest
2. A flavour

## Ask manifest

The ask manifest lives in the project and details project-specific configuration such as required tooling and scripts.
It is defined in a file called _ask.toml_ and is usually checked in and shared between all developers.

<!-- ask:gen:manifest -->

| Key             | Type                       | Required | Description                                                                                                                                                                                |
| --------------- | -------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `packages`      | list                       | no       | Packages to install; `aur:` prefix installs from the AUR, a `-` prefix removes a package set in a lower layer.                                                                             |
| `bind_mounts`   | list                       | no       | Host paths to bind-mount into the container; `~` expands to the home directory.                                                                                                            |
| `services`      | table of string            | no       | systemd services to manage; keys are unit names (the `.service` suffix is optional), values are `enabled`, `disabled`, or `masked`. Manifest services take precedence over flavour layers. |
| `tool_managers` | list                       | no       | Tool managers to provision the project's tools with, e.g. `mise`.                                                                                                                          |
| `scripts`       | table of string            | no       | Shell scripts exposed as `ask run <name>`; keys are names, values are shell commands.                                                                                                      |
| `env`           | table of string or boolean | no       | Environment variables to set; `false` unsets the variable instead.                                                                                                                         |
| `taskfiles`     | list                       | no       | Extra pyinfra taskfiles to run last during converge; paths are relative to this file.                                                                                                      |

Known tool managers: `mise`.

<!-- /ask:gen -->

## Flavours

Flavours decide the base of the ask.
It configures the base Linux distribution, the shell, your user and any tooling you want in there.
This is a personal configuration and typically not shared with anyone else.

Flavours are defined under _$XDG_CONFIG_HOME/ask/flavors/<name>.toml_.
The file name (without `.toml`) is the flavour's name.
Exactly one flavour applies to a project:
the one whose `when.path` matches the project directory,
or — if none matches — the one marked `default = true`.

### Top-level keys

<!-- ask:gen:flavor -->

| Key            | Type           | Required | Description                                                                                                    |
| -------------- | -------------- | -------- | -------------------------------------------------------------------------------------------------------------- |
| `distribution` | string         | yes      | The Linux distribution the container is created from.                                                          |
| `default`      | boolean        | no       | Use this flavour when no other flavour's `when.path` matches. Defaults to `false`.                             |
| `when`         | table          | no       | When this flavour applies, by matching the project path.                                                       |
| `shell`        | table          | no       | The shell to install; either a name string or a table with `name` and per-shell options (e.g. `zshrc = true`). |
| `user`         | table          | no       | The container user; mirrors the calling user by default.                                                       |
| `layers`       | table of table | no       | Named layers applied bottom-up; the `base` layer always applies and cannot have conditions.                    |

Known distributions: `arch`, `debian`.

<!-- /ask:gen -->

### User

The container user mirrors the calling user when unset.

<!-- ask:gen:user -->

| Key            | Type    | Required | Description                                                               |
| -------------- | ------- | -------- | ------------------------------------------------------------------------- |
| `name`         | string  | no       | Container user name; `null` mirrors the calling user. Defaults to `null`. |
| `uid`          | integer | no       | Container user id; `null` mirrors the calling user. Defaults to `null`.   |
| `extra_groups` | list    | no       | Additional groups for the container user.                                 |
| `group`        | table   | no       | The user's primary group; mirrors the user by default.                    |

<!-- /ask:gen -->

### Layers

Layers stack configuration bottom-up: `base` (if present) always applies,
other layers apply when their `when` condition matches the project,
ordered by `order` (ties in unspecified order).
The manifest is applied as the topmost layer.

<!-- ask:gen:layer -->

| Key           | Type                       | Required | Description                                                                                                                         |
| ------------- | -------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `bind_mounts` | list                       | no       | Host paths to bind-mount into the container; `~` expands to the home directory.                                                     |
| `packages`    | list                       | no       | Packages to install; `aur:` prefix installs from the AUR, a `-` prefix removes a package set in a lower layer.                      |
| `services`    | table of string            | no       | systemd services to manage; keys are unit names (the `.service` suffix is optional), values are `enabled`, `disabled`, or `masked`. |
| `agents`      | table                      | no       | Agents to enable in the layer; agent names map to `true`/`false` or a settings table.                                               |
| `ides`        | list                       | no       | IDEs to install and expose in the layer.                                                                                            |
| `env`         | table of string or boolean | no       | Environment variables to set; `false` unsets the variable instead.                                                                  |
| `taskfiles`   | list                       | no       | Extra pyinfra taskfiles to run last during converge; paths are relative to the file declaring them.                                 |
| `order`       | integer                    | no       | Layers with lower order are applied first; equal orders are applied in unspecified order. Defaults to `0`.                          |
| `when`        | table                      | no       | Condition for the layer to apply; `null` means always. Defaults to `null`.                                                          |

Known IDEs: `clion`, `code`, `datagrip`, `goland`, `idea`, `phpstorm`, `pycharm`, `rider`, `rubymine`, `rustrover`, `webstorm`, `zed`. In a flavour, `ides` are configured per layer; the manifest has no `ides` key.

<!-- /ask:gen -->

### Agents

<!-- ask:gen:agents -->

_Per-agent settings (`[layers.<layer>.agents.<name>]`, or `true`/`false` shorthand):_

| Key          | Type                       | Required | Description                                                                                            |
| ------------ | -------------------------- | -------- | ------------------------------------------------------------------------------------------------------ |
| `enabled`    | boolean                    | no       | Whether the agent is installed; `false` removes an agent enabled in a lower layer. Defaults to `true`. |
| `options`    | table of boolean           | no       | Per-agent options, e.g. `auth = false` skips mounting the agent's credentials.                         |
| `extensions` | list                       | no       | Extensions for the agent to install; only `pi` and `oh-my-pi` support extensions.                      |
| `env`        | table of string or boolean | no       | Environment variables for this agent; `false` unsets the variable.                                     |

_Layer-level agent table (`[layers.<layer>.agents]`):_

| Key       | Type                       | Required | Description                                                                                  |
| --------- | -------------------------- | -------- | -------------------------------------------------------------------------------------------- |
| `default` | string                     | no       | Agent launched by bare `ask agent`; defaults to the first enabled agent. Defaults to `null`. |
| `env`     | table of string or boolean | no       | Environment variables shared by all agents in the layer.                                     |
| `entries` | table of table             | no       | Agent name to settings; each value may also be a bare `true`/`false` for defaults.           |

_Agent options:_

- `claude`: `auth`, `claude_md`, `config`, `skills`
- `codex`: `agents_md`, `auth`, `config`, `skills`
- `mistral-vibe`: `agents_md`, `auth`, `config`, `skills`
- `oh-my-pi`: `agents_md`, `auth`, `config`, `skills`
- `opencode`: `agents_md`, `auth`, `config`, `skills`
- `pi`: `auth`, `config`, `skills`, `system_md`

<!-- /ask:gen -->
