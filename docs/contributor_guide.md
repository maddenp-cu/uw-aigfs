# Contributor Guide

[← Back to Index](index.md)

Welcome to the `uw-aigfs` Contributor Guide. Please familiarize yourself with and follow the procedures in the sections below before submitting changes.

> **Note:** Before starting work on a new feature, bug fix, or other change, please open an [Issue](https://github.com/NOAA-GSL/uw-aigfs/issues) to propose your change and solicit feedback from other developers. This helps avoid duplicate efforts or wasted work.

## Table of Contents

- [Developer Setup](#developer-setup)
- [Code Quality](#code-quality)
- [API Documentation](#api-documentation)
- [Fork and PR Model](#fork-and-pr-model)
  - [Overview](#overview)
  - [Specifics for uw-aigfs](#specifics-for-uw-aigfs)
  - [Merging](#merging)
  - [Need Help?](#need-help)
- [Repository Structure](#repository-structure)
  - [Key Concepts](#key-concepts)
- [Deploying Realtime AIGFS on Ursa](#deploying-realtime-aigfs-on-ursa)
  - [Production User Deploy Procedure](#production-user-deploy-procedure)
  - [Developer Testing Procedure](#developer-testing-procedure)
  - [Application Directory Layout](#application-directory-layout)
- [Containerized AIGFS](#containerized-aigfs)

## Developer Setup

> **Note:** The installation of conda environments is only meant for systems other than WCOSS. Do not run this step on WCOSS.

`uw-aigfs` installs and manages its own conda installation in the `conda/` subdirectory of the repository root. To set up a development environment, run:

```bash
make devenv
```

This installs [Miniforge](https://github.com/conda-forge/miniforge) into `conda/`, creates the `aigfs` conda environment from `etc/env/aigfs.yaml`, then installs additional developer tools (linters, formatters, test runners) listed in `etc/env/dev.yaml`.

This command can also be run later to upgrade a non-development environment to a developer environment.

After the initial installation, activate the environment in a fresh shell with:

```bash
source bin/activate-<platform>
```

where `<platform>` is `ursa` or `wcoss2`, or `conda` on a developer workstation (see the [User Guide](user_guide.md#install) for details).

> **Note on disk space:** The conda installation requires several gigabytes of disk space. Clone `uw-aigfs` to a location with a sufficiently large disk quota -- not your HPC home directory.

## Code Quality

Several `make` targets are available in an activated `aigfs` development environment:

| Target           | Description                                                                                                                                                                             |
|------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `make docs`      | Build HTML API docs with [pdoc](https://pdoc.dev/) into `docs/api/`                                                                                                                     |
| `make format`    | Format Python with [ruff](https://docs.astral.sh/ruff/), Bash with [go-shfmt](https://github.com/mvdan/sh), and JSON data with [jq](https://jqlang.org/)                                |
| `make lint`      | Lint Python  with [ruff](https://docs.astral.sh/ruff/), Bash  with [shellcheck](https://www.shellcheck.net/), and YAML data with [yamllint](https://yamllint.readthedocs.io/en/stable/) |
| `make typecheck` | Typecheck Python with [mypy](https://mypy-lang.org/)                                                                                                                                    |
| `make unittest`  | Run unit tests and report coverage with [pytest](https://docs.pytest.org/) and [coverage](https://coverage.readthedocs.io/en/)                                                          |
| `make test`      | Equivalent to `make lint && make typecheck && make unittest`                                                                                                                            |

Configuration for `ruff`, `mypy`, `pytest`, and `coverage` is provided by `pyproject.toml`, `shellcheck` by `.shellcheckrc`, and `yamllint` by `.yamllint.yaml`, all in the repo root.

A useful development idiom is:

```bash
make format && make test
```

This formats the code, then runs the linter, typechecker, and the unit tests. The order is intentional:

- **`format`** catches certain syntax errors that would cause other tools to fail (and could change line numbers in their reports).
- **`lint`** provides a fast first check for obvious errors and anti-patterns.
- **`typecheck`** checks for problematic use of incompatible types in function/method arguments and return values.
- **`unittest`** runs higher-level semantic-correctness checks once syntax is clean.

All checks are run by CI against every pull request. Ensure your code is formatted and tests pass locally before opening a PR, and when updating code during the PR process.

### API Documentation

API documentation for the `aigfs` Python module is generated automatically by `pdoc` from source-code docstrings. To build it locally:

```bash
make docs
```

Output is written to `docs/api/` (excluded from version control). Open `docs/api/index.html` in a browser to preview the API documentation prior to the PR process.

The docs workflow (`.github/workflows/docs.yaml`) rebuilds and publishes the API docs to GitHub Pages automatically on every push to `main`.

## Fork and PR Model

### Overview

Contributions to `uw-aigfs` are made via a [Fork](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/about-forks) and [Pull Request (PR)](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests) model. The general steps are:

1. [Fork](https://docs.github.com/en/get-started/exploring-projects-on-github/contributing-to-a-project#forking-a-repository) the [uw-aigfs repository](https://github.com/NOAA-GSL/uw-aigfs) into your personal GitHub account.
2. [Clone](https://docs.github.com/en/get-started/exploring-projects-on-github/contributing-to-a-project) your fork onto your development system.
3. [Create an Issue](https://github.com/NOAA-GSL/uw-aigfs/issues/new) to discuss your proposed change before starting work.
4. [Create a branch](https://docs.github.com/en/get-started/exploring-projects-on-github/contributing-to-a-project#creating-a-branch-to-work-on) in your clone for your changes.
5. [Make, commit, and push changes](https://docs.github.com/en/get-started/exploring-projects-on-github/contributing-to-a-project#making-and-pushing-changes) in your clone to your fork. Refer to the [Developer Setup](#developer-setup) section for formatting and testing instructions.
6. [Create a pull request](https://docs.github.com/en/get-started/exploring-projects-on-github/contributing-to-a-project#making-a-pull-request) to merge your changes into the main repository.

For future contributions, either delete and recreate your fork, or configure the official `uw-aigfs` repository as a [remote](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/configuring-a-remote-repository-for-a-fork) and [sync upstream changes](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/syncing-a-fork) to stay up-to-date.

### Specifics for uw-aigfs

When creating your PR, please follow these guidelines:

- Target base repository `NOAA-GSL/uw-aigfs` and base branch `main`.
- Complete the PR description template. Provide an informative summary of your contribution and mark the appropriate checklist items.
- Initially open your PR as a [draft pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests#draft-pull-requests).
- Visit the _Files changed_ tab and add inline comments on lines you think reviewers will benefit from. Proactively answering anticipated questions saves review time.
- Once your draft is marked up, click _Ready for review_ on the _Conversation_ tab.

A default set of reviewers will be added automatically. You may add others if appropriate. Respond to reviewer comments as needed, pushing additional commits to your branch. Your PR will update automatically.

### Merging

Your PR is ready to merge when:

1. It has been approved by a required number of `uw-aigfs` core-developer reviewers.
2. All required CI checks have passed.

These criteria and their current statuses are shown at the bottom of the PR's _Conversation_ tab. CI checks take some time to run -- please be patient.

If you have write access to the repository, you may merge your PR yourself once the above conditions are met. Otherwise, a core developer will merge it for you.

### Need Help?

Use the _Conversation_ tab of your PR to ask for help with any difficulties you encounter during the contribution process.

## Repository Structure

```
├── bin                            # Automation tools
│   ├── activate-<platform>        # Source to activate AIGFS environment for <platform>
│   ├── post                       # Post-processing script
│   ├── run                        # Support for Makefile targets
│   └── setup                      # Executable wrapper for aigfs.setup module
├── conda                          # Managed conda installation (created by make [dev]env)
├── docs                           # User and contributor documentation
├── etc                            # Configuration files, etc.
│   ├── ansible                    # Ansible deployment assets
│   ├── app                        # AIGFS configuration files
│   ├── env                        # Conda environment definitions
│   │   ├── aigfs.yaml             # Core AIGFS environment definition
│   │   └── dev.yaml               # Developer packages
│   ├── grib-in.yaml               # Config for extracting GRIB messages to netCDF ICs
│   ├── grib-out.json              # Config for writing GRIB forecast data
│   ├── modulefiles                # System modules
│   ├── oci                        # Container support files
│   │   ├── Containerfile          # Container image build recipe
│   │   └── build                  # In-image build script
│   ├── platform                   # Per-platform YAML overrides
│   └── workflow                   # Workflow files
│       ├── ecflow.yaml            # ecFlow base config
│       └── rocoto.yaml            # Rocoto base config
├── lib                            # Python library code
│   └── aigfs                      # The AIGFS python package
│       ├── conftest.py            # Unit-test fixtures
│       ├── drivers                # AIGFS component drivers
│       │   ├── *.jsonschema       # Config schema
│       │   ├── *.py               # AIGFS component driver
│       │   └── utils              # Shared driver utilities
│       │       ├── grib2writer.py # GRIB2 writing support
│       │       └── tasks.py       # Shared driver tasks
│       ├── common.py              # Shared logic
│       ├── setup.py               # Logic for preparing AIGFS assets
│       └── validation.py          # Config validation
├── Makefile                       # Provides automation targets
├── pyproject.toml                 # Code-quality tool configuration
└── README.md                      # Top-level documentation
```

Additionally, each Python `.py` module is accompanied by a `_test.py` unit-test module.

### Key Concepts

**Drivers** (`drivers/`) implement [uwtools](https://uwtools.readthedocs.io/en/2.20.0/) driver classes using the [iotaa](https://github.com/maddenp/iotaa) task framework. Each driver exposes tasks (Python methods decorated with `@task`, `@collection`, or `@external`) that declare their inputs and outputs as `Asset` objects. The `uw execute` command (called from Rocoto job scripts) resolves and runs these tasks.

**Configuration** follows the `uwtools` YAML model. `etc/base.yaml` is the baseline; it is merged with workflow and platform configs, then with any user-provided YAML configs by `bin/setup` using `uwtools.api.config.compose`. The resulting `aigfs.yaml` is the single source of truth at runtime.

**Workflow** is managed by [Rocoto](https://github.com/NOAA-GSL/rocoto). The `etc/workflow/rocoto.yaml` template is realized by `uwtools` to produce `rocoto.xml`. Task dependencies (prep → forecast → post) are expressed in that template.

When adding a new workflow stage, you will typically need to:

1. Add a new driver module in `lib/aigfs/drivers/`.
1. Add a unit-test module alongside the driver module.
1. Add a `.jsonschema` file for validation of the driver's config alongside the driver module.
1. Add corresponding configuration block(s) in `etc/base.yaml` and potentially in the `etc/platform/<system>.yaml` configs.
1. Add new workflow configuration in `etc/workflow/<engine>.yaml`.
1. Update this documentation.

## Deploying Realtime AIGFS on Ursa

### Production User Deploy Procedure

As user `role.rtaigfs`, `cd` to the appropriate scratch workspace, then:

```
$ git clone https://github.com/NOAA-GSL/uw-aigfs.git rtaigfs
$ cd rtaigfs/
$ make env
$ make deploy playbook=rtaigfs-ursa
```

### Developer Testing Procedure

The `rtaigfs` Ansible playbook is configured to install the crontab only for the production user, so developers can follow the procedure above to obtain an application directory, after which they can run `app/bin/run` iteratively to execute the workflow. Before iterating the workflow, they should verify that settings in `app/rtaigfs.yaml` are appropriate -- especially e.g. that the `app.platform.scheduler.account` value is correct -- and edit as needed.

### Application Directory Layout

If these commands complete successfully, an `app/` subdirectory should have been created and populated with assets necessary for execution of realtime AIGFS runs:

```
app/
├── bin              # Executables
├── cycles           # Root of yyyymmdd/hh cycle run directories
├── model            # AIGFS model files
├── rtaigfs.log      # Log file from latest run
├── rtaigfs.log.last # Log file from previous run (created after first run)
└── rtaigfs.yaml     # Parameterized configuration
```

Additionally, `crontab -l` should show entries for running AIGFS and for emailing a daily production report.

After deployment, *no manual changes* should be made to the contents of the git clone or any of its subdirectories or files. All updates should be performed via the following recipe:

1. Update the `uw-aigfs` git repo via PR.
2. Unload the `role.rtaigfs` crontab: `crontab -r`.
3. Update the git clone on Ursa: `git pull`.
4. If the conda installation must be updated: `rm -rf conda && make env`.
5. Update the deployment: `make deploy playbook=rtaigfs-ursa`.

The structure of a `yyyymmdd/hh` cycle run directory is as follows:

```
├── aigfs.yaml       # Fully realized AIGFS config 
├── forecast         # Run directory for forecast task
├── logs             # Rocoto logs
│   ├── <task>.log   # Task log (one per task execution)
│   └── workflow.log # Rocoto general log
├── post_*           # Run directory for post task (one per leadtime)
├── prep             # Run directory for prep task
├── rocoto.db        # Rocoto sqlite3 database
├── rocoto_lock.db   # Rocoto database lockfile
└── rocoto.xml       # Rocoto workflow document
```

Per-task run directories have structure and content specific to each task, but since each task is executed via a `uwtools` driver, several common files can be expected:

```
├── runscript.<driver>      # Executable driver runscript
├── runscript.<driver>.done # A sentinel file created if driver executed successfully
└── runscript.<driver>.out  # Driver execution output
```

Values for `<driver>` are `aigfs_ics`, `aigfs_inference`, and `aigfs_post`.

## Containerized AIGFS

**This section contains work-in-progress development notes and is unlikely to be complete or fully correct.**

To build an [OCI](https://opencontainers.org/) container image containing the AIGFS application and its supporting software runtime from the root directory of a git clone of this repository:

1. Ensure that there are no uncommitted changes and no unversioned files in the clone. Commit (or stash) any changes, and run `git clean -dfx` to remove any unversioned files. **Be sure to back up anything you do not want to lose first. For example, if you previously ran `make env` or similar to create a `conda/` installation in the clone root, you may want to temporarily move it elsewhere and move it back later.**
2. Copy the AIGFS model files (`params/` and `stats/` -- see the [User Guide](user_guide.md#the-model-directory)) into a `model/` directory in the clone root.
3. Ensure that the `podman` and `qemu-user-static` (Debian names; translate as needed for other Linux OSes) OS packages are installed.
4. Optionally, run `podman system prune --all` to clear old `podman` resources. **Be sure you don't need anything listed by e.g. `podman images`.**
5. Run `make container`.

You may optionally push the resulting container image to a remote container registry, but instructions for doing so are beyond the scope of this documentation.

You may now run commands inside the container. In a new, empty directory, create `user.yaml` with content similar to

``` yaml
app:
  first_cycle: !datetime 2026-09-16T12
  last_cycle: !datetime 2026-09-16T12
```

To set up the `aigfs.yaml` configuration and run the `prep` step on a Linux system with `podman`:

``` bash
run="podman run --rm -v .:/run/aigfs ghcr.io/maddenp-cu/aigfs:latest run cmd"
$run setup --platform oci /run/aigfs/user.yaml
$run uw execute --module aigfs.drivers.ics --classname AIGFSICs --task run --config /run/aigfs/aigfs.yaml --cycle 2026-09-16T06 --key-path prep
```

- `-v .:/run/aigfs` instructs `podman` to *bind mount* the current directory to the path `/run/aigfs` inside the container. This is the same path that will appear as `app.rundir` in the generated `aigfs.yaml`.
- `ghcr.io/maddenp-cu/aigfs:latest` identifies the container image to use. Since `make container` tagged the container image created above with this tag, the image should be found locally. (Otherwise, it would be downloaded from the remote container registry it is published to.)
- `run cmd` executes the `bin/run` script copied from the repo into the container with the `cmd` argument, which calls a function called `cmd()` that runs the remaining arguments with the AIGFS conda environment activated. (The container image is built such that the `run` script will be on `PATH` inside the container.)
- Note that, from the perspective of the commands run in the container, `/run/aigfs` refers to the current directory on the host system.

To run the same plus the `forecast` step on Ursa with `apptainer`:

``` bash
apptainer pull aigfs.sif docker://ghcr.io/maddenp-cu/aigfs:latest
run="apptainer exec -B .:/run/aigfs aigfs.sif run cmd"
$run setup --platform oci /run/aigfs/user.yaml
$run uw execute --module aigfs.drivers.ics --classname AIGFSICs --task run --config /run/aigfs/aigfs.yaml --cycle 2026-09-16T06 --key-path prep
srun --exclusive --nodes 1 --time 00:20:00 $run uw execute --module aigfs.drivers.inference --classname AIGFSInference --task run --config /run/aigfs/aigfs.yaml --cycle 2026-09-16T06 --key-path forecast
```

- The `apptainer pull` command fetches the OCI container and converts it to Apptainer's format, saving it as `aigfs.sif`.
- The `-B` argument to `apptainer` performs the same bind mount as `-v` for `podman`.
- The `forecast` step needs to run on a batch node, so it executed under `srun`.

[← Back to Index](index.md)
